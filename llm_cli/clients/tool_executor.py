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
    get_approval_prompt,
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
    security_warnings: list[tuple[str, str]] = field(default_factory=list)

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
        # 1. Access Control & Identity Proof (ABAC) - Fast, local gatekeeping
        if not _run_security_checks(ctx):
            return _create_error_response(ctx), None

        display_reasoning(ctx)

        # 2. Static Analysis (AST) - Local, deterministically detects dangerous code
        if not _run_code_safety_check(ctx):
            return _create_error_response(ctx), None

        # 3. Dynamic Intent Verification (Dual LLM)
        # Slower, remote, but only for "safe" code
        if not _run_dual_llm_verification(ctx):
            return _create_error_response(ctx), None

        # 4. Final Human-in-the-Loop Validation
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
    """Checks Security Policy Engine and PQC Identity availability."""
    from llm_cli.security.audit import log_audit
    from llm_cli.security.identity import IdentityManager

    has_pqc = False
    try:
        IdentityManager._ensure_keys()
        has_pqc = True
    except Exception:
        # Handle missing PQC identity based on security level
        security_level = config_manager.get("security", "security_level") or "high"

        if security_level == "high":
            err = (
                f"Security Violation: Tool '{ctx.name}' blocked.\n"
                "[bold yellow]Reason:[/bold yellow] PQC Secure Identity "
                "(Identity Proof) is missing.\n"
                "[bold cyan]Solution:[/bold cyan] Run "
                "[bold]llm-cli-security keygen[/bold] to generate your keys, "
                "or set security_level = 'standard' in config.toml."
            )
            report_error(err)
            ctx.error_message = "Secure identity missing. Setup required."
            log_audit(
                ctx.name,
                ctx.args,
                None,
                error=ctx.error_message,
                context={
                    "model": ctx.session.client.model,
                    "event_type": "security_violation",
                },
            )
            return False
        else:
            from llm_cli.ui import report_warning

            report_warning(
                "Secure Identity (PQC) missing. Proceeding in Standard mode."
            )

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
        log_audit(
            ctx.name,
            ctx.args,
            None,
            error=ctx.error_message,
            context={
                "model": ctx.session.client.model,
                "event_type": "security_violation",
            },
        )
        return False
    return True


def _run_dual_llm_verification(ctx: ToolExecutionContext) -> bool:
    """Verifies intent using a second LLM if required by CASS."""
    from llm_cli.security.audit import log_audit

    if not ctx.security_requirements.get("require_dual_llm_verification"):
        return True

    user_prompt = ctx.session.client.get_last_user_prompt()
    if not user_prompt:
        return True

    from llm_cli.security.dual_llm_verifier import verify_tool_call

    prompt_msg = f"[bold cyan]Dual LLM verifying intent for '{ctx.name}'...[/bold cyan]"
    console.print(prompt_msg)

    # Include the last tool result to help the verifier understand why this tool
    # is being called (e.g., to fix an error found in the previous step).
    last_tool_result = ctx.session.client.get_last_tool_result()

    is_safe, reason = verify_tool_call(
        user_prompt, ctx.name, ctx.args, last_tool_result=last_tool_result
    )
    if not is_safe:
        # Distinguish between "verification infrastructure unavailable" (soft failure)
        # and "intent check actively rejected the call" (hard security block).
        #
        # Soft-failure reasons returned by verify_tool_call when the secondary LLM
        # cannot be reached or is not configured:
        #   - "Verification process failed: ..."  (network / API error)
        #   - "API key missing"                   (provider has no key set)
        #   - "Provider not found"                (unknown provider alias)
        #   - "Initialization error: ..."         (client construction failed)
        _SOFT_FAIL_PREFIXES = (
            "Verification process failed",
            "API key missing",
            "Provider not found",
            "Initialization error",
            # Low-confidence verdicts (confidence < threshold) are annotated by
            # verify_tool_call() with this prefix and routed to human review
            # rather than being treated as a hard security block.
            "[LOW_CONFIDENCE:",
        )
        is_soft_failure = any(reason.startswith(p) for p in _SOFT_FAIL_PREFIXES)

        # In case of low confidence or transient errors, we offer manual approval.
        # Hard security blocks (reason NOT starting with soft fail prefixes)
        # will stay as a hard error.
        if is_soft_failure:
            from llm_cli.ui import report_warning

            report_warning(
                f"Dual LLM Verification unavailable or low-confidence: {reason}\n"
                "Falling back to manual approval."
            )

            # Fallback to human: Let the main approval logic handle it
            ctx.security_warnings.append(
                (
                    "Intent Analysis Warning",
                    f"Dual LLM intent verification uncertain or unavailable: {reason}",
                )
            )
            return True
        else:
            # This is now reached if dual_llm_verifier returns False with a
            # non-soft-fail reason (actual intent violation).
            report_error(
                f"[bold red]Security Block (Dual LLM):[/bold red] "
                f"Intent verification failed.\n"
                f"[bold yellow]Reason:[/bold yellow] {reason}"
            )
            ctx.error_message = (
                f"Security Policy Violation (Dual LLM Violation): "
                f"Intent verification rejected this action. Reason: {reason}"
            )
            log_audit(
                ctx.name,
                ctx.args,
                None,
                error=ctx.error_message,
                context={
                    "model": ctx.session.client.model,
                    "event_type": "security_violation",
                },
            )
            return False
    else:
        report_success(f"Dual LLM Verified: {reason or 'Matched user intent'}")
        return True


