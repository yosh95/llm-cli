# llm_cli/clients/tool_executor_ui.py

import difflib
import re
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.syntax import Syntax

from llm_cli.ui import print_block


def display_reasoning(ctx: Any) -> None:
    """Displays the agent's reasoning if available."""
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


def display_tool_request(ctx: Any) -> None:
    """Displays a concise block showing the tool being called and its arguments."""
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


def preview_diff(args: dict[str, Any]) -> None:
    """Shows a unified diff preview for file creation or overwrite."""
    path_str = args.get("path", "")
    new_content = args.get("content", "")
    if not path_str or not new_content:
        return
    path = Path(path_str)
    if path.exists():
        try:
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
        except Exception:
            pass
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
    """Shows a unified diff preview for a file edit operation."""
    path_str = args.get("path", "")
    search = args.get("search", "")
    replace = args.get("replace", "")
    if not path_str or search is None or replace is None:
        return
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8")
        if search in content:
            new_content = content.replace(search, replace, 1)
        else:
            # Fuzzy match matching the logic in edit_file
            stripped_search = search.strip()
            if not stripped_search:
                return

            tokens = re.split(r"(\s+|[^\w])", stripped_search)
            pattern_parts = [re.escape(t) for t in tokens if t and not t.isspace()]
            if not pattern_parts:
                return

            pattern = r"\s*".join(pattern_parts)
            matches = list(re.finditer(pattern, content, re.DOTALL))

            if len(matches) != 1:
                return
            match_start, match_end = matches[0].span()
            new_content = content[:match_start] + replace + content[match_end:]

        diff = "".join(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if diff:
            print_block(
                Syntax(diff, "diff", theme="monokai", word_wrap=True),
                title=f"[bold]Diff: {path}[/bold]",
                style="yellow",
            )
    except Exception:
        pass


def preview_python_code(args: dict[str, Any]) -> None:
    """Shows a syntax-highlighted preview of Python code to be executed."""
    code = args.get("code", "")
    if not code:
        return
    print_block(
        Syntax(code, "python", theme="monokai", line_numbers=True, word_wrap=True),
        title="[bold yellow]Python Code Preview[/bold yellow]",
        style="yellow",
    )
