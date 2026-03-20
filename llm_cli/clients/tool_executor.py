# llm_cli/clients/tool_executor.py

import difflib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from rich.markup import escape
from rich.syntax import Syntax

from llm_cli.clients.config import config_manager
from llm_cli.modules.models import ContentPart, DataSource
from llm_cli.modules.tool_registry import registry
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
    @property
    def sentinel(self) -> Any: ...
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

    def __post_init__(self) -> None:
        call = self.part.function_call
        if call:
            self.tool_id = call.get("id", "unknown")
            self.name = call["name"]
            self.args = call.get("args", {})
            self.thought_signature = self.part.thought_signature


class BaseToolHandler(ABC):
    """Abstract base class for individual stages of tool execution."""

    @abstractmethod
    def process(self, context: ToolExecutionContext) -> None:
        """Process the context at this stage."""
        pass


class SecurityGuardrailHandler(BaseToolHandler):
    """Checks Sentinel anomalies and Security Policy Engine."""

    def process(self, context: ToolExecutionContext) -> None:
        # 1. Sentinel Check
        score, status = context.session.sentinel.get_sentinel_status()
        if status != "green" and context.session.sentinel.sentinel.mode != "learn":
            from rich.panel import Panel
            from rich.text import Text

            color = "red" if status == "red" else "yellow"
            msg = Text(
                f"Sentinel: Intent Deviation Detected (Score: {score:.2f})\n",
                style="bold",
            )
            msg.append(
                "\nHigh probability of intent drift or safety violation."
                if status == "red"
                else "\nModerate deviation detected."
            )
            console.print(Panel(msg, title="🚨 Sentinel Alert", border_style=color))

        # 2. PQC Identity Pre-check for High-Risk Tools
        from llm_cli.security.cass import CASSOrchestrator, RiskLevel
        from llm_cli.security.identity import IdentityManager

        risk_level = CASSOrchestrator().evaluate_risk(context.name)
        enforcement = config_manager.get("security", "pqc_enforcement") or "warn"
        is_strict = enforcement == "strict_block"

        has_pqc = False
        try:
            IdentityManager._ensure_keys()
            has_pqc = True
        except Exception as e:
            if is_strict and risk_level == RiskLevel.HIGH:
                err_msg = (
                    f"High-risk tool '{context.name}' blocked: "
                    "Secure identity (PQC keys) missing or corrupted. "
                    "Please run 'llm-cli --init-config' and ensure environment is safe."
                )
                report_error(err_msg)
                context.error_message = err_msg
                context.aborted = True
                return
            logger.warning(f"PQC Identity check failed: {e}")

        # 3. Policy Engine Check (ABAC)
        from llm_cli.security.policy import EvaluationContext, policy_engine

        user_prompt = self._find_user_prompt(context.session)
        eval_ctx: EvaluationContext = {
            "user_id": str(
                config_manager.get("security", "default_user_id") or "current_user"
            ),
            "user_prompt": user_prompt,
            "has_pqc_proof": has_pqc,
        }
        if not policy_engine.evaluate(context.name, context.args, eval_ctx):
            context.error_message = (
                f"Policy Violation: Execution of '{context.name}' denied."
            )
            context.aborted = True

    def _find_user_prompt(self, session: AgentContext) -> str:
        return session.client.get_last_user_prompt() or "No user prompt found"


class ReasoningDisplayHandler(BaseToolHandler):
    """Displays the model's reasoning before executing the tool."""

    def process(self, context: ToolExecutionContext) -> None:
        explanation = (
            context.args.get("explanation")
            or context.args.get("thought")
            or context.args.get("reasoning")
        )
        if explanation:
            display_name = context.session.client.get_display_name()
            dur = f" ({context.duration:.1f}s)" if context.duration else ""
            title = f"[bold cyan]{display_name} (Reasoning){dur}[/bold cyan]"
            print_block(explanation, title=title, style="cyan")


class CodeSafetyHandler(BaseToolHandler):
    """Performs static analysis on executable code."""

    def process(self, context: ToolExecutionContext) -> None:
        high_risk_tools = set(config_manager.get("security", "high_risk_tools") or [])
        if not (
            context.name in high_risk_tools
            or context.name == "execute_python"
            or context.name.endswith("__execute_python")
        ):
            return

        code = context.args.get("code", "")
        if not code:
            return

        is_safe, issues = analyze_python_safety(code)
        if not is_safe:
            issue_str = "\n".join(f"• {i}" for i in issues)
            print_block(
                f"[bold red]⚠️  Security Warning:[/bold red]\n{issue_str}",
                title="Static Analysis Risk",
                style="red",
            )
            if config_manager.get_bool(
                "security", "static_analysis_is_error", default=True
            ):
                context.error_message = "Static analysis failed. Blocked."
                context.aborted = True