def _run_code_safety_check(ctx: ToolExecutionContext) -> bool:
    from llm_cli.security.audit import log_audit

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

    is_safe, violations, warnings = analyze_python_safety(code)
    if not is_safe:
        # 1. Critical Violations: Strict block, no bypass.
        if violations:
            violation_str = "\n".join(f"• {v}" for v in violations)
            print_block(
                f"[bold red][bold yellow]WARNING[/bold yellow]  "
                f"Security Violation:[/bold red]\n{violation_str}",
                title="Static Analysis Critical Block",
                style="red",
            )
            ctx.error_message = (
                "Critical security violation in code. Execution blocked."
            )
            log_audit(
                ctx.name,
                ctx.args,
                None,
                error=ctx.error_message,
                context={
                    "model": ctx.session.client.model,
                    "event_type": "static_analysis_violation",
                    "violations": violations,
                },
            )
            return False

        # 2. Warnings: Potential risk detected, proceed to human approval with warning.
        if warnings:
            warning_str = "\n".join(f"• {w}" for w in warnings)
            ctx.security_warnings.append(
                (
                    "Static Analysis Warning",
                    f"Static analysis detected potential risks:\n{warning_str}",
                )
            )
            # Log it for monitoring, but don't block yet (let user decide)
            log_audit(
                ctx.name,
                ctx.args,
                None,
                error="Security Warning (User Reviewed)",
                context={
                    "model": ctx.session.client.model,
                    "event_type": "static_analysis_warning",
                    "warnings": warnings,
                },
            )
            return True

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
    """
    Handles user approval based on the tool's risk level and security policy.
    Dual LLM warnings or high-risk tools always require manual approval.
    """
    # 1. Resolve Auto-Approval Policy
    # Policy order: none (strictest) < low < medium
    auto_approval_policy = (
        config_manager.get("security", "auto_approval_level") or "none"
    ).lower()

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
            return True

    # 3. Manual Approval Flow
    display_tool_request(ctx)
    if any(k in ctx.name for k in ("write_file", "create_or_overwrite_file")):
        preview_diff(ctx.args)
    elif "edit_file" in ctx.name:
        preview_edit_diff(ctx.args)
    elif "execute_python" in ctx.name:
        preview_python_code(ctx.args)

    if ctx.security_warnings:
        for title, warning in ctx.security_warnings:
            print_block(
                warning,
                title=title,
                style="red",
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
                data_payload
                if isinstance(data_payload, DataSource)
                else DataSource(**data_payload)
            )

        # 2. Bi-directional Verification: Ensure the result is signed.
        # Remote tools (MCP) are signed by the server. Local tools are signed here
        # to satisfy the verification requirement in 'high' security mode.
        is_already_signed = False
        if isinstance(result, dict) and "pqc_signature" in result:
            is_already_signed = True
        elif isinstance(result, str) and result.strip().startswith("{"):
            try:
                import json

                parsed = json.loads(result)
                if isinstance(parsed, dict) and "pqc_signature" in parsed:
                    is_already_signed = True
            except (json.JSONDecodeError, TypeError):
                pass

        if not is_already_signed:
            # Only sign if it's not already an error message
            res_str = str(result)
            if not (
                res_str.startswith("Error:") or "[bold red]DENIED[/bold red]" in res_str
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
        escape(res_str),
        title="[bold green][bold green]OK[/bold green] Tool Output[/bold green]",
        style="green",
    )
    return True


