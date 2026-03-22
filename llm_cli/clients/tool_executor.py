# llm_cli/clients/tool_executor.py

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from rich.markup import escape
from rich.syntax import Syntax

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

    def __post_init__(self) -> None:
        call = self.part.function_call
        if call:
            self.tool_id = call.get("id", "unknown")
            self.name = call["name"]
            self.args = call.get("args", {})
            self.thought_signature = self.part.thought_signature

        # Evaluate risk and security requirements once
        from llm_cli.security.cass import cass_orchestrator as cass

        self.risk_level = cass.evaluate_risk(self.name)
        self.security_requirements = cass.get_security_requirements(self.name)


def execute_tool_call(
    session: "AgentContext", part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    """
    Main orchestration for tool execution.
    Refactored from a complex class-based pipeline to a linear, readable flow.
    """
    ctx = ToolExecutionContext(session, part, duration)
    if not part.function_call:
        return None

    try:
        # 1. Security Guardrails (PQC, Policy, ABAC)
        if not _run_security_checks(ctx):
            return _create_error_response(ctx), None

        # 2. Reasoning Display
        _display_reasoning(ctx)

        # 3. Static Analysis (Code Safety)
        if not _run_code_safety_check(ctx):
            return _create_error_response(ctx), None

        # 4. User Approval & Previews
        if not _get_user_approval(ctx):
            return _create_error_response(ctx), None

        # 5. Actual Execution
        if not _execute_function(ctx):
            return _create_error_response(ctx), None

        # 6. Post-Processing (Verification, Truncation, Display)
        if not _post_process_result(ctx):
            return _create_error_response(ctx), None

    except Exception as e:
        logger.exception("Unexpected error during tool execution")
        ctx.error_message = f"Internal Error: {e}"
        return _create_error_response(ctx), None

    # Final success response
    response = ContentPart(
        function_response={
            "id": ctx.tool_id,
            "name": ctx.name,
            "response": {"result": ctx.result_data},
        },
        thought_signature=ctx.thought_signature,
    )
    return response, ctx.injected_data


# --- Pipeline Steps (Flat & Linear) ---


def _run_security_checks(ctx: ToolExecutionContext) -> bool:
    """Checks Security Policy Engine and PQC Identity."""
    # PQC Identity Check: Mandatory for ALL executions.
    from llm_cli.security.identity import IdentityManager

    has_pqc = False
    try:
        IdentityManager._ensure_keys()
        has_pqc = True
    except Exception:
        # All tools now strictly require PQC identity.
        err = (
            f"Security Violation: Tool '{ctx.name}' blocked. "
            f"Secure identity (PQC) missing."
        )
        report_error(err)
        ctx.error_message = err
        return False

    # Policy Engine Check
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
        return False

    return True


def _display_reasoning(ctx: ToolExecutionContext) -> None:
    explanation = (
        ctx.args.get("explanation")
        or ctx.args.get("thought")
        or ctx.args.get("reasoning")
    )
    if explanation:
        display_name = ctx.session.client.get_display_name()
        dur = f" ({ctx.duration:.1f}s)" if ctx.duration else ""
        print_block(
            explanation,
            title=f"[bold cyan]{display_name} (Reasoning){dur}[/bold cyan]",
            style="cyan",
        )


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


def _get_user_approval(ctx: ToolExecutionContext) -> bool:
    tool_entry = registry.tools.get(ctx.name, {})
    skip_approval = tool_entry.get("skip_approval", False)

    if skip_approval:
        return True

    # Show Previews
    _display_tool_request(ctx)
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
        ctx.result_data = result
        return True
    except ConfigurationError as e:
        report_error(str(e))
        ctx.error_message = "Search function unavailable. Check API keys."
        return False
    except Exception as e:
        report_error(f"Tool execution failed: {e}")
        ctx.error_message = str(e)
        return False


def _post_process_result(ctx: ToolExecutionContext) -> bool:
    # Extract injected data
    if isinstance(ctx.result_data, dict) and "__llm_cli_data__" in ctx.result_data:
        data_payload = ctx.result_data.pop("__llm_cli_data__")
        ctx.injected_data = (
            data_payload
            if isinstance(data_payload, DataSource)
            else DataSource(**data_payload)
        )

    # PQC Verification
    try:
        ctx.result_data = _verify_pqc_signature(ctx.result_data, ctx.risk_level)
    except ValueError as e:
        ctx.error_message = str(e)
        return False

    # Truncation & Final Display
    res_str = _truncate_output(str(ctx.result_data))
    ctx.result_data = res_str
    print_block(
        escape(res_str), title="[bold green]✅ Tool Output[/bold green]", style="green"
    )
    return True


# --- Helpers ---


def _display_tool_request(ctx: ToolExecutionContext) -> None:
    # Build concise arguments list, skipping redundant system fields
    arg_parts = []
    for k, v in ctx.args.items():
        if k in ("explanation", "thought", "reasoning"):
            continue

        val_str = repr(v)
        if len(val_str) > 120:
            val_str = val_str[:120] + "..."

        arg_parts.append(f"{k}={val_str}")

    if arg_parts:
        arg_str = ", ".join(arg_parts)
        content = f"[cyan]{escape(ctx.name)}[/cyan]({escape(arg_str)})"
    else:
        content = f"[cyan]{escape(ctx.name)}[/cyan]"

    print_block(
        content, title="[bold yellow]🤖 Agent Request[/bold yellow]", style="yellow"
    )


def _truncate_output(res_str: str) -> str:
    max_len = int(config_manager.get("general", "max_output_length") or 10000)
    max_lines = int(config_manager.get("general", "max_output_lines") or 500)
    lines = res_str.splitlines()
    original_lines, original_chars = len(lines), len(res_str)

    if len(lines) > max_lines or len(res_str) > max_len:
        res_str = "\n".join(lines[:max_lines])[:max_len]
        res_str += (
            f"\n\n... (Output truncated. Shown {len(res_str.splitlines())} "
            f"of {original_lines} lines, {len(res_str)} of {original_chars} chars.)"
        )
    return res_str


def _create_error_response(ctx: ToolExecutionContext) -> ContentPart:
    return ContentPart(
        function_response={
            "id": ctx.tool_id,
            "name": ctx.name,
            "response": {"result": f"Error: {ctx.error_message}"},
        },
        thought_signature=ctx.thought_signature,
    )


def _verify_pqc_signature(result_data: Any, risk_level: Any) -> Any:

    is_signed = isinstance(result_data, dict) and "pqc_signature" in result_data

    if not is_signed:
        # Mandatory Security Policy: ALL tool responses must be signed.
        # This ensures the audit trail is post-quantum verifiable.
        msg = (
            f"Security Violation: Missing PQC signature for tool response "
            f"(Risk: {risk_level.value})."
        )
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
        pqc_pub = IdentityManager._get_pqc_public_key_content(variant=variant)
        sig = base64.urlsafe_b64decode(str(sig_b64) + "==")
        if PQCProvider.verify(
            f"{v_id}:{content}".encode(), sig, pqc_pub, variant=variant
        ):
            report_success(f"PQC Verified ({variant}) (ID: {v_id})")
        else:
            msg = f"PQC Signature Verification Failed (ID: {v_id})"
            report_error(msg)
            raise ValueError(msg)
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        logger.warning(f"Signature verification error: {e}")
    return content


def preview_diff(args: dict[str, Any]) -> None:
    path_str = args.get("path", "")
    new_content = args.get("content", "")
    if not path_str or not new_content:
        return
    path = Path(path_str)
    if path.exists():
        old_content = path.read_text(encoding="utf-8")
        diff = list(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if diff:
            print_block(
                Syntax("".join(diff), "diff", theme="monokai", word_wrap=True),
                title=f"[bold]Diff: {path}[/bold]",
                style="yellow",
            )
    else:
        print_block(
            Syntax(
                new_content,
                Syntax.guess_lexer(str(path), code=new_content),
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            ),
            title=f"[bold green]New File: {path}[/bold green]",
            style="green",
        )


def preview_edit_diff(args: dict[str, Any]) -> None:
    path_str = args.get("path", "")
    search = args.get("search", "")
    replace = args.get("replace", "")
    if not path_str or not search:
        return
    path = Path(path_str)
    if not path.exists():
        return
    old_content = path.read_text(encoding="utf-8")
    new_content = old_content.replace(search, replace)
    diff = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if diff:
        print_block(
            Syntax("".join(diff), "diff", theme="monokai", word_wrap=True),
            title=f"[bold]Edit Diff: {path}[/bold]",
            style="yellow",
        )


def preview_python_code(args: dict[str, Any]) -> None:
    code = args.get("code", "")
    if code:
        print_block(
            Syntax(code, "python", theme="monokai", line_numbers=True, word_wrap=True),
            title="[bold]Python Code Preview[/bold]",
            style="yellow",
        )
