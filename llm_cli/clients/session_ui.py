# llm_cli/clients/session_ui.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.shortcuts import CompleteStyle
from rich.panel import Panel
from rich.text import Text

from llm_cli.ui import console, print_block, report_error

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

try:
    import termios
except ImportError:
    termios = None  # type: ignore

kb = KeyBindings()
kb_exit = KeyBindings()


@kb.add("c-delete")
def _(_event: Any) -> None:
    raise KeyboardInterrupt


@kb.add("c-j")
def _(event: Any) -> None:
    event.current_buffer.insert_text("\n")


@kb.add("c-x", "c-e")
def _(event: Any) -> None:
    """Open the current buffer in an external editor safely."""
    import os
    import shlex
    import subprocess
    import tempfile

    buffer = event.current_buffer
    original_text = buffer.text
    editor_raw = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vim"

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(original_text.encode("utf-8"))
        tf_path = Path(tf.name)

    try:
        cmd_args = shlex.split(editor_raw) + [str(tf_path)]
        return_code = subprocess.call(cmd_args)
        if return_code == 0:
            with tf_path.open(encoding="utf-8") as f:
                new_text = f.read()
                buffer.text = new_text
            buffer.validate_and_handle()
        else:
            buffer.text = original_text
    except Exception as e:
        report_error(f"Failed to open editor: {e}")
        buffer.text = original_text
    finally:
        if tf_path.exists():
            tf_path.unlink()


class SessionUI:
    """Handles UI interactions for a chat session."""

    def __init__(
        self,
        prompt_session: PromptSession,
        kb: KeyBindings,
        kb_exit: KeyBindings,
    ) -> None:
        self.prompt_session = prompt_session
        self.kb = kb
        self.kb_exit = kb_exit

    def print_block(
        self, renderable: Any, title: str | None = None, style: str | None = None
    ) -> None:
        """Print content with background color (no border) for easier copying."""
        print_block(renderable, title, style)

    def print_secret_warning(self, anomalies: list[str]) -> None:
        """Displays a warning when potential reasoning anomalies are detected."""
        unique_anomalies = sorted(set(anomalies))
        msg = (
            "The following sequences were flagged as statistical anomalies in the "
            "model's reasoning process. They may represent unexpected data patterns "
            "or potential sensitive information:\n\n"
        )

        anomaly_markup = "\n".join(
            [f"• [bold yellow]{s}[/bold yellow]" for s in unique_anomalies]
        )

        console.print(
            Panel(
                Text.from_markup(msg + anomaly_markup),
                title="[bold yellow]⚠️  Reasoning Anomaly Detected[/bold yellow]",
                border_style="yellow",
            )
        )

    def confirm_secret_transmission(self, anomalies: list[str]) -> bool:
        """Confirms whether the user wants to send detected anomalies to external AI."""
        unique_anomalies = sorted(set(anomalies))
        msg = (
            "[bold red]CAUTION:[/bold red] The following anomalous sequences were "
            "detected in your message. Sending these to an external AI provider "
            "might deviate from intended usage or compromise data integrity:\n\n"
        )
        anomaly_markup = "\n".join(
            [f"• [bold red]{s}[/bold red]" for s in unique_anomalies]
        )

        console.print(
            Panel(
                Text.from_markup(msg + anomaly_markup),
                title="[bold red]🚨 Reasoning Integrity Guardrail[/bold red]",
                border_style="red",
            )
        )

        confirm = self.get_input(
            "Do you still want to send this message? (y/N): ", exit_on_escape=True
        )
        return confirm.lower() in ("y", "ｙ")

    def confirm(self, message: str, exit_on_escape: bool = False) -> bool:
        """Helper to ask for a y/n confirmation."""
        ans = self.get_input(message, exit_on_escape=exit_on_escape)
        return ans.lower() in ("y", "ｙ")

    def get_input(
        self,
        message: str,
        exit_on_escape: bool = False,
        raise_on_interrupt: bool = False,
        **kwargs: Any,
    ) -> str:
        """Helper for console input, supporting both TTY and prompt_toolkit."""
        if sys.stdin.isatty():
            if termios:
                try:
                    termios.tcflush(sys.stdin, termios.TCIFLUSH)
                except Exception:
                    pass

            current_kb = (
                merge_key_bindings([self.kb, self.kb_exit])
                if exit_on_escape
                else self.kb
            )
            kwargs.setdefault("key_bindings", current_kb)
            kwargs.setdefault("complete_style", CompleteStyle.READLINE_LIKE)
            kwargs.setdefault("enable_open_in_editor", True)
            kwargs.setdefault("enable_system_prompt", True)
            kwargs.setdefault("enable_suspend", True)
            kwargs.pop("history", None)

            try:
                return str(self.prompt_session.prompt(message, **kwargs)).strip()
            except (KeyboardInterrupt, EOFError):
                if raise_on_interrupt:
                    raise
                return ""

        try:
            tty_path = Path("/dev/tty") if sys.platform != "win32" else Path("CON")
            with tty_path.open() as tty:
                sys.stderr.write(message)
                sys.stderr.flush()
                line = tty.readline()
                if not line:
                    raise EOFError
                return line.strip()
        except Exception as e:
            if isinstance(e, EOFError):
                raise e
            console.print(
                f"[yellow]Warning: Could not access TTY for input ({e}). "
                "Returning empty.[/yellow]"
            )
            return ""