def _truncate_output(res_str: str) -> str:
    from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES

    original_len = len(res_str)
    original_lines = res_str.splitlines()
    original_lines_count = len(original_lines)

    if original_lines_count > MAX_OUTPUT_LINES or original_len > MAX_OUTPUT_CHARS:
        # Perform truncation
        truncated_lines = original_lines[:MAX_OUTPUT_LINES]
        res_str = "\n".join(truncated_lines)[:MAX_OUTPUT_CHARS]

        # Count lines and chars *before* appending the footer to avoid reporting
        # a truncated partial line as a full line, and to keep the char count
        # consistent with what was actually shown.
        shown_lines_count = len(truncated_lines)
        shown_chars = len(res_str)
        res_str += (
            f"\n\n... (Output truncated. Shown {shown_lines_count} of "
            f"{original_lines_count} lines, {shown_chars} of {original_len} chars.)"
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
    result_data: Any, risk_level: Any, server_id: str | None = None, _depth: int = 0
) -> Any:
    """
    Verifies the PQC signature and extracts the result content.
    Supports recursive unwrapping for multi-layered signatures with depth limit.
    """
    import base64
    import json

    _MAX_VERIFY_DEPTH = 3  # Prevent DoS via deeply nested signatures

    if _depth >= _MAX_VERIFY_DEPTH:
        logger.warning(
            f"PQC signature unwrap depth exceeded limit ({_MAX_VERIFY_DEPTH})."
        )
        return result_data

    from llm_cli.security.identity import IdentityManager
    from llm_cli.security.pqc import PQCProvider

    # 1. Handle stringified JSON (common in MCP transport)
    if isinstance(result_data, str) and result_data.strip().startswith("{"):
        try:
            parsed = json.loads(result_data)
            if isinstance(parsed, dict) and "pqc_signature" in parsed:
                result_data = parsed
        except (json.JSONDecodeError, TypeError):
            # Fallback for Python-style string representation (single quotes)
            try:
                import ast

                parsed = ast.literal_eval(result_data)
                if isinstance(parsed, dict) and "pqc_signature" in parsed:
                    result_data = parsed
            except (ValueError, SyntaxError):
                pass

    # 2. Check if this is a signed dictionary
    if not (isinstance(result_data, dict) and "pqc_signature" in result_data):
        # Base case: No more signatures to strip.
        # But for 'high' security, we expect success results to be signed.
        if isinstance(result_data, str) and (
            "Error:" in result_data or "[bold red]DENIED[/bold red]" in result_data
        ):
            return result_data
        return result_data

    # 3. Perform Verification
    sig_b64 = result_data.get("pqc_signature", "")
    v_id = result_data.get("verification_id", "unknown")
    variant = result_data.get("algorithm", "ML-DSA-65")
    content = result_data.get("result", result_data.get("response", result_data))

    # We need a string representation for PQC verification
    content_str = str(content)

    try:
        target_entity = server_id or IdentityManager.get_local_identity()
        pqc_pub = IdentityManager._get_trusted_pqc_public_key(target_entity, variant)

        if not pqc_pub:
            raise ValueError(f"No trusted PQC key found for '{target_entity}'.")

        sig = base64.urlsafe_b64decode(str(sig_b64) + "==")
        if PQCProvider.verify(
            f"{v_id}:{content_str}".encode(), sig, pqc_pub, variant=variant
        ):
            report_success(f"PQC Verified ({variant}) (ID: {v_id})")
            # --- RECURSION with depth tracking ---
            return _verify_pqc_signature(
                content, risk_level, server_id=server_id, _depth=_depth + 1
            )
        else:
            raise ValueError(f"PQC Signature Verification Failed (ID: {v_id})")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        logger.warning(f"Signature verification error: {e}")
        return content