class UserApprovalHandler(BaseToolHandler):
    """Manages user confirmation and diff previews."""

    def process(self, context: ToolExecutionContext) -> None:
        tool_entry = registry.tools.get(context.name, {})
        skip_approval = tool_entry.get("skip_approval", False)

        # CASS Escalation Check
        _, status = context.session.sentinel.get_sentinel_status()
        if (
            status == "red"
            and config_manager.get("security", "mamba_enforcement") == "strict_block"
        ):
            skip_approval = False
            print_block(
                "[bold red]CASS Escalation:[/bold red] Mandatory review required.",
                style="red",
            )

        if skip_approval:
            return

        # Show Previews
        self._display_request(context)
        if any(k in context.name for k in ("write_file", "create_or_overwrite_file")):
            preview_diff(context.args)
        elif "edit_file" in context.name:
            preview_edit_diff(context.args)
        elif "execute_python" in context.name:
            preview_python_code(context.args)

        try:
            user_input = context.session._get_input(
                "Allow execution? (y/N or feedback): ",
                exit_on_escape=True,
                raise_on_interrupt=True,
            )
        except (KeyboardInterrupt, EOFError):
            context.error_message = "Operation cancelled by user."
            context.aborted = True
            return

        if user_input.lower() not in ("y", "ｙ"):
            context.error_message = (
                f"Rejected by user. Feedback: {user_input}"
                if user_input.lower() not in ("n", "ｎ")
                else "Error: Operation denied."
            )
            context.aborted = True

    def _display_request(self, context: ToolExecutionContext) -> None:
        is_code_tool = any(
            k in context.name for k in ("write_file", "edit_file", "execute_python")
        )
        if is_code_tool:
            content = f"[cyan]{escape(context.name)}[/cyan]"
        else:
            display_args = {
                k: (v[:200] + "...") if isinstance(v, str) and len(v) > 200 else v
                for k, v in context.args.items()
                if k not in ("explanation", "thought", "reasoning")
            }
            content = (
                f"[cyan]{escape(context.name)}[/cyan]({escape(str(display_args))})"
            )
        print_block(
            content, title="[bold yellow]🤖 Agent Request[/bold yellow]", style="yellow"
        )


class ExecutionHandler(BaseToolHandler):
    """Actually calls the registered tool function."""

    def process(self, context: ToolExecutionContext) -> None:
        tool_entry = registry.tools[context.name]
        if not tool_entry.get("interactive", False):
            console.print(f"[bold yellow]🏃 Executing {context.name}...[/bold yellow]")

        # Context-aware security requirements from CASS
        from llm_cli.security.cass import CASSOrchestrator

        cass = CASSOrchestrator()
        requirements = cass.get_security_requirements(context.name)

        try:
            result = tool_entry["func"](
                __audit_model__=context.session.client.model,
                __audit_sentinel__=context.session.sentinel,
                __security_requirements__=requirements,
                **context.args,
            )
            context.result_data = result
        except Exception as e:
            report_error(f"Tool execution failed: {e}")
            context.error_message = str(e)
            context.aborted = True


class PostProcessHandler(BaseToolHandler):
    """Handles PQC verification, truncation, and display."""

    def process(self, context: ToolExecutionContext) -> None:
        # Extract injected data
        if (
            isinstance(context.result_data, dict)
            and "__llm_cli_data__" in context.result_data
        ):
            data_payload = context.result_data.pop("__llm_cli_data__")
            context.injected_data = (
                data_payload
                if isinstance(data_payload, DataSource)
                else DataSource(**data_payload)
            )

        # PQC Verification
        from llm_cli.security.cass import CASSOrchestrator

        risk_level = CASSOrchestrator().evaluate_risk(context.name)
        try:
            context.result_data = _verify_pqc_signature(context.result_data, risk_level)
        except ValueError as e:
            # Handle specific security failure messages to return directly to LLM
            context.error_message = str(e)
            context.aborted = True
            return

        # Truncation
        res_str = str(context.result_data)
        max_len = int(config_manager.get("general", "max_output_length") or 10000)
        max_lines = int(config_manager.get("general", "max_output_lines") or 500)

        original_chars = len(res_str)
        lines = res_str.splitlines()
        original_lines = len(lines)

        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            res_str = "\n".join(lines)
            truncated = True

        if len(res_str) > max_len:
            # If still over limit, truncate by characters but try to keep whole lines
            res_str = res_str[:max_len]
            last_newline = res_str.rfind("\n")
            if last_newline != -1:
                res_str = res_str[:last_newline]
            truncated = True

        if truncated:
            current_lines = len(res_str.splitlines())
            res_str += (
                f"\n\n... (Output truncated. Shown {current_lines} of "
                f"{original_lines} lines, {len(res_str)} of {original_chars} chars.)"
            )
            context.result_data = res_str

        # Final Display
        print_block(
            escape(res_str),
            title="[bold green]✅ Tool Output[/bold green]",
            style="green",
        )


