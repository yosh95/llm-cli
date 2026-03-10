# llm_cli/clients/session.py

import datetime
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import termios
except ImportError:
    termios = None  # type: ignore

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.shortcuts import CompleteStyle
from rich.rule import Rule

from llm_cli.clients.base import (
    BaseLlmClient,
    console,
)
from llm_cli.clients.completer import LlmCliCompleter
from llm_cli.clients.exceptions import (
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.security.integrity import ReasoningSentinelManager

kb = KeyBindings()
kb_exit = KeyBindings()

MAX_TURNS = 20


@kb.add("c-delete")
def _(_event: Any) -> None:
    raise KeyboardInterrupt


@kb.add("c-j")
def _(event: Any) -> None:
    event.current_buffer.insert_text("\n")


@kb.add("c-x", "c-e")
def _(event: Any) -> None:
    """
    Open the current buffer in an external editor safely.
    Uses shlex to prevent command injection from EDITOR environment variable.
    """
    buffer = event.current_buffer
    original_text = buffer.text
    editor_raw = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vim"

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(original_text.encode("utf-8"))
        tf_path = Path(tf.name)

    try:
        # Use shlex.split to safely parse the editor command and arguments.
        # This prevents command injection like EDITOR="vim; rm -rf /"
        cmd_args = shlex.split(editor_raw) + [str(tf_path)]

        # Execute without shell=True for security.
        return_code = subprocess.call(cmd_args)

        if return_code == 0:
            with tf_path.open(encoding="utf-8") as f:
                new_text = f.read()
                buffer.text = new_text
            buffer.validate_and_handle()
        else:
            # Editor exited with error/abort status (e.g. :cq in vim)
            buffer.text = original_text
    except Exception as e:
        console.print(f"\n[red]Failed to open editor: {e}[/red]")
        buffer.text = original_text
    finally:
        if tf_path.exists():
            tf_path.unlink()


class ChatSession:
    """Manages the interactive CLI session and the ReAct loop."""

    def __init__(self, client: BaseLlmClient) -> None:
        self.client = client
        # Attach session to client so commands can access it
        self.client._session = self
        self.history_path = client.history_path

        self.prompt_history: Any
        if self.history_path:
            Path(self.history_path).parent.mkdir(parents=True, exist_ok=True)
            self.prompt_history = FileHistory(self.history_path)
        else:
            self.prompt_history = InMemoryHistory()

        self.prompt_session: PromptSession = PromptSession(history=self.prompt_history)
        self.completer = LlmCliCompleter(client)
        self.sentinel = ReasoningSentinelManager()

    def _print_block(
        self, renderable: Any, title: str | None = None, style: str | None = None
    ) -> None:
        """Print content with background color (no border) for easier copying."""
        if title:
            console.print(Rule(title=title, style=style or "white"))

        console.print(renderable)

        if title:
            console.print(Rule(style=style or "white"))

    def run(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        console.print("[dim]Use Ctrl+c or /q to exit, /h for help.[/dim]")
        data = initial_data or []
        prompt_default = ""

        while True:
            try:
                # Suggest checkpoint if conversation is getting long.
                # Use turn count as the metric.
                # We count MODEL messages to include ReAct loop steps.
                model_turns = len(
                    [m for m in self.client.conversation if m.role == Role.MODEL]
                )
                if model_turns >= MAX_TURNS:
                    msg = (
                        f"Context is large "
                        f"({model_turns} turns). "
                        "Summarize and compress? (y/N): "
                    )
                    if self._confirm(msg):
                        self._handle_checkpoint()
                        # If history was cleared, continue to next prompt
                        if len(self.client.conversation) <= 1:
                            continue

                # Clear any pending input to prevent ghost KeyboardInterrupt/EOFError.
                if termios and sys.stdin.isatty():
                    try:
                        termios.tcflush(sys.stdin, termios.TCIFLUSH)
                    except Exception:
                        pass

                # Apply both standard key bindings and exit-on-escape bindings
                combined_kb = merge_key_bindings([kb, kb_exit])
                user_input = self.prompt_session.prompt(
                    "> ",
                    default=prompt_default,
                    completer=self.completer,
                    complete_style=CompleteStyle.READLINE_LIKE,
                    key_bindings=combined_kb,
                    enable_system_prompt=True,
                    enable_open_in_editor=True,
                    enable_suspend=True,
                ).strip()
                prompt_default = ""  # Reset default after use
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue

            try:
                try:
                    if self.client._handle_command(user_input, sources, data):
                        continue
                except CheckpointRequest:
                    self._handle_checkpoint()
                    continue
                except TemplateRequest as e:
                    prompt_default = e.text
                    continue
                except ExitRequest:
                    break

                data.append(DataSource(content=user_input, content_type="text/plain"))
                self.process_and_print(data)
                data = []
            except (KeyboardInterrupt, EOFError):
                console.print(
                    "[yellow]Interrupted. Returning to main prompt...[/yellow]"
                )
                data = []
            except Exception as e:
                console.print(f"[bold red]Error: {e}[/bold red]")
                data = []

    def process_and_print(self, data: list[DataSource]) -> None:
        self._log_chat(data, role="User")

        while True:
            # Prefix for the model response
            display_name = self.client.get_display_name()

            # Use status context for spinner (clears automatically after exit)
            start_time = datetime.datetime.now()
            status_msg = (
                f"[bold cyan]🤔 Thinking ({self.client.model})...[/bold cyan] "
                "[dim](Ctrl+C to interrupt)[/dim]"
            )
            with console.status(status_msg, spinner="dots"):
                res = self.client._send(data)
            duration = (datetime.datetime.now() - start_time).total_seconds()

            # Response is now expected to be a tuple ((text, thought), usage)
            response_tuple, usage = res if res else ((None, None), None)
            response_text, thought_text = response_tuple

            # --- Reasoning Sentinel Integration ---
            score_t = self.sentinel.process_chunk(thought_text) if thought_text else 0.0
            score_r = (
                self.sentinel.process_chunk(response_text) if response_text else 0.0
            )
            # Average score for the turn
            self.last_integrity_score = (
                (score_t + score_r) / 2.0
                if thought_text and response_text
                else (score_t or score_r)
            )

            # Finalize turn for the sentinel
            # (triggers online learning if in collect mode)
            self.sentinel.finalize_session()

            if usage:
                self.client.last_usage = usage

            # Display thought content in a separate panel if available
            if thought_text:
                duration_str = f" ({duration:.1f}s)"
                self._print_block(
                    CustomMarkdown(thought_text),
                    title=f"[bold dim]Thought{duration_str}[/bold dim]",
                    style="dim",
                )

            # Display the response
            if response_text:
                if self.client.stdout:
                    print(response_text)
                else:
                    # Wrap the textual response in a Panel for clarity
                    # if we are in a ReAct loop. Otherwise, use a simple Rule.
                    duration_str = f" ({duration:.1f}s)"
                    title_str = f"[bold cyan]{display_name}{duration_str}[/bold cyan]"
                    if self.client._has_pending_tool_calls():
                        self._print_block(
                            CustomMarkdown(response_text),
                            title=title_str,
                            style="cyan",
                        )
                    else:
                        console.print(Rule(title=title_str, style="cyan"))
                        console.print(CustomMarkdown(response_text))
                        console.print(Rule(style="cyan"))

            if response_text is None and not self.client._has_pending_tool_calls():
                return

            if response_text:
                self._log_chat(response_text, role=self.client.model)

            if not self.client._has_pending_tool_calls():
                break

            # If there are pending tool calls, process them and continue the loop
            last_msg = self.client.conversation[-1]
            tool_results_parts: list[str | ContentPart] = []
            injected_datas = []

            for part in last_msg.parts:
                if isinstance(part, ContentPart) and part.function_call:
                    res_tool = self._execute_tool_call(part, duration=duration)
                    if not res_tool:
                        return
                    tool_result, injected = res_tool
                    # tool_result is expected to be a ContentPart with function_response
                    tool_results_parts.append(tool_result)
                    if injected:
                        injected_datas.append(injected)

            if tool_results_parts:
                self.client.conversation.append(
                    Message(role=Role.TOOL, parts=tool_results_parts)
                )
                if injected_datas:
                    self._log_chat(injected_datas, role="Tool Output")
                # Prepare for the next round of generation
                # The tool results are already appended to the conversation
                # history as Role.TOOL.
                # Passing them as 'data' to _send would cause the client to
                # append them AGAIN as a new User message, creating a
                # duplicate and potentially confusing the LLM
                # (especially Gemini, which enforces strict alternating roles).
                # However, if there is injected data (like file content), we MUST
                # pass it so it gets added as a User message.
                data = injected_datas if injected_datas else []
            else:
                break

    def _handle_checkpoint(self) -> None:
        summarize_prompt = (
            "Summarize the conversation so far, preserving key context, "
            "decisions, code changes, and remaining tasks. "
            "Be comprehensive but concise."
        )

        # Back up the current conversation state including provider-specific data
        original_state = self.client.get_conversation_state()

        # Prepare the summarization prompt as a new DataSource
        prompt_source = DataSource(content=summarize_prompt, content_type="text/plain")

        try:
            status_msg = (
                f"[bold cyan]🤔 Summarizing ({self.client.model})...[/bold cyan] "
                "[dim](Ctrl+C to interrupt)[/dim]"
            )
            with console.status(status_msg, spinner="dots"):
                # Pass the prompt as data so it is correctly processed by all clients
                # (especially Gemini which requires 'input' payload)
                res = self.client._send([prompt_source])

            response_tuple, _ = res if res else ((None, None), None)
            summary = response_tuple[0]

            if not summary:
                console.print("[red]Failed to generate summary.[/red]")
                self.client.set_conversation_state(original_state)
                return

            console.print(
                Rule(
                    title="[bold cyan]Proposed Context Summary[/bold cyan]",
                    style="cyan",
                )
            )
            console.print(CustomMarkdown(summary) if summary else "")
            console.print(Rule(style="cyan"))

            if self._confirm("Clear history and use this summary? (y/N): "):
                self.client.clear_history()
                self.client.conversation = [
                    Message(
                        role=Role.USER,
                        parts=[
                            ContentPart(
                                text=f"SYSTEM: History cleared. "
                                f"Continue from this summary:\n\n{summary}"
                            )
                        ],
                    )
                ]
                console.print("[green]✅ Context refreshed.[/green]")
            else:
                console.print("[yellow]Checkpoint canceled.[/yellow]")
                self.client.set_conversation_state(original_state)
        except (KeyboardInterrupt, EOFError):
            self.client.set_conversation_state(original_state)
            console.print("[yellow]Checkpoint canceled (Interrupted).[/yellow]")
            return
        except Exception as e:
            console.print(f"[bold red]Checkpoint failed: {e}[/bold red]")
            self.client.set_conversation_state(original_state)

    def _log_chat(self, content: Any, role: str) -> None:
        if not self.client.chat_log_path:
            return

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            path = Path(self.client.chat_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            text_content = ""
            if isinstance(content, list):
                # Handle list of DataSource or ContentPart
                parts = []
                for item in content:
                    if isinstance(item, DataSource):
                        parts.append(str(item.content))
                    elif isinstance(item, ContentPart):
                        fc = item.function_call
                        fr = item.function_response
                        desc = item.text or f"[Tool: {fc or fr}]"
                        parts.append(desc)
                    else:
                        parts.append(str(item))
                text_content = "\n".join(parts)
            else:
                text_content = str(content)

            with path.open("a", encoding="utf-8") as f:
                f.write(f"--- {timestamp} [{role}] ---\n{text_content}\n\n")

            self.client._trim_log_file(path, self.client.max_chat_log_lines)
        except Exception as e:
            console.print(f"[dim red]Chat logging failed: {e}[/dim red]")

    def _get_input(
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

            # Use provided kwargs, but set defaults for key_bindings and editor
            # to match the main prompt's behavior.
            current_kb = merge_key_bindings([kb, kb_exit]) if exit_on_escape else kb
            kwargs.setdefault("key_bindings", current_kb)
            kwargs.setdefault("complete_style", CompleteStyle.READLINE_LIKE)
            kwargs.setdefault("enable_open_in_editor", True)
            kwargs.setdefault("enable_system_prompt", True)
            kwargs.setdefault("enable_suspend", True)
            kwargs.pop(
                "history", None
            )  # PromptSession.prompt() does not accept history

            try:
                return str(self.prompt_session.prompt(message, **kwargs)).strip()
            except (KeyboardInterrupt, EOFError):
                if raise_on_interrupt:
                    raise
                # Return empty string to simulate cancellation (e.g. "no")
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

    def _confirm(self, message: str) -> bool:
        return self._get_input(message, exit_on_escape=True).lower() in ("y", "ｙ")

    def _execute_tool_call(
        self, part: ContentPart, duration: float | None = None
    ) -> tuple[ContentPart, DataSource | None] | None:
        from llm_cli.clients.tool_executor import execute_tool_call

        return execute_tool_call(self, part, duration)
