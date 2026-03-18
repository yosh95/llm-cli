# llm_cli/clients/tool_executor.py

import difflib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from rich.syntax import Syntax

from llm_cli.clients.config import get_bool_setting, get_setting
from llm_cli.modules.models import ContentPart, DataSource, Role
from llm_cli.modules.tool_registry import registry
from llm_cli.security.static_analyzer import analyze_python_safety

if TYPE_CHECKING:
    from llm_cli.clients.session import ChatSession

logger = logging.getLogger(__name__)


def execute_tool_call(
    session: "ChatSession", part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    """
    Orchestrates the tool execution lifecycle: security, approval, and verification.
    """
    from llm_cli.clients.base import console

    call = part.function_call
    if not call:
        return None

    tool_id, name, args = call.get("id", "unknown"), call["name"], call.get("args", {})
    thought_signature = part.thought_signature

    # 1. Security Guardrails: Sentinel and Policy Engine
    if not _handle_security_guardrails(session, name, args):
        err_msg = "Security Policy Violation"
        return _create_error_response(tool_id, name, err_msg, thought_signature), None

    # 2. Contextual Display: Reasoning explanation
    _display_tool_reasoning(session, args, duration)

    # 3. Risk Assessment & Static Analysis
    from llm_cli.security.cass import CASSOrchestrator

    cass = CASSOrchestrator()
    requirements = cass.get_security_requirements(name)
    risk_level = cass.evaluate_risk(name)

    if not _handle_static_analysis(session, name, args):
        err_msg = "Static analysis failed"
        return _create_error_response(tool_id, name, err_msg, thought_signature), None

    # 4. Human-in-the-Loop: Approval Flow
    approved, feedback = _handle_user_approval(session, name, args, requirements)
    if not approved:
        res_msg = (
            f"Rejected by user. Feedback: {feedback}"
            if feedback
            else "Error: Operation denied."
        )
        return _create_error_response(tool_id, name, res_msg, thought_signature), None

    # 5. Execution & Post-processing (PQC, Truncation, Injection)
    try:
        return _execute_and_verify(
            session, name, args, tool_id, thought_signature, requirements, risk_level
        )
    except Exception as e:
        console.print(f"[bold red]Tool execution failed: {e}[/bold red]")
        return _create_error_response(tool_id, name, str(e), thought_signature), None


def _handle_security_guardrails(session: "ChatSession", name: str, args: dict) -> bool:
    """Checks Mamba Sentinel anomalies and Security Policy Engine."""
    from llm_cli.clients.base import console

    # --- Sentinel Check ---
    score, status = session.sentinel.get_sentinel_status()
    if status != "green" and session.sentinel.sentinel.mode != "collect":
        from rich.panel import Panel
        from rich.text import Text

        color = "red" if status == "red" else "yellow"
        msg_txt = f"Sentinel: Intent Deviation Detected (Score: {score:.2f})\n"
        msg = Text(msg_txt, style="bold")
        if status == "red":
            msg.append("\nHigh probability of intent drift or safety violation.")
        else:
            msg.append("\nModerate deviation detected.")
        console.print(Panel(msg, title="🚨 Sentinel Alert", border_style=color))

    # --- Policy Engine Check ---
    from llm_cli.security.policy import policy_engine

    user_prompt = "No user prompt found"
    for history_msg in reversed(session.client.conversation):
        if history_msg.role == Role.USER:
            texts = [
                p.text
                for p in history_msg.parts
                if isinstance(p, ContentPart) and p.text
            ]
            texts += [p for p in history_msg.parts if isinstance(p, str)]
            if texts:
                user_prompt = "\n".join(texts)
                break

    from llm_cli.security.policy import EvaluationContext

    context: EvaluationContext = {
        "user_id": str(get_setting("default_user_id", "security") or "current_user"),
        "roles": list(get_setting("default_roles", "security") or ["user"]),
        "user_prompt": user_prompt,
    }
    if not policy_engine.evaluate(name, args, context):
        console.print(f"[red]Policy Violation: Execution of '{name}' denied.[/red]")
        return False
    return True


def _display_tool_reasoning(
    session: "ChatSession", args: dict, duration: float | None
) -> None:
    """Displays the model's explanation for calling the tool."""
    explanation = (
        args.get("explanation") or args.get("thought") or args.get("reasoning")
    )
    if explanation:
        display_name = session.client.get_display_name()
        dur = f" ({duration:.1f}s)" if duration else ""
        title = f"[bold cyan]{display_name} (Reasoning){dur}[/bold cyan]"
        session._print_block(explanation, title=title, style="cyan")


def _handle_static_analysis(session: "ChatSession", name: str, args: dict) -> bool:
    """Performs static analysis on executable code."""
    if not (name == "execute_python" or name.endswith("__execute_python")):
        return True

    code = args.get("code", "")
    if not code:
        return True

    is_safe, issues = analyze_python_safety(code)
    if not is_safe:
        issue_str = "\n".join(f"• {i}" for i in issues)
        msg = f"[bold red]⚠️  Security Warning:[/bold red]\n{issue_str}"
        session._print_block(msg, title="Static Analysis Risk", style="red")
        if get_bool_setting("static_analysis_is_error", "security", default=True):
            from llm_cli.clients.base import console

            console.print("[red]Static analysis failed. Blocked.[/red]")
            return False
    return True


def _handle_user_approval(
    session: "ChatSession", name: str, args: dict, requirements: Any
) -> tuple[bool, str]:
    """Manages the user confirmation dialog and diff previews."""
    from llm_cli.clients.base import console

    tool_entry = registry.tools.get(name, {})
    skip_approval = tool_entry.get("skip_approval", False)

    # CASS Escalation: Force approval on Sentinel RED status
    _, status = session.sentinel.get_sentinel_status()
    if status == "red" and requirements.get("mamba_enforcement") == "strict_block":
        skip_approval = False
        msg = "[bold red]CASS Escalation:[/bold red] Mandatory review required."
        session._print_block(msg, style="red")

    if skip_approval:
        return True, ""

    # Display Request
    is_code_tool = any(k in name for k in ("write_file", "edit_file", "execute_python"))
    if is_code_tool:
        request_content = f"[cyan]{escape(name)}[/cyan]"
    else:
        # Truncate very long arguments for display
        display_args = {}
        for k, v in args.items():
            if k in ("explanation", "thought", "reasoning"):
                continue
            display_args[k] = (
                (v[:200] + "...") if isinstance(v, str) and len(v) > 200 else v
            )
        request_content = f"[cyan]{escape(name)}[/cyan]({escape(str(display_args))})"

    session._print_block(
        request_content,
        title="[bold yellow]🤖 Agent Request[/bold yellow]",
        style="yellow",
    )

    # Show Previews
    if "write_file" in name or "create_or_overwrite_file" in name:
        preview_diff(session, args)
    elif "edit_file" in name:
        preview_edit_diff(session, args)
    elif "execute_python" in name:
        preview_python_code(session, args)

    user_input = session._get_input(
        "Allow execution? (y/N or feedback): ",
        exit_on_escape=True,
        raise_on_interrupt=True,
    )
    if user_input.lower() in ("y", "ｙ"):
        return True, ""

    # Handle Denial
    feedback = user_input if user_input.lower() not in ("n", "ｎ") else ""
    console.print("[red]Operation denied.[/red]")
    return False, feedback


def _execute_and_verify(
    session: "ChatSession",
    name: str,
    args: dict,
    tool_id: str,
    signature: str | None,
    requirements: Any,
    risk_level: Any,
) -> tuple[ContentPart, DataSource | None]:
    """Executes the tool, verifies PQC signatures, and truncates output."""
    from llm_cli.clients.base import console

    tool_entry = registry.tools[name]
    is_interactive = tool_entry.get("interactive", False)

    if not is_interactive:
        console.print(f"[bold yellow]🏃 Executing {name}...[/bold yellow]")

    result_data = tool_entry["func"](
        __audit_model__=session.client.model,
        __audit_sentinel__=session.sentinel,
        __security_requirements__=requirements,
        **args,
    )

    # 1. Extract injected data
    injected = None
    if isinstance(result_data, dict) and "__llm_cli_data__" in result_data:
        data_payload = result_data.pop("__llm_cli_data__")
        if isinstance(data_payload, DataSource):
            injected = data_payload
        else:
            injected = DataSource(**data_payload)

    # 2. PQC Verification
    result_data = _verify_pqc_signature(session, result_data, risk_level)

    # 3. Output Truncation
    p_str = str(result_data)
    max_len = int(get_setting("max_output_length", "general") or 10000)
    if len(p_str) > max_len:
        p_str = (
            p_str[:max_len]
            + f"\n\n... (Output truncated. Shown {max_len} of {len(p_str)} chars.)"
        )
        result_data = p_str

    # 4. Display Output
    session._print_block(
        escape(p_str), title="[bold green]✅ Tool Output[/bold green]", style="green"
    )

    response = ContentPart(
        function_response={
            "id": tool_id,
            "name": name,
            "response": {"result": result_data},
        },
        thought_signature=signature,
    )
    return response, injected


def _verify_pqc_signature(
    session: "ChatSession", result_data: Any, risk_level: Any
) -> Any:
    """Verifies PQC signature if present and strips metadata."""
    from llm_cli.security.cass import RiskLevel

    if not (isinstance(result_data, dict) and "pqc_signature" in result_data):
        if risk_level == RiskLevel.HIGH:
            msg = (
                "[bold yellow]⚠️ CASS Warning:[/bold yellow] "
                "High-risk tool missing PQC signature."
            )
            session._print_block(msg, style="yellow")
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
            msg = f"[bold green]✓ PQC Verified ({variant})[/bold green] (ID: {v_id})"
            session._print_block(msg, style="green")
        else:
            msg = (
                "[bold red]❌ PQC Signature Verification Failed[/bold red] "
                f"(ID: {v_id})"
            )
            session._print_block(msg, style="red")
    except Exception as e:
        logger.warning(f"Signature verification error: {e}")

    return content


def _create_error_response(
    tool_id: str, name: str, message: str, signature: str | None
) -> ContentPart:
    """Creates a standardized error response for the LLM."""
    return ContentPart(
        function_response={
            "id": tool_id,
            "name": name,
            "response": {"result": f"Error: {message}"},
        },
        thought_signature=signature,
    )


def preview_diff(session: "ChatSession", args: dict[str, Any]) -> None:
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
                diff_text = "".join(
                    [line if line.endswith("\n") else line + "\n" for line in diff]
                )
                syn = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
                session._print_block(
                    syn,
                    title=f"[bold]Diff: {path}[/bold]",
                    style="yellow",
                )
        else:
            lexer = Syntax.guess_lexer(str(path), code=new_content)
            syn = Syntax(
                new_content,
                lexer,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
            session._print_block(
                syn,
                title=f"[bold green]New File: {path}[/bold green]",
                style="green",
            )
    except Exception:
        pass


def preview_edit_diff(session: "ChatSession", args: dict[str, Any]) -> None:
    """Generate a unified diff preview for edit_file (search/replace)."""
    try:
        path_str = args.get("path", "")
        search = args.get("search", "")
        replace = args.get("replace", "")
        if not path_str or not search:
            return

        path = Path(path_str)
        title = f"[bold]Edit Diff: {path}[/bold]"

        diff = list(
            difflib.unified_diff(
                search.splitlines(keepends=True),
                replace.splitlines(keepends=True),
                fromfile="before (fragment)",
                tofile="after (fragment)",
            )
        )

        if diff:
            diff_text = "".join(
                [line if line.endswith("\n") else line + "\n" for line in diff]
            )
            syn = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
            session._print_block(
                syn,
                title=title,
                style="yellow",
            )
        else:
            session._print_block(
                "[yellow]No changes detected in search/replace block.[/yellow]",
                title=title,
                style="yellow",
            )
    except Exception:
        pass


def preview_python_code(session: "ChatSession", args: dict[str, Any]) -> None:
    try:
        code = args.get("code", "")
        if not code:
            return

        syn = Syntax(code, "python", theme="monokai", word_wrap=True)
        session._print_block(
            syn,
            title="[bold]Execute Python Script[/bold]",
            style="magenta",
        )
    except Exception:
        pass
