# llm_cli/clients/session.py
from __future__ import annotations

import datetime
import sys
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
from prompt_toolkit.shortcuts import CompleteStyle
from rich.rule import Rule

from llm_cli.clients.completer import LlmCliCompleter
from llm_cli.clients.exceptions import (
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)
from llm_cli.clients.session_helper import handle_checkpoint, log_chat
from llm_cli.clients.session_ui import SessionUI, kb, kb_exit, merge_key_bindings
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.ui import console

MAX_TURNS = 20


class ChatSession:
    """Manages the interactive CLI session and the ReAct loop."""

    def __init__(self, client: BaseLlmClient) -> None:
        self.client = client
        self.client._session = self
        self._setup_from_client()

    def _setup_from_client(self) -> None:
        """Initializes or updates session state based on the current client."""
        self.history_path = self.client.history_path

        self.prompt_history: Any
        if self.history_path:
            Path(self.history_path).parent.mkdir(
                parents=True, exist_ok=True, mode=0o700
            )
            self.prompt_history = FileHistory(self.history_path)
        else:
            self.prompt_history = InMemoryHistory()

        self.prompt_session: PromptSession = PromptSession(history=self.prompt_history)
        self.completer = LlmCliCompleter(self.client)
        self.ui = SessionUI(self.prompt_session, kb, kb_exit)

    def switch_client(self, new_client: BaseLlmClient) -> None:
        """Explicitly switch the active client and sync state."""
        old_client = self.client
        new_client.conversation = old_client.conversation
        new_client.active_tools = old_client.active_tools
        new_client.tools_enabled = old_client.tools_enabled
        new_client.live_debug = old_client.live_debug
        new_client.system_prompt_enabled = old_client.system_prompt_enabled

        self.client = new_client
        self.client._session = self
        self.completer = LlmCliCompleter(self.client)
        self.prompt_session.completer = self.completer

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

            except (KeyboardInterrupt, EOFError):
                break

            try:
                try:
                    if self.client._handle_command(user_input, sources, data):
                        continue
                except CheckpointRequest:
                    handle_checkpoint(self)
                    # handle_checkpoint shows its own rule if confirmed
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

        try:
            from llm_cli.mcp_lib import get_current_trace_id
            from llm_cli.security.merkle_anchor import SessionAnchorManager

            trace_id = get_current_trace_id()
            SessionAnchorManager.create_anchor(trace_id)
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
                handle_checkpoint(self)
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
            self.last_response_signature = signed_res["pqc_signature"]
        except Exception:
            pass

    def _get_input(self, *args: Any, **kwargs: Any) -> str:
        """Proxy to SessionUI.get_input for backward compatibility/protocols."""
        return self.ui.get_input(*args, **kwargs)

    def _run_single_turn(self, data: list[DataSource]) -> tuple[str | None, float]:
        """Execute one LLM round-trip and handle display side-effects."""
        display_name = self.client.get_display_name()

        start_time = datetime.datetime.now()
        thinking_msg = (
            f"[bold cyan]Thinking ({self.client.model})...[/bold cyan] "
            "[dim](Ctrl+C to interrupt)[/dim]"
        )
        console.print(thinking_msg)
        res = self.client._send(data)
        duration = (datetime.datetime.now() - start_time).total_seconds()

        response_tuple, usage = res if res else ((None, None), None)
        response_text, thought_text = response_tuple

        if usage:
            self.client.last_usage = usage

        if thought_text:
            self.ui.print_block(
                CustomMarkdown(thought_text),
                title=f"[bold dim]Thought ({duration:.1f}s)[/bold dim]",
                style="dim",
            )

        if response_text:
            self._sign_response(response_text)
            if self.client.stdout:
                print(response_text)
            else:
                title_str = f"[bold cyan]{display_name} ({duration:.1f}s)[/bold cyan]"
                if self.client._has_pending_tool_calls():
                    self.ui.print_block(
                        CustomMarkdown(response_text), title=title_str, style="cyan"
                    )
                else:
                    console.print(Rule(title=title_str, style="cyan"))
                    console.print(CustomMarkdown(response_text))
                    console.print(Rule(style="cyan"))

            log_chat(self, response_text, role=self.client.model)
        return response_text, duration

    def _process_tool_loop(self, duration: float) -> list[DataSource] | None:
        """Collect and execute all pending tool calls."""
        from llm_cli.clients.tool_executor import execute_tool_call

        if not self.client._has_pending_tool_calls():
            return None

        last_msg = self.client.conversation[-1]
        tool_results_parts: list[str | ContentPart] = []
        injected_datas: list[DataSource] = []

        for part in last_msg.parts:
            if isinstance(part, ContentPart) and part.function_call:
                res_tool = execute_tool_call(self, part, duration=duration)
                if not res_tool:
                    # User cancelled (or aborted) this tool call.
                    # If we already have results from earlier calls in this batch,
                    # stop processing further tools but still commit what we have
                    # so the conversation history stays consistent.
                    break
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
            log_chat(self, injected_datas, role="Tool Output")
        return injected_datas if injected_datas else []

    def process_and_print(self, data: list[DataSource]) -> None:
        """Orchestrate the full ReAct loop for one user turn."""
        log_chat(self, data, role="User")
        while True:
            _, duration = self._run_single_turn(data)
            next_data = self._process_tool_loop(duration)
            if next_data is None:
                break
            data = next_data
