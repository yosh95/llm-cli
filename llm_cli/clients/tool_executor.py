# llm_cli/clients/tool_executor.py

import difflib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from rich.syntax import Syntax

from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Role
from llm_cli.modules.tool_registry import registry

if TYPE_CHECKING:
    from llm_cli.clients.session import ChatSession


def execute_tool_call(
    session: "ChatSession", part: ContentPart, duration: float | None = None
) -> tuple[ContentPart, DataSource | None] | None:
    from llm_cli.clients.base import console

    client = session.client
    call = part.function_call
    if not call:
        return None

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
    context = {
        "user_id": get_setting("default_user_id", "security") or "current_user",
        "roles": get_setting("default_roles", "security") or ["admin"],
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

    is_write = (
        name == "write_file"
        or name == "create_or_overwrite_file"
        or name.endswith("__write_file")
        or name.endswith("__create_or_overwrite_file")
    )
    is_edit = name == "edit_file" or name.endswith("__edit_file")
    is_exec = (
        name == "execute_command"
        or name == "execute_shell_command"
        or name.endswith("__execute_command")
        or name.endswith("__execute_shell_command")
    )

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
            preview_command(session, args)

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
            result_data = tool_entry["func"](__audit_model__=client.model, **args)
        else:
            with console.status(
                f"[bold yellow]🏃 Executing {name}...[/bold yellow]",
                spinner="dots",
            ):
                result_data = tool_entry["func"](__audit_model__=client.model, **args)

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


def preview_command(session: "ChatSession", args: dict[str, Any]) -> None:
    try:
        command = args.get("command", "")
        if not command:
            return

        syn = Syntax(command, "bash", theme="monokai", word_wrap=True)
        session._print_block(
            syn,
            title="[bold]Execute Command[/bold]",
            style="magenta",
        )
    except Exception:
        pass
