# llm_cli/clients/tool_executor.py

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from rich.markup import escape

from llm_cli.clients.config import config_manager
from llm_cli.clients.exceptions import ConfigurationError
from llm_cli.modules.models import ContentPart, DataSource
from llm_cli.modules.tool_registry import registry
from llm_cli.security.cass import RiskLevel, SecurityPosture
from llm_cli.security.static_analyzer import analyze_python_safety
from llm_cli.ui import (
    console,
    print_block,
    report_error,
    report_success,
)

from .tool_executor_ui import (
    display_reasoning,
    display_tool_request,
    preview_diff,
    preview_edit_diff,
    preview_python_code,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentContext(Protocol):
    """Protocol for Agent sessions (e.g. ChatSession)."""

    @property
    def client(self) -> Any: ...
    def _get_input(self, message: str, **kwargs: Any) -> str: ...


@dataclass
class ToolExecutionContext:
    """Carries tool-specific state through the execution pipeline."""

    session: AgentContext
    part: ContentPart
    duration: float | None = None
    # Derived fields
    tool_id: str = "unknown"
    call_id: str | None = None
    name: str = "unknown"
    args: dict[str, Any] = field(default_factory=dict)
    thought_signature: str | None = None
    # Output fields
    result_data: Any = None
    injected_data: DataSource | None = None
    error_message: str | None = None
    aborted: bool = False

    # Security fields
    risk_level: RiskLevel = field(init=False)
    security_requirements: SecurityPosture = field(init=False)
    server_name: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        call = self.part.function_call
        if call:
            self.tool_id = call.get("id", "unknown")
            self.call_id = call.get("call_id")
            self.name = call["name"]
            self.args = call.get("args", {})
            self.thought_signature = self.part.thought_signature

        from llm_cli.security.cass import cass_orchestrator as cass

        # Strip MCP server prefix (e.g., 'gpu__') for risk evaluation
        parts = self.name.split("__")
        if len(parts) > 1:
            self.server_name = parts[0]
            base_name = "__".join(parts[1:])
        else:
            self.server_name = None
            base_name = self.name

        self.risk_level = cass.evaluate_risk(base_name)
        self.security_requirements = cass.get_security_requirements(base_name)


def execute_tool_call(
    session: "AgentContext", part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    """Main orchestration for tool execution."""
    ctx = ToolExecutionContext(session, part, duration)
    if not part.function_call:
        return None

    try:
        if not _run_security_checks(ctx):
            return _create_error_response(ctx), None

        display_reasoning(ctx)

        if not _run_code_safety_check(ctx):
            return _create_error_response(ctx), None

        if not _run_pre_approval_validation(ctx):
            return _create_error_response(ctx), None

        if not _get_user_approval(ctx):
            if ctx.aborted:
                return None
            return _create_error_response(ctx), None

        if not _execute_function(ctx):
            return _create_error_response(ctx), None

        if not _post_process_result(ctx):
            return _create_error_response(ctx), None

    except Exception as e:
        logger.exception("Unexpected error during tool execution")
        ctx.error_message = f"Internal Error: {e}"
        return _create_error_response(ctx), None

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


def _run_security_checks(ctx: ToolExecutionContext) -> bool:
    """Checks Security Policy Engine, PQC Identity, and Dual LLM Verification."""
    from llm_cli.security.identity import IdentityManager

    has_pqc = False
    try:
        IdentityManager._ensure_keys()
        has_pqc = True
    except Exception:
        err = f"Security Violation: Tool '{ctx.name}' blocked. Secure identity missing."
        report_error(err)
        ctx.error_message = err
        return False

    # 1. Dual LLM Verification (Dynamic Intent Check)
    if ctx.security_requirements.get("require_dual_llm_verification"):
        user_prompt = ctx.session.client.get_last_user_prompt()
        if user_prompt:
            from llm_cli.security.dual_llm_verifier import verify_tool_call

            console.print(f"[dim blue]🛡️  Dual LLM verifying '{ctx.name}'...[/dim blue]")
            is_safe, reason = verify_tool_call(user_prompt, ctx.name, ctx.args)
            if not is_safe:
                err = f"Dual LLM Violation: Tool '{ctx.name}' blocked. Reason: {reason}"
                report_error(err)
                ctx.error_message = err
                return False
            else:
                report_success(f"Dual LLM Verified: {reason or 'Matched user intent'}")

    from llm_cli.security.policy import EvaluationContext, policy_engine

    user_prompt = ctx.session.client.get_last_user_prompt() or "No user prompt found"
    eval_ctx: EvaluationContext = {
        "user_id": str(
            config_manager.get("security", "default_user_id") or "current_user"
        ),
        "user_prompt": user_prompt,
        "has_pqc_proof": has_pqc,
    }
    if not policy_engine.evaluate(ctx.name, ctx.args, eval_ctx):
        ctx.error_message = f"Policy Violation: Execution of '{ctx.name}' denied."
        report_error(ctx.error_message)
        return False
    return True


def _run_code_safety_check(ctx: ToolExecutionContext) -> bool:
    high_risk_tools = set(config_manager.get("security", "high_risk_tools") or [])
    if not (
        ctx.name in high_risk_tools
        or ctx.name == "execute_python"
        or ctx.name.endswith("__execute_python")
    ):
        return True

    code = ctx.args.get("code", "")
    if not code:
        return True

    is_safe, issues = analyze_python_safety(code)
    if not is_safe:
        issue_str = "\n".join(f"• {i}" for i in issues)
        print_block(
            f"[bold red]⚠️  Security Violation:[/bold red]\n{issue_str}",
            title="Static Analysis Risk",
            style="red",
        )
        ctx.error_message = "Static analysis failed. Execution blocked by policy."
        return False
    return True


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
        ctx.error_message = (
            f"Error: Missing required parameter(s): {', '.join(missing)}"
        )
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
        ctx.error_message = f"Validation error: {e}"
        report_error(ctx.error_message)
        return False


def _get_user_approval(ctx: ToolExecutionContext) -> bool:
    tool_entry = registry.tools.get(ctx.name, {})
    skip_approval = tool_entry.get("skip_approval", False)

    if skip_approval:
        return True

    display_tool_request(ctx)
    if any(k in ctx.name for k in ("write_file", "create_or_overwrite_file")):
        preview_diff(ctx.args)
    elif "edit_file" in ctx.name:
        preview_edit_diff(ctx.args)
    elif "execute_python" in ctx.name:
        preview_python_code(ctx.args)

    try:
        user_input = ctx.session._get_input(
            "Allow execution? (y/N or feedback): ",
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
        console.print(f"[bold yellow]🏃 Executing {ctx.name}...[/bold yellow]")

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
                data_payload
                if isinstance(data_payload, DataSource)
                else DataSource(**data_payload)
            )

        # 2. Bi-directional Verification: Ensure the result is signed.
        # Remote tools (MCP) are signed by the server. Local tools are signed here
        # to satisfy the verification requirement in 'high' security mode.
        if not (isinstance(result, dict) and "pqc_signature" in result):
            # Only sign if it's not already an error message
            res_str = str(result)
            if not (res_str.startswith("Error:") or "⛔" in res_str):
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

    try:
        ctx.result_data = _verify_pqc_signature(
            ctx.result_data, ctx.risk_level, server_id=ctx.server_name
        )
    except ValueError as e:
        if security_level == "high":
            ctx.error_message = str(e)
            return False
        else:
            from llm_cli.ui import report_warning

            report_warning(f"Insecure Tool Response: {e} (Standard Mode)")
            # Fallback to the original result without validation
            if isinstance(ctx.result_data, dict):
                ctx.result_data = ctx.result_data.get(
                    "result", ctx.result_data.get("response", ctx.result_data)
                )

    res_str = _truncate_output(str(ctx.result_data))
    ctx.result_data = res_str
    print_block(
        escape(res_str), title="[bold green]✅ Tool Output[/bold green]", style="green"
    )
    return True


def _truncate_output(res_str: str) -> str:
    from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES

    lines = res_str.splitlines()
    if len(lines) > MAX_OUTPUT_LINES or len(res_str) > MAX_OUTPUT_CHARS:
        res_str = "\n".join(lines[:MAX_OUTPUT_LINES])[:MAX_OUTPUT_CHARS]
        shown_lines = len(res_str.splitlines())
        res_str += (
            f"\n\n... (Output truncated. Shown {shown_lines} of {len(lines)} lines, "
            f"{len(res_str)} of {len(res_str)} chars.)"
        )
    return res_str


def _create_error_response(ctx: ToolExecutionContext) -> ContentPart:
    err = ctx.error_message or "Unknown error"
    if not err.startswith("Error:") and not err.startswith("Security Error:"):
        err = f"Error: {err}"
    return ContentPart(
        function_response={
            "id": ctx.tool_id,
            "call_id": ctx.call_id,
            "name": ctx.name,
            "response": {"result": err},
        },
        thought_signature=ctx.thought_signature,
    )


def _verify_pqc_signature(
    result_data: Any, risk_level: Any, server_id: str | None = None
) -> Any:
    # Handle cases where the result is a JSON string (common in MCP transport)
    original_data = result_data
    if isinstance(result_data, str) and result_data.strip().startswith("{"):
        import json

        try:
            parsed = json.loads(result_data)
            if isinstance(parsed, dict) and "pqc_signature" in parsed:
                result_data = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    if not (isinstance(result_data, dict) and "pqc_signature" in result_data):
        # If it's not a signed dictionary, it might be a raw string or error.
        # But for 'high' security standard, we strictly enforce signatures on success.
        msg = (
            "Security Violation: Missing PQC signature for tool response "
            f"(Risk: {risk_level.value})."
        )
        # Check if the result is actually an error message from the tool
        if isinstance(original_data, str) and (
            "Error:" in original_data or "⛔" in original_data
        ):
            return original_data

        report_error(f"PQC Enforcement: {msg}")
        raise ValueError(msg)

    import base64

    from llm_cli.security.identity import IdentityManager
    from llm_cli.security.pqc import PQCProvider

    sig_b64 = result_data.get("pqc_signature", "")
    v_id = result_data.get("verification_id", "unknown")
    variant = result_data.get("algorithm", "ML-DSA-65")
    content = str(result_data.get("result", result_data.get("response", result_data)))

    try:
        # Use server_id if provided (for MCP), otherwise use local identity
        target_entity = server_id or IdentityManager.get_local_identity()
        pqc_pub = IdentityManager._get_trusted_pqc_public_key(target_entity, variant)

        if not pqc_pub:
            raise ValueError(f"No trusted PQC key found for '{target_entity}'.")

        sig = base64.urlsafe_b64decode(str(sig_b64) + "==")
        if PQCProvider.verify(
            f"{v_id}:{content}".encode(), sig, pqc_pub, variant=variant
        ):
            report_success(f"PQC Verified ({variant}) (ID: {v_id})")
            return content
        else:
            raise ValueError(f"PQC Signature Verification Failed (ID: {v_id})")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        logger.warning(f"Signature verification error: {e}")
    return content
