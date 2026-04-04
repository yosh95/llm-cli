# llm_cli/ui.py

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()


def print_block(renderable: Any, title: str | None = None, style: str | None = None) -> None:
    """Print content with background color and optional rules."""
    if title:
        console.print(Rule(title=title, style=style or "white"))

    console.print(renderable)

    if title:
        console.print(Rule(style=style or "white"))


def print_panel(
    renderable: Any,
    title: str | None = None,
    style: str | None = None,
    border_style: str | None = None,
) -> None:
    """Print content inside a Rich Panel."""
    console.print(
        Panel(
            renderable,
            title=title,
            style=style or "none",
            border_style=border_style or "dim",
            padding=(0, 1),
        )
    )


def report_error(message: str) -> None:
    console.print(f"[bold red][ERROR] {message}[/bold red]")


def report_warning(message: str) -> None:
    console.print(f"[bold yellow][WARNING] {message}[/bold yellow]")


def report_success(message: str) -> None:
    console.print(f"[bold green][SUCCESS] {message}[/bold green]")
