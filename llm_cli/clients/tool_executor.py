# llm_cli/clients/tool_executor.py

import json
import logging
from typing import Any

from llm_cli.clients.config import config_manager
from llm_cli.clients.exceptions import ConfigurationError
from llm_cli.modules.models import ContentPart, DataSource
from llm_cli.modules.tool_registry import registry
from llm_cli.security.cass import RiskLevel
from llm_cli.ui import (
    console,
    print_panel,
    report_error,
)

from .tool_executor_security import (
    run_code_safety_check,
    run_dual_llm_verification,
    run_security_checks,
    verify_pqc_signature,
)
from .tool_executor_types import AgentContext, ToolExecutionContext
from .tool_executor_ui import (
    display_reasoning,
    get_approval_prompt,
)
from .tool_executor_utils import (
    create_error_response,
    display_execution_details,
    print_tool_output,
    truncate_output,
)

logger = logging.getLogger(__name__)


def execute_tool_call(
    session: AgentContext, part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    """Main orchestration for tool execution."""
    ctx = ToolExecutionContext(session, part, duration)
    if not part.function_call:
        return None

    try:
        # 1. Access Control & Identity Proof (ABAC) - Fast, local gatekeeping
        if not run_security_checks(ctx):
            return create_error_response(ctx), None

        display_reasoning(ctx)

        # 2. Static Analysis (AST) - Local, deterministically detects dangerous code
        if not run_code_safety_check(ctx):
            return create_error_response(ctx), None

        # 3. Dynamic Intent Verification (Dual LLM)
        # Slower, remote, but only for "safe" code
        if not run_dual_llm_verification(ctx):
            return create_error_response(ctx), None

        # 4. Final Human-in-the-Loop Validation
        if not _run_pre_approval_validation(ctx):
            return create_error_response(ctx), None

        if not _get_user_approval(ctx):
            if ctx.aborted:
                return None
            return create_error_response(ctx), None

        if not _execute_function(ctx):
            return create_error_response(ctx), None

        if not _post_process_result(ctx):
            return create_error_response(ctx), None

    except Exception as e:
        logger.exception("Unexpected error during tool execution")
        ctx.error_message = f"[ERROR] Internal Error: {e}"
        return create_error_response(ctx), None

    response = ContentPart(
        function_response={
            "id": ctx.tool_id,
            "call_id": ctx.call_id,
            "name": ctx.name,
            "response": {"result": ctx.result_data},
        },
        thought_signature=ctx.thought_signature,
    )
    return response, ctx.injected_data


def _run_pre_approval_validation(ctx: ToolExecutionContext) -> bool:
    """Runs tool-specific validation before asking for user approval."""
    tool_entry = registry.tools.get(ctx.name)
    if not tool_entry:
        return True

    # 1. Basic Parameter Validation (Check required fields)
    params_spec = tool_entry.get("parameters", {})
    required_fields = params_spec.get("required", [])
    missing = [f for f in required_fields if f not in ctx.args]
    if missing:
        ctx.error_message = f"Error: Missing required parameter(s): {', '.join(missing)}"
        report_error(ctx.error_message)
        return False

    validate_func = tool_entry.get("validate")
    if not validate_func:
        return True

    try:
        res = validate_func(**ctx.args)
        if res is True:
            return True
        ctx.error_message = (
            res if isinstance(res, str) else f"Validation failed for tool '{ctx.name}'."
        )
        report_error(ctx.error_message)
        return False
    except Exception as e:
        ctx.error_message = f"[ERROR] Validation error: {e}"
        report_error(ctx.error_message)
        return False


def _get_user_approval(ctx: ToolExecutionContext) -> bool:
    """
    Handles user approval based on the tool's risk level and security policy.
    Dual LLM warnings or high-risk tools always require manual approval.
    """
    # 1. Resolve Auto-Approval Policy
    # Policy order: none (strictest) < low < medium
    auto_approval_policy = (config_manager.get("security", "auto_approval_level") or "none").lower()

    # 2. Check for bypass conditions
    # If any warnings were flagged, we MUST ask for approval regardless of policy.
    if not ctx.security_warnings:
        is_auto_approved = False

        if auto_approval_policy == "medium":
            # Allow low and medium risk tools
            if ctx.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                is_auto_approved = True
        elif auto_approval_policy == "low":
            # Only allow low risk tools
            if ctx.risk_level == RiskLevel.LOW:
                is_auto_approved = True

        if is_auto_approved:
            logger.debug(f"Auto-approving '{ctx.name}' (Risk: {ctx.risk_level.value})")
            delay = float(config_manager.get("general", "auto_approval_delay") or 0.0)
            display_execution_details(ctx, auto_approved=True, delay=delay)

            # Brief pause for human reading of reasoning/args before execution.
            if delay > 0:
                import time

                try:
                    time.sleep(delay)
                except (KeyboardInterrupt, EOFError):
                    ctx.error_message = "Operation cancelled by user."
                    ctx.aborted = True
                    return False

            return True

    # 3. Manual Approval Flow
    display_execution_details(ctx, auto_approved=False)

    if ctx.security_warnings:
        for title, warning in ctx.security_warnings:
            print_panel(
                warning,
                title=title,
                border_style="red",
            )

    try:
        # Use a risk-level-aware prompt (defined alongside the visual badge in
        # tool_executor_ui._RISK_STYLE). HIGH already shows
        # "[bold yellow]WARNING[/bold yellow] HIGH RISK operation",
        # so we no longer need a separate execute_python special-case here.
        prompt_msg = get_approval_prompt(ctx)

        user_input = ctx.session._get_input(
            prompt_msg,
            exit_on_escape=True,
            raise_on_interrupt=True,
        )
    except (KeyboardInterrupt, EOFError):
        ctx.error_message = "Operation cancelled by user."
        ctx.aborted = True
        return False

    if user_input.lower() not in ("y", "ｙ"):
        ctx.error_message = (
            f"Rejected by user. Feedback: {user_input}"
            if user_input.lower() not in ("n", "ｎ")
            else "Error: Operation denied."
        )
        return False
    return True


def _execute_function(ctx: ToolExecutionContext) -> bool:
    tool_entry = registry.tools[ctx.name]
    if not tool_entry.get("interactive", False):
        console.print(f"[bold yellow]Executing {ctx.name}...[/bold yellow]")

    try:
        result = tool_entry["func"](
            __audit_model__=ctx.session.client.model,
            __security_requirements__=ctx.security_requirements,
            **ctx.args,
        )

        # 1. Process injected data BEFORE signing
        # Some tools return a dict with __llm_cli_data__ for side-channel info.
        if isinstance(result, dict) and "__llm_cli_data__" in result:
            data_payload = result.pop("__llm_cli_data__")
            ctx.injected_data = (
                data_payload if isinstance(data_payload, DataSource) else DataSource(**data_payload)
            )

        # 2. Bi-directional Verification: Ensure the result is signed.
        # Remote tools (MCP) are signed by the server. Local tools are signed here
        # to satisfy the verification requirement in 'high' security mode.
        is_already_signed = False
        if isinstance(result, dict) and "pqc_signature" in result:
            is_already_signed = True
        elif isinstance(result, str) and result.strip().startswith("{"):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "pqc_signature" in parsed:
                    is_already_signed = True
            except (json.JSONDecodeError, TypeError):
                pass

        if not is_already_signed and not ctx.server_name:
            # Only sign if it's not already an error message and it's a local tool.
            # Remote tools (MCP) are signed by the server if Zero Trust is enabled.
            res_str = str(result)
            if not (
                res_str.startswith("[ERROR]")
                or "[DENIED] Access Denied:" in res_str
                or res_str.startswith("Error:")
            ):
                from llm_cli.security.pqc import PQCAgilityManager, sign_tool_result

                variant = PQCAgilityManager.get_required_level(ctx.name, args=ctx.args)
                result = sign_tool_result(res_str, variant=variant)

        ctx.result_data = result
        return True
    except ConfigurationError as e:
        report_error(str(e))
        ctx.error_message = "Function unavailable. Check API configuration."
        return False
    except Exception as e:
        report_error(f"Tool execution failed: {e}")
        ctx.error_message = str(e)
        return False


def _post_process_result(ctx: ToolExecutionContext) -> bool:
    security_level = config_manager.get("security", "security_level") or "high"

    # Check if this is an MCP server with Zero Trust disabled.
    is_mcp_zero_trust = True
    if ctx.server_name:
        mcp_servers = config_manager.get_mcp_servers()
        for s in mcp_servers:
            if s.get("name") == ctx.server_name:
                is_mcp_zero_trust = s.get("zero_trust", False)
                break

    try:
        ctx.result_data = verify_pqc_signature(
            ctx.result_data, ctx.risk_level, server_id=ctx.server_name
        )
    except ValueError as e:
        # If Zero Trust is disabled for this MCP server, we don't treat
        # missing/invalid signatures as a fatal error even in 'high' mode.
        if security_level == "high" and is_mcp_zero_trust:
            ctx.error_message = str(e)
            return False
        else:
            from llm_cli.ui import report_warning

            report_warning(f"Insecure Tool Response: {e} (Verification Skipped)")

            # Fallback: Recursively strip the PQC envelope to show only the result
            # even if we couldn't verify the signature.

            def unwrap(data: Any, depth: int = 0) -> Any:
                if depth > 5:
                    return data

                # Handle stringified JSON
                if isinstance(data, str) and data.strip().startswith("{"):
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and (
                            "pqc_signature" in parsed or "result" in parsed
                        ):
                            return unwrap(parsed, depth + 1)
                    except Exception:
                        pass

                # Handle dict with signature/result
                if isinstance(data, dict):
                    if "result" in data:
                        return unwrap(data["result"], depth + 1)
                    if "response" in data:
                        return unwrap(data["response"], depth + 1)

                return data

            ctx.result_data = unwrap(ctx.result_data)

    res_str = truncate_output(str(ctx.result_data))
    ctx.result_data = res_str
    print_tool_output(res_str)
    return True
