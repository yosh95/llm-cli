# llm_cli/ui.py

from typing import Any

from rich.console import Console
from rich.rule import Rule

console = Console()


def print_block(
    renderable: Any, title: str | None = None, style: str | None = None
) -> None:
    """Print content with background color and optional rules."""
    if title:
        console.print(Rule(title=title, style=style or "white"))

    console.print(renderable)

    if title:
        console.print(Rule(style=style or "white"))


def report_error(message: str) -> None:
    console.print(f"[bold red]Error: {message}[/bold red]")


def report_warning(message: str) -> None:
    console.print(f"[bold yellow]Warning: {message}[/bold yellow]")


def report_success(message: str) -> None:
    console.print(f"[bold green]SUCCESS: {message}[/bold green]")
