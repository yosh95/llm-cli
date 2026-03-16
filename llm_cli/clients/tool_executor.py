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
    from llm_cli.clients.base import console

    client = session.client
    call = part.function_call
    if not call:
        return None

    # --- Real-time Anomaly Detection (Mamba Sentinel) ---
    score, status = session.sentinel.get_sentinel_status()
    is_anomaly = status != "green"
    sentinel_mode = session.sentinel.sentinel.mode

    if is_anomaly:
        if sentinel_mode == "detect" or sentinel_mode != "collect":
            from rich.panel import Panel
            from rich.text import Text

            color = "red" if status == "red" else "yellow"
            title = (
                "🚨 [bold]Sentinel: Intent Deviation Detected[/bold]"
                if status == "red"
                else "⚠️ [bold]Sentinel: Unusual Reasoning Pattern[/bold]"
            )
            sentinel_msg = Text()
            sentinel_msg.append(
                "The Mamba Sentinel has detected a potential deviation in the "
                "model's reasoning process.\n",
                style="bold",
            )
            sentinel_msg.append(
                f"Anomaly Score: {score:.2f} (Status: {status.upper()})\n", style="cyan"
            )

            if status == "red":
                sentinel_msg.append(
                    "\n[CRITICAL] High probability of intent drift or "
                    "safety violation. "
                    "Strict manual review of the proposed action is recommended.",
                    style="bold red",
                )
            else:
                sentinel_msg.append(
                    "\n[WARNING] Moderate deviation detected. "
                    "Please review the request carefully.",
                    style="yellow",
                )

            console.print(Panel(sentinel_msg, title=title, border_style=color))
        else:
            # In collect mode, we just log it silently to avoid interrupting the user
            logger.info(
                f"Sentinel Anomaly detected (score={score:.2f}, status={status}) "
                "but ignored due to 'collect' mode."
            )

    tool_id, name, args = (
        call.get("id", "unknown"),
        call["name"],
        call.get("args", {}),
    )

    # Extract thought_signature if present (required by Gemini API)
    thought_signature = part.thought_signature

    # --- Policy & Security Check Start ---
    from llm_cli.security.policy import policy_engine

    # Resolve user prompt from conversation history for intent analysis
    user_prompt = "No user prompt found"
    for msg in reversed(client.conversation):
        if msg.role == Role.USER:
            # Extract text parts
            texts = [p.text for p in msg.parts if isinstance(p, ContentPart) and p.text]
            # Also handle simple string parts if any (though usually ContentPart)
            texts += [p for p in msg.parts if isinstance(p, str)]
            if texts:
                user_prompt = "\n".join(texts)
                break

    # Evaluate policy (includes Role-Based check and Intent Analysis)
    from llm_cli.security.policy import EvaluationContext

    context: EvaluationContext = {
        "user_id": str(get_setting("default_user_id", "security") or "current_user"),
        "roles": list(get_setting("default_roles", "security") or ["user"]),
        "user_prompt": user_prompt,
    }

    if not policy_engine.evaluate(name, args, context):
        console.print(
            f"[red]Policy Violation: Execution of '{name}' "
            "denied by security policy.[/red]"
        )
        response = ContentPart(
            function_response={
                "id": tool_id,
                "name": name,
                "response": {
                    "result": "Error: Security Policy Violation. Action denied."
                },
            },
            thought_signature=thought_signature,
        )
        return response, None
    # --- Policy & Security Check End ---

    # Extract explanation for visibility.
    explanation = (
        args.get("explanation") or args.get("thought") or args.get("reasoning")
    )
    if explanation:
        display_name = client.get_display_name()
        duration_str = f" ({duration:.1f}s)" if duration is not None else ""
        title = f"[bold cyan]{display_name} (Reasoning){duration_str}[/bold cyan]"
        session._print_block(
            explanation,
            title=title,
            style="cyan",
        )

    tool_entry = registry.tools.get(name, {})
    skip_approval = tool_entry.get("skip_approval", False)

    # --- CASS: Context-Adaptive Security Scaling ---
    from llm_cli.security.cass import CASSOrchestrator, RiskLevel

    cass = CASSOrchestrator()
    requirements = cass.get_security_requirements(name)
    risk_level = cass.evaluate_risk(name)

    # Force approval if Sentinel detects RED status and is in active detect mode.
    # (Real-time Intent Deviation Detection)
    #
    # Design rationale – Human-in-the-Loop (HITL) escalation:
    # Rather than autonomously blocking execution, CASS deliberately escalates to
    # a mandatory human approval dialog when the Mamba Sentinel fires at RED level.
    # This preserves Human-in-the-Loop oversight as required by NIST AI RMF
    # and avoids the UX damage of silent, opaque rejections while still ensuring
    # that every anomalous action receives explicit human confirmation.
    if status == "red" and requirements["mamba_enforcement"] == "strict_block":
        skip_approval = False
        session._print_block(
            "[bold red]CASS Escalation:[/bold red] Mandatory human review required.\n"
            f"Mamba Sentinel anomaly score: {score:.2f} (status: {status.upper()})\n"
            f"Risk profile: {risk_level.value.upper()} – strict enforcement active.",
            style="red",
        )

    # Require PQC signature for High Risk tools (Tier 3 enforcement).
    # High-risk tools (edit_file, create_or_overwrite_file, execute_python) embed
    # a ResponseSigner dict in their return value; tool_executor verifies it below.
    # A warning (not hard block) is issued if the signature is absent so that
    # environments without PQC keys still function while operators are alerted.

    is_write = (
        name == "write_file"
        or name == "create_or_overwrite_file"
        or name.endswith("__write_file")
        or name.endswith("__create_or_overwrite_file")
    )
    is_edit = name == "edit_file" or name.endswith("__edit_file")
    is_exec = name == "execute_python" or name.endswith("__execute_python")

    # --- Static Analysis Check for Python Code ---
    is_safe = True
    issues: list[str] = []
    if is_exec:
        code = args.get("code", "")
        if code:
            is_safe, issues = analyze_python_safety(code)
            if not is_safe:
                issue_str = "\n".join(f"• {i}" for i in issues)
                session._print_block(
                    f"[bold red]⚠️  Security Warning (Static Analysis):[/bold red]\n"
                    f"{issue_str}",
                    title="[bold red]Potential Risk Detected[/bold red]",
                    style="red",
                )
                if get_bool_setting(
                    "static_analysis_is_error", "security", default=True
                ):
                    console.print(
                        "[red]Static analysis failed. Execution blocked.[/red]"
                    )
                    response = ContentPart(
                        function_response={
                            "id": tool_id,
                            "name": name,
                            "response": {
                                "result": (
                                    "Error: Static analysis failed. The "
                                    "following security issues were "
                                    "detected and the execution was "
                                    f"blocked:\n{issue_str}"
                                )
                            },
                        },
                        thought_signature=thought_signature,
                    )
                    return response, None
    # --- End Static Analysis Check ---

    if not skip_approval:
        if is_write or is_edit or is_exec:
            request_content = f"[cyan]{escape(name)}[/cyan]"
        else:
            display_args = {
                k: (v[:200] + "...") if isinstance(v, str) and len(v) > 200 else v
                for k, v in args.items()
                if k not in ("explanation", "thought", "reasoning")
            }
            request_content = (
                f"[cyan]{escape(name)}[/cyan]({escape(str(display_args))})"
            )

        session._print_block(
            request_content,
            title="[bold yellow]🤖 Agent Request[/bold yellow]",
            style="yellow",
        )

        if is_write:
            preview_diff(session, args)
        elif is_edit:
            preview_edit_diff(session, args)
        elif is_exec:
            preview_python_code(session, args)

        user_input = session._get_input(
            "Allow execution? (y/N or feedback): ",
            exit_on_escape=True,
            raise_on_interrupt=True,
        )
        if user_input.lower() not in ("y", "ｙ"):
            feedback = user_input if user_input.lower() not in ("n", "ｎ") else ""
            console.print("[red]Operation denied.[/red]")
            if feedback:
                result_msg = f"Rejected by user. Feedback: {feedback}"
            else:
                result_msg = (
                    "Error: Operation denied. DO NOT retry. Ask for instructions."
                )

            response = ContentPart(
                function_response={
                    "id": tool_id,
                    "name": name,
                    "response": {"result": result_msg},
                },
                thought_signature=thought_signature,
            )
            return response, None

    try:
        if name not in registry.tools:
            raise ValueError(f"Tool '{name}' not found.")

        tool_entry = registry.tools[name]
        is_interactive = tool_entry.get("interactive", False)

        if is_interactive:
            result_data = tool_entry["func"](
                __audit_model__=client.model,
                __audit_sentinel__=session.sentinel,
                __security_requirements__=requirements,
                **args,
            )
        else:
            console.print(f"[bold yellow]🏃 Executing {name}...[/bold yellow]")
            result_data = tool_entry["func"](
                __audit_model__=client.model,
                __audit_sentinel__=session.sentinel,
                __security_requirements__=requirements,
                **args,
            )

        injected_data = (
            result_data.pop("__llm_cli_data__", None)
            if isinstance(result_data, dict)
            else None
        )
        injected = None
        if injected_data:
            if isinstance(injected_data, dict):
                injected = DataSource(
                    content=injected_data["content"],
                    content_type=injected_data.get("content_type", "text/plain"),
                    is_file_or_url=injected_data.get("is_file_or_url", False),
                    metadata=injected_data.get("metadata", {}),
                )
            elif isinstance(injected_data, DataSource):
                injected = injected_data

        # --- Signature Stripping & Verification ---
        is_pqc_present = (
            isinstance(result_data, dict) and "pqc_signature" in result_data
        )

        # CASS Requirement: High Risk tools MUST have PQC signatures
        if risk_level == RiskLevel.HIGH and not is_pqc_present:
            session._print_block(
                "[bold yellow]⚠️ CASS Warning:[/bold yellow] High-risk tool response "
                "missing PQC signature. Verification of integrity is limited.",
                style="yellow",
            )

        if is_pqc_present:
            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import PQCProvider

            sig_b64 = result_data.get("pqc_signature", "")
            v_id = result_data.get("verification_id", "unknown")
            variant = result_data.get("algorithm", "ML-DSA-65")
            # The actual content is usually in "result" or "response"
            content_to_verify = result_data.get("result", result_data.get("response"))
            if content_to_verify is None:
                content_to_verify = str(result_data)
            else:
                content_to_verify = str(content_to_verify)

            try:
                import base64

                pqc_pub = IdentityManager._get_pqc_public_key_content(variant=variant)
                sig = base64.urlsafe_b64decode(str(sig_b64) + "==")
                message = f"{v_id}:{content_to_verify}".encode()

                if PQCProvider.verify(message, sig, pqc_pub, variant=variant):
                    session._print_block(
                        f"[bold green]✓ PQC Verified ({variant})[/bold green] "
                        f"(ID: {v_id})",
                        style="green",
                    )
                else:
                    session._print_block(
                        f"[bold red]❌ PQC Signature Verification Failed[/bold red] "
                        f"(ID: {v_id})",
                        style="red",
                    )
            except Exception as e:
                logger.warning(f"Signature verification error: {e}")

            # Always strip the signature and metadata before passing to LLM
            # regardless of verification success/failure to maintain context efficiency
            # and prevent raw JSON leakage.
            result_data = content_to_verify

        p_str = str(result_data)
        max_len = int(get_setting("max_output_length", "general") or 10000)

        if len(p_str) > max_len:
            original_len = len(p_str)
            p_str = p_str[:max_len] + (
                f"\n\n... (Output truncated by system safety limit. "
                f"Shown {max_len} of {original_len} characters. "
                "Use tool parameters (e.g., start_line, start_offset) "
                "to read the rest.)"
            )
            result_data = p_str

        if is_exec:
            session._print_block(
                escape(p_str),
                title="[bold green]✅ Tool Output[/bold green]",
                style="green",
            )
        else:
            session._print_block(
                escape(p_str),
                title="[bold green]✅ Tool Result[/bold green]",
                style="green",
            )

        response = ContentPart(
            function_response={
                "id": tool_id,
                "name": name,
                "response": {"result": result_data},
            },
            thought_signature=thought_signature,
        )
        return response, injected
    except Exception as e:
        console.print(f"[bold red]Tool execution failed: {e}[/bold red]")
        response = ContentPart(
            function_response={
                "id": tool_id,
                "name": name,
                "response": {"result": f"Error: {e}"},
            },
            thought_signature=thought_signature,
        )
        return response, None


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
