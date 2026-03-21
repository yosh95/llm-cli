# llm_cli/clients/session.py
from __future__ import annotations

import datetime
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient

try:
    import termios
except ImportError:
    termios = None  # type: ignore

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.shortcuts import CompleteStyle
from rich.rule import Rule

from llm_cli.clients.completer import LlmCliCompleter
from llm_cli.clients.exceptions import (
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)
from llm_cli.clients.session_ui import SessionUI
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.security.integrity import ReasoningSentinelManager
from llm_cli.ui import (
    console,
    report_error,
)

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
        report_error(f"Failed to open editor: {e}")
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
        self.ui = SessionUI(self.prompt_session, kb, kb_exit)

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
                if self._should_checkpoint():
                    continue

                user_input = self._get_user_input(prompt_default)
                prompt_default = ""

                if not user_input:
                    continue

                if self._check_secrets_before_send(user_input):
                    # Potential secret detected and user cancelled.
                    # Keep the input for editing.
                    prompt_default = user_input
                    continue

            except (KeyboardInterrupt, EOFError):
                break

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

        # At the end of the session, perform External Anchoring of the Audit Chain
        try:
            from llm_cli.security.pqc import AuditAnchoring

            AuditAnchoring.create_external_anchor()
        except Exception:
            pass

    def _should_checkpoint(self) -> bool:
        """Suggest checkpoint if conversation is getting long."""
        model_turns = len([m for m in self.client.conversation if m.role == Role.MODEL])
        if model_turns >= MAX_TURNS:
            msg = (
                f"Context is large ({model_turns} turns). "
                "Summarize and compress? (y/N): "
            )
            if self.ui.confirm(msg):
                self._handle_checkpoint()
                # If history was cleared, caller should continue to next prompt
                if len(self.client.conversation) <= 1:
                    return True
        return False

    def _get_user_input(self, default: str) -> str:
        """Fetch input from user with standard prompt settings."""
        if termios and sys.stdin.isatty():
            try:
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass

        combined_kb = merge_key_bindings([kb, kb_exit])
        return str(
            self.prompt_session.prompt(
                "> ",
                default=default,
                completer=self.completer,
                complete_style=CompleteStyle.READLINE_LIKE,
                key_bindings=combined_kb,
                enable_system_prompt=True,
                enable_open_in_editor=True,
                enable_suspend=True,
            )
        ).strip()

    def _sign_response(self, response_text: str) -> None:
        """Signs the response for bi-directional verification."""
        try:
            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import ResponseSigner

            verification_id = "initial"
            if (
                self.client.conversation
                and self.client.conversation[-1].role == Role.TOOL
            ):
                last_part = self.client.conversation[-1].parts[0]
                if isinstance(last_part, ContentPart):
                    fr = last_part.function_response
                    if isinstance(fr, dict):
                        verification_id = fr.get("id", "root")

            pqc_priv = IdentityManager._get_pqc_private_key_content()
            signed_res = ResponseSigner.sign_response(
                response_text, verification_id, pqc_priv
            )
            # Stored for external audit / "Verified" badge display.
            self.last_response_signature = signed_res["pqc_signature"]
        except Exception:
            # Silent fail for signing errors in CLI
            pass

    def _get_input(self, *args: Any, **kwargs: Any) -> str:
        """Proxy to SessionUI.get_input for backward compatibility/protocols."""
        return self.ui.get_input(*args, **kwargs)

    def _check_secrets_before_send(self, user_input: str) -> bool:
        """Check for secrets and ask for confirmation. Returns True if aborted."""
        if user_input.startswith("/"):
            return False

        # Note: Sentinel context anchoring is performed inside process_chunk()
        # (at response time), not here.  Running a forward pass on the user input
        # before the LLM even responds would waste CPU and mutate SSM state for
        # no detection benefit — secrets can only be detected in the *response*.
        if self.sentinel.suspected_secrets:
            if not self.ui.confirm_secret_transmission(self.sentinel.suspected_secrets):
                self.sentinel.suspected_secrets = []
                return True
            self.sentinel.suspected_secrets = []
        return False

    # ------------------------------------------------------------------
    # Single-responsibility helpers extracted from process_and_print
    # ------------------------------------------------------------------

    def _run_single_turn(self, data: list[DataSource]) -> tuple[str | None, float]:
        """
        Execute one LLM round-trip and handle Sentinel + display side-effects.
        """
        display_name = self.client.get_display_name()

        # Resolve user prompt from conversation history for Prompt Anchoring
        user_prompt = self.client.get_last_user_prompt()

        # If not found in history (e.g., first turn where it's only in 'data'),
        # extract it from the data payload.
        if not user_prompt and data:
            texts = [str(d.content) for d in data if d.content_type == "text/plain"]
            if texts:
                user_prompt = "\n".join(texts)

        # Show a static "thinking" indicator while waiting for the API.
        start_time = datetime.datetime.now()
        console.print(
            f"[bold cyan]🤔 Thinking ({self.client.model})...[/bold cyan] "
            "[dim](Ctrl+C to interrupt)[/dim]"
        )
        res = self.client._send(data)
        duration = (datetime.datetime.now() - start_time).total_seconds()

        # Unpack the (text, thought) / usage envelope.
        response_tuple, usage = res if res else ((None, None), None)
        response_text, thought_text = response_tuple

        # --- Reasoning Sentinel with Prompt Anchoring ---
        score_t = (
            self.sentinel.process_chunk(thought_text, user_prompt=user_prompt)
            if thought_text
            else 0.0
        )
        score_r = (
            self.sentinel.process_chunk(response_text, user_prompt=user_prompt)
            if response_text
            else 0.0
        )
        self.last_integrity_score = (
            (score_t + score_r) / 2.0
            if thought_text and response_text
            else (score_t or score_r)
        )
        # Triggers online learning when the sentinel is in "learn" mode.
        self.sentinel.finalize_session()

        # --- Secret detection warning ---
        if self.sentinel.suspected_secrets:
            self.ui.print_secret_warning(self.sentinel.suspected_secrets)
            self.sentinel.suspected_secrets = []

        if usage:
            self.client.last_usage = usage

        # --- Display thought panel ---
        if thought_text:
            duration_str = f" ({duration:.1f}s)"
            self.ui.print_block(
                CustomMarkdown(thought_text),
                title=f"[bold dim]Thought{duration_str}[/bold dim]",
                style="dim",
            )

        # --- Display response + PQC background signing ---
        if response_text:
            self._sign_response(response_text)

            if self.client.stdout:
                print(response_text)
            else:
                duration_str = f" ({duration:.1f}s)"
                title_str = f"[bold cyan]{display_name}{duration_str}[/bold cyan]"
                if self.client._has_pending_tool_calls():
                    # Inside a ReAct loop: use a titled block so turns are distinct.
                    self.ui.print_block(
                        CustomMarkdown(response_text),
                        title=title_str,
                        style="cyan",
                    )
                else:
                    console.print(Rule(title=title_str, style="cyan"))
                    console.print(CustomMarkdown(response_text))
                    console.print(Rule(style="cyan"))

            self._log_chat(response_text, role=self.client.model)

        return response_text, duration

    def _process_tool_loop(self, duration: float) -> list[DataSource] | None:
        """
        Collect and execute all pending tool calls from the last MODEL message.

        Responsibilities:
        - Iterate over function_call parts in the last conversation message.
        - Delegate each call to _execute_tool_call (which handles approval, policy,
          diff preview, etc.).
        - Append the results as a TOOL message to the conversation history.
        - Return the injected DataSources that must be forwarded as the next USER
          message (or an empty list when there is nothing to inject).

        Returns:
            list[DataSource] — next-turn data (may be empty).
            None             — signals that the loop should be aborted immediately
                               (e.g. a tool call was cancelled by the user).
        """
        if not self.client._has_pending_tool_calls():
            return None

        last_msg = self.client.conversation[-1]
        tool_results_parts: list[str | ContentPart] = []
        injected_datas: list[DataSource] = []

        for part in last_msg.parts:
            if isinstance(part, ContentPart) and part.function_call:
                res_tool = self._execute_tool_call(part, duration=duration)
                if not res_tool:
                    # User denied the tool call — abort the entire loop.
                    return None
                tool_result, injected = res_tool
                tool_results_parts.append(tool_result)
                if injected:
                    injected_datas.append(injected)

        if not tool_results_parts:
            return None

        self.client.conversation.append(
            Message(role=Role.TOOL, parts=tool_results_parts)
        )
        if injected_datas:
            self._log_chat(injected_datas, role="Tool Output")

        # Injected data (e.g. file content returned by a tool) must be forwarded
        # as the next _send payload so it becomes a USER message.  Plain tool
        # results are already in Role.TOOL and must NOT be re-sent.
        return injected_datas if injected_datas else []

    # ------------------------------------------------------------------
    # Public orchestrator
    # ------------------------------------------------------------------

    def process_and_print(self, data: list[DataSource]) -> None:
        """
        Orchestrate the full ReAct loop for one user turn.

        Calls _run_single_turn for each LLM round-trip, then
        _process_tool_loop to execute any requested tools, repeating until
        there are no more pending tool calls or the user aborts.
        """
        self._log_chat(data, role="User")

        while True:
            _, duration = self._run_single_turn(data)

            # Execute pending tool calls and get next-turn data.
            # _process_tool_loop returns:
            # - a list of DataSources (possibly empty) if tools were executed.
            # - None if there are no tools to run or the user cancelled execution.
            next_data = self._process_tool_loop(duration)

            if next_data is None:
                break

            # Continue the ReAct loop with the (possibly empty) injected data.
            data = next_data

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
            console.print(status_msg)
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

            if self.ui.confirm("Clear history and use this summary? (y/N): "):
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

    def _execute_tool_call(
        self, part: ContentPart, duration: float | None = None
    ) -> tuple[ContentPart, DataSource | None] | None:
        from llm_cli.clients.tool_executor import execute_tool_call

        return execute_tool_call(self, part, duration)