def execute_tool_call(
    session: "AgentContext", part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    """Main pipeline orchestration for tool execution."""
    ctx = ToolExecutionContext(session, part, duration)
    if not part.function_call:
        return None

    # Pipeline definition
    pipeline: list[BaseToolHandler] = [
        SecurityGuardrailHandler(),
        ReasoningDisplayHandler(),
        CodeSafetyHandler(),
        UserApprovalHandler(),
        ExecutionHandler(),
        PostProcessHandler(),
    ]

    # Run pipeline
    for handler in pipeline:
        try:
            handler.process(ctx)
            if ctx.aborted:
                return _create_error_response(ctx), None
        except Exception as e:
            logger.exception("Error in pipeline stage %s", handler.__class__.__name__)
            ctx.error_message = f"Internal Error in {handler.__class__.__name__}: {e}"
            return _create_error_response(ctx), None

    response = ContentPart(
        function_response={
            "id": ctx.tool_id,
            "name": ctx.name,
            "response": {"result": ctx.result_data},
        },
        thought_signature=ctx.thought_signature,
    )
    return response, ctx.injected_data


def _create_error_response(ctx: ToolExecutionContext) -> ContentPart:
    return ContentPart(
        function_response={
            "id": ctx.tool_id,
            "name": ctx.name,
            "response": {"result": f"Error: {ctx.error_message}"},
        },
        thought_signature=ctx.thought_signature,
    )


# --- Helper functions (Moved/Maintained for compatibility) ---


def _verify_pqc_signature(result_data: Any, risk_level: Any) -> Any:
    from llm_cli.security.cass import RiskLevel

    is_signed = isinstance(result_data, dict) and "pqc_signature" in result_data
    enforcement = config_manager.get("security", "pqc_enforcement") or "warn"
    is_strict = enforcement == "strict_block"

    if not is_signed:
        if risk_level == RiskLevel.HIGH:
            msg = (
                "High-risk tool missing PQC signature. Please generate keys "
                "using 'llm-cli-security keygen' to enable high-risk operations."
            )
            report_error(f"PQC Enforcement: {msg} Blocked.")
            # Returning a message to the LLM as requested
            llm_msg = (
                "This tool is high-risk and is prohibited in the current environment."
            )
            raise ValueError(llm_msg)
        return result_data

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
            if is_strict and risk_level == RiskLevel.HIGH:
                report_error(f"PQC Enforcement: {msg}")
                raise ValueError(msg)
            report_error(msg)
    except Exception as e:
        if is_strict and risk_level == RiskLevel.HIGH:
            report_error(f"PQC Enforcement: Signature verification error: {e}")
            raise e
        logger.warning(f"Signature verification error: {e}")
    return content


def preview_diff(args: dict[str, Any]) -> None:
    try:
        path, new_content = (Path(args.get("path", "")), args.get("content", ""))
        if not path or not new_content:
            return
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
                syn = Syntax("".join(diff), "diff", theme="monokai", word_wrap=True)
                print_block(syn, title=f"[bold]Diff: {path}[/bold]", style="yellow")
        else:
            lexer = Syntax.guess_lexer(str(path), code=new_content)
            syn = Syntax(
                new_content, lexer, theme="monokai", line_numbers=True, word_wrap=True
            )
            print_block(
                syn, title=f"[bold green]New File: {path}[/bold green]", style="green"
            )
    except Exception:
        pass


def preview_edit_diff(args: dict[str, Any]) -> None:
    try:
        path_str, search, replace = (
            args.get("path", ""),
            args.get("search", ""),
            args.get("replace", ""),
        )
        if not path_str or not search:
            return
        diff = list(
            difflib.unified_diff(
                search.splitlines(keepends=True),
                replace.splitlines(keepends=True),
                fromfile="before (fragment)",
                tofile="after (fragment)",
            )
        )
        if diff:
            syn = Syntax("".join(diff), "diff", theme="monokai", word_wrap=True)
            print_block(
                syn, title=f"[bold]Edit Diff: {path_str}[/bold]", style="yellow"
            )
    except Exception:
        pass


def preview_python_code(args: dict[str, Any]) -> None:
    code = args.get("code", "")
    if code:
        syn = Syntax(code, "python", theme="monokai", word_wrap=True)
        print_block(syn, title="[bold]Execute Python Script[/bold]", style="magenta")
