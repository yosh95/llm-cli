# llm_cli/clients/tool_executor_security.py

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from llm_cli.clients.config import config_manager
from llm_cli.clients.tool_executor_types import ToolExecutionContext
from llm_cli.security.static_analyzer import analyze_python_safety
from llm_cli.ui import (
    console,
    print_panel,
    report_error,
    report_success,
)

logger = logging.getLogger(__name__)


def run_security_checks(ctx: ToolExecutionContext) -> bool:
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

            report_warning("Secure Identity (PQC) missing. Proceeding in Standard mode.")

    from llm_cli.security.policy import EvaluationContext, policy_engine

    user_prompt = ctx.session.client.get_last_user_prompt() or "No user prompt found"
    eval_ctx: EvaluationContext = {
        "user_id": str(config_manager.get("security", "default_user_id") or "current_user"),
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


# Global executor for security verification tasks
_verification_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="security_verify")


def start_dual_llm_verification(ctx: ToolExecutionContext) -> None:
    """
    Starts intent verification using a second LLM in a background thread.
    The result is stored in ctx.verification_task (a Future).
    """
    if not ctx.security_requirements.get("require_dual_llm_verification"):
        return

    user_prompt = ctx.session.client.get_last_user_prompt()
    if not user_prompt:
        return

    from llm_cli.security.dual_llm_verifier import verify_tool_call

    # Define the worker function that will run in a thread
    def _verify() -> tuple[bool, str]:
        last_tool_result = ctx.session.client.get_last_tool_result()
        return verify_tool_call(user_prompt, ctx.name, ctx.args, last_tool_result=last_tool_result)

    if logger.isEnabledFor(logging.DEBUG):
        prompt_msg = (
            f"[bold cyan]Dual LLM verifying intent for '{ctx.name}' (background)...[/bold cyan]"
        )
        console.print(prompt_msg)

    # Launch the verification in the background
    ctx.verification_task = _verification_executor.submit(_verify)


def finish_dual_llm_verification(ctx: ToolExecutionContext) -> bool:
    """
    Waits for the background Dual LLM verification task and processes the result.
    If no task was started, returns True.
    """
    from llm_cli.security.audit import log_audit

    if ctx.verification_task is None:
        return True

    task: Future = ctx.verification_task
    try:
        # Wait for the result. In 'standard' or 'low' auto-approval modes,
        # this will likely be finished already by the time user hits 'y'.
        is_safe, reason = task.result(timeout=30)  # 30s safeguard
    except Exception as e:
        logger.error(f"[ERROR] Dual LLM Verification task failed: {e}")
        # Fallback to human in case of task execution errors
        from llm_cli.ui import report_warning

        report_warning(f"Dual LLM Verification failed during execution: {e}")
        ctx.security_warnings.append(
            ("Verification Error", f"The background verification task encountered an error: {e}")
        )
        return True

    if not is_safe:
        # Distinguish between "verification infrastructure unavailable" (soft failure)
        # and "intent check actively rejected the call" (hard security block).
        _SOFT_FAIL_PREFIXES = (
            "Verification process failed",
            "API key missing",
            "Provider not found",
            "Initialization error",
            "[LOW_CONFIDENCE:",
        )
        is_soft_failure = any(reason.startswith(p) for p in _SOFT_FAIL_PREFIXES)

        # In case of low confidence or transient errors, we offer manual approval.
        if is_soft_failure:
            from llm_cli.ui import report_warning

            report_warning(
                f"Dual LLM Verification uncertain or unavailable: {reason}\n"
                "Review the intent carefully before proceeding."
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
        # Always report success to the console so the user knows the background
        # check passed.
        report_success(f"Dual LLM Intent Verified: {reason or 'OK'}")
        return True


def run_dual_llm_verification(ctx: ToolExecutionContext) -> bool:
    """
    Synchronous wrapper for Dual LLM verification.
    Used for tests or synchronous callers.
    """
    start_dual_llm_verification(ctx)
    return finish_dual_llm_verification(ctx)


def run_code_safety_check(ctx: ToolExecutionContext) -> bool:
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
            print_panel(
                f"[bold red][bold yellow]WARNING[/bold yellow]  "
                f"Security Violation:[/bold red]\n{violation_str}",
                title="Static Analysis Critical Block",
                border_style="red",
            )
            ctx.error_message = "Critical security violation in code. Execution blocked."
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


def verify_pqc_signature(
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
        logger.warning(f"PQC signature unwrap depth exceeded limit ({_MAX_VERIFY_DEPTH}).")
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
        if PQCProvider.verify(f"{v_id}:{content_str}".encode(), sig, pqc_pub, variant=variant):
            if logger.isEnabledFor(logging.DEBUG):
                report_success(f"PQC Verified ({variant}) (ID: {v_id})")
            # --- RECURSION with depth tracking ---
            return verify_pqc_signature(content, risk_level, server_id=server_id, _depth=_depth + 1)
        else:
            raise ValueError(f"PQC Signature Verification Failed (ID: {v_id})")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        logger.warning(f"Signature verification error: {e}")
        return content
