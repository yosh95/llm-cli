# llm_cli/clients/tool_executor_ui.py

import difflib
import re
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from llm_cli.ui import console, print_block

# ---------------------------------------------------------------------------
# Risk-level visual vocabulary
# ---------------------------------------------------------------------------
# Each entry defines everything needed to render a consistent risk badge:
#   icon    – single emoji shown in the panel title and approval prompt
#   label   – short ALL-CAPS text (e.g. "HIGH RISK") shown in the badge
#   color   – Rich color name used for the panel border and label text
#   prompt  – the exact string shown as the human-approval prompt
# ---------------------------------------------------------------------------
_RISK_STYLE: dict[str, dict[str, str]] = {
    "high": {
        "icon": "[bold red]![/bold red]",
        "label": "HIGH RISK",
        "color": "bold red",
        "border": "red",
        "prompt": "HIGH RISK operation – Allow execution? (y/N or feedback): ",
    },
    "medium": {
        "icon": "[bold yellow]![/bold yellow]",
        "label": "MEDIUM RISK",
        "color": "bold yellow",
        "border": "yellow",
        "prompt": "Allow execution? (y/N or feedback): ",
    },
    "low": {
        "icon": "[bold green]•[/bold green]",
        "label": "LOW RISK",
        "color": "bold green",
        "border": "green",
        "prompt": "Allow execution? (y/N or feedback): ",
    },
}


def display_reasoning(ctx: Any) -> None:
    """Displays the agent's reasoning if available."""
    explanation = (
        ctx.args.get("explanation") or ctx.args.get("thought") or ctx.args.get("reasoning")
    )
    if explanation:
        display_name = ctx.session.client.get_display_name()
        dur = f" ({ctx.duration:.1f}s)" if ctx.duration else ""
        print_block(
            explanation,
            title=f"[bold cyan]{display_name} (Reasoning){dur}[/bold cyan]",
            style="cyan",
        )


def get_approval_prompt(ctx: Any) -> str:
    """Returns the risk-appropriate approval prompt string for a tool context."""
    risk_key = ctx.risk_level.value.lower() if hasattr(ctx, "risk_level") else "medium"
    style = _RISK_STYLE.get(risk_key, _RISK_STYLE["medium"])
    return style["prompt"]


def display_tool_request(ctx: Any, auto_approved: bool = False) -> None:
    """Displays a risk-aware panel showing the tool being called and its arguments."""
    # Resolve risk style (fall back to medium if ctx lacks risk_level)
    risk_key = ctx.risk_level.value.lower() if hasattr(ctx, "risk_level") else "medium"
    style = _RISK_STYLE.get(risk_key, _RISK_STYLE["medium"])

    icon = style["icon"]
    label = style["label"]
    color = style["color"]
    border = style["border"]

    # ── Build argument summary ──────────────────────────────────────────────
    arg_parts = []
    for k, v in ctx.args.items():
        if k in ("explanation", "thought", "reasoning"):
            continue
        val_str = repr(v)

        # We allow paths, directories and URLs to be longer, as they are
        # crucial for security review. Other arguments (like 'content')
        # can be truncated to keep the UI clean.
        limit = 250 if k in ("path", "directory", "url") else 50
        if len(val_str) > limit:
            val_str = val_str[:limit] + "..."
        arg_parts.append(f"  {k} = {val_str}")

    args_block = "\n".join(arg_parts) if arg_parts else "  (no arguments)"

    # ── Compose panel body ──────────────────────────────────────────────────
    # Line 1: risk badge + tool name
    # Line 2+: indented argument list
    body = Text()
    body.append(Text.from_markup(f"{icon} {label} ", style=color))
    body.append("  ")
    body.append(ctx.name, style="bold cyan")
    body.append("\n")
    body.append(args_block, style="white")

    panel_title = Text()
    if auto_approved:
        panel_title.append(Text.from_markup("AGENT REQUEST (AUTO-APPROVED)", style="bold green"))
    else:
        panel_title.append(Text.from_markup("AGENT REQUEST", style="bold yellow"))

    console.print(
        Panel(
            body,
            title=panel_title,
            border_style=border,
            padding=(0, 1),
        )
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
