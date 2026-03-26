# llm_cli/clients/session_ui.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.shortcuts import CompleteStyle

from llm_cli.ui import console, print_block

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

    # Validate the editor executable before use.
    # shlex.split() allows $EDITOR to carry extra flags (e.g. "vim -u NONE"),
    # which is legitimate.  What we guard against is a compromised environment
    # where EDITOR contains a path to a non-existent or non-executable binary —
    # fail fast rather than silently invoking an unexpected program.
    try:
        import shutil as _shutil

        editor_parts = shlex.split(editor_raw)
        if not editor_parts:
            raise ValueError("EDITOR is empty after parsing.")

        editor_exe = editor_parts[0]
        resolved_exe = _shutil.which(editor_exe)
        if not resolved_exe:
            raise ValueError(f"Editor executable '{editor_exe}' not found in PATH.")
        # Replace the (possibly relative) executable with its resolved absolute
        # path so that the command cannot be hijacked by a later PATH change.
        editor_parts[0] = resolved_exe
    except Exception as e:
        from llm_cli.ui import report_error

        report_error(f"Invalid EDITOR setting: {e}")
        return

    # Use mkstemp for better control over permissions (0600)

    fd, tf_path_str = tempfile.mkstemp(suffix=".txt")
    tf_path = Path(tf_path_str)
    tf_path.chmod(0o600)

    try:
        with os.fdopen(fd, "wb") as tf:
            tf.write(original_text.encode("utf-8"))

        cmd_args = editor_parts + [str(tf_path)]
        return_code = subprocess.call(cmd_args)
        if return_code == 0:
            buffer.text = tf_path.read_text(encoding="utf-8")
            buffer.validate_and_handle()
        else:
            buffer.text = original_text
    except Exception as e:
        from llm_cli.ui import report_error

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
