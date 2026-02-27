# llm_cli/clients/session.py

import datetime
import difflib
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    import termios
except ImportError:
    termios = None  # type: ignore

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    PathCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.shortcuts import CompleteStyle
from rich.markup import escape
from rich.rule import Rule
from rich.syntax import Syntax

from llm_cli.clients.base import (
    BaseLlmClient,
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
    console,
)
from llm_cli.clients.config import get_setting, get_templates
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

kb = KeyBindings()
kb_exit = KeyBindings()


class LlmCliCompleter(Completer):
    """Provides completion for slash commands and their arguments."""

    def __init__(self, client: BaseLlmClient) -> None:
        self.client = client
        self.path_completer = PathCompleter(expanduser=True)

        # self.all_cmds will be generated dynamically
        self.path_cmds = ("/attach", "/save", "/load")
        self.provider_cmds = ("/p", "/provider")
        self.model_cmds = ("/m", "/model")
        self.template_cmds = ("/t", "/template")

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor

        # Dynamic command list from client (re-fetched every time to
        # support provider switching)
        all_cmds = ["/" + cmd for cmd in self.client.slash_commands]

        # 1. Command completion (if no space yet)
        if " " not in text and text.startswith("/"):
            for cmd in all_cmds:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))
            return

        # 2. Argument completion
        try:
            space_idx = text.index(" ")
        except ValueError:
            return

        cmd = text[:space_idx]
        # Calculate prefix for argument completion
        # We only complete the word being typed
        arg_text_full = text[space_idx + 1 :]
        arg_prefix = (
            arg_text_full.split()[-1]
            if arg_text_full and not arg_text_full.endswith(" ")
            else ""
        )
        if arg_text_full.endswith(" "):
            arg_prefix = ""

        # Determine start position for replacement
        # It should be negative length of current word
        start_pos = -len(arg_prefix)

        if cmd in self.provider_cmds:
            if hasattr(self.client, "PROVIDER_CONFIG"):
                # Use a set to avoid duplicates if multiple aliases point to same
                # section. Actually keys are aliases, so just list aliases.
                for alias in self.client.PROVIDER_CONFIG:
                    if alias.startswith(arg_prefix):
                        yield Completion(alias, start_position=start_pos)

        elif cmd in self.model_cmds:
            for alias in self.client.available_models:
                if alias.startswith(arg_prefix):
                    yield Completion(alias, start_position=start_pos)

        elif cmd in self.template_cmds:
            templates = get_templates()
            for name in templates:
                if name.startswith(arg_prefix):
                    yield Completion(name, start_position=start_pos)

        elif cmd in self.path_cmds:
            # Path completion needs the full part after command
            if text.startswith(cmd + " "):
                sub_text = text[len(cmd) + 1 :]
                new_doc = Document(sub_text, cursor_position=len(sub_text))
                yield from self.path_completer.get_completions(new_doc, complete_event)


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
        else:
            # Editor exited with error/abort status (e.g. :cq in vim)
            console.print(
                "\n[yellow]Editor aborted. Restoring previous text...[/yellow]"
            )
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
        self.history_path = client.history_path

        self.prompt_history: Any
        if self.history_path:
            Path(self.history_path).parent.mkdir(parents=True, exist_ok=True)
            self.prompt_history = FileHistory(self.history_path)
        else:
            self.prompt_history = InMemoryHistory()

        self.prompt_session: PromptSession = PromptSession(history=self.prompt_history)
        self.completer = LlmCliCompleter(client)

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
                # Use total tokens processed or turn count as metrics.
                user_turns = len(
                    [m for m in self.client.conversation if m.role == Role.USER]
                )
                if self.client.cumulative_total_tokens >= 50000 or user_turns >= 40:
                    msg = (
                        f"Context is large "
                        f"({self.client.cumulative_total_tokens:,} tokens, "
                        f"{user_turns} turns). "
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

            if usage:
                # Update cumulative tokens across providers.
                # OpenAI: 'total_tokens'
                # Claude: 'input_tokens' + 'output_tokens' or 'total_tokens'
                # Gemini: 'totalTokenCount'
                # Ollama: 'prompt_eval_count' + 'eval_count'
                total = (
                    usage.get("total_tokens")
                    or usage.get("totalTokenCount")
                    or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
                    or (usage.get("prompt_eval_count", 0) + usage.get("eval_count", 0))
                    or 0
                )
                if total > 0:
                    self.client.cumulative_total_tokens += total
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
                self._log_chat(response_text, role="Model")

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
        return self._get_input(message, exit_on_escape=True).lower() == "y"

    def _execute_tool_call(
        self, part: ContentPart, duration: float | None = None
    ) -> tuple[ContentPart, DataSource | None] | None:
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
        for msg in reversed(self.client.conversation):
            if msg.role == Role.USER:
                # Extract text parts
                texts = [
                    p.text for p in msg.parts if isinstance(p, ContentPart) and p.text
                ]
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
        # Check 'explanation' first (new), then fall back to 'thought' or 'reasoning'.
        explanation = (
            args.get("explanation") or args.get("thought") or args.get("reasoning")
        )
        if explanation:
            # Use consistent display name for reasoning
            display_name = self.client.get_display_name()
            duration_str = f" ({duration:.1f}s)" if duration is not None else ""
            title = f"[bold cyan]{display_name} (Reasoning){duration_str}[/bold cyan]"
            self._print_block(
                explanation,
                title=title,
                style="cyan",
            )

        tool_entry = registry.tools.get(name, {})
        skip_approval = tool_entry.get("skip_approval", False)

        # Check if it's one of the core tools, potentially namespaced
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
            # Display Agent Request in a Panel
            if is_write or is_edit or is_exec:
                # Detailed preview panel will be shown, so skip inline args
                request_content = f"[cyan]{escape(name)}[/cyan]"
            else:
                # Exclude explanation/thought from display args for cleaner output
                display_args = {
                    k: (v[:200] + "...") if isinstance(v, str) and len(v) > 200 else v
                    for k, v in args.items()
                    if k not in ("explanation", "thought", "reasoning")
                }
                request_content = (
                    f"[cyan]{escape(name)}[/cyan]({escape(str(display_args))})"
                )

            self._print_block(
                request_content,
                title="[bold yellow]🤖 Agent Request[/bold yellow]",
                style="yellow",
            )

            if is_write:
                self._preview_diff(args)
            elif is_edit:
                self._preview_edit_diff(args)
            elif is_exec:
                self._preview_command(args)

            user_input = self._get_input(
                "Allow execution? (y/N or feedback): ",
                exit_on_escape=True,
                raise_on_interrupt=True,
            )
            if user_input.lower() != "y":
                feedback = user_input if user_input.lower() != "n" else ""
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
                result_data = tool_entry["func"](**args)
            else:
                # Use status context for tool execution spinner
                with console.status(
                    f"[bold yellow]🏃 Executing {name}...[/bold yellow]",
                    spinner="dots",
                ):
                    result_data = tool_entry["func"](**args)

            injected_data = (
                result_data.pop("__llm_cli_data__", None)
                if isinstance(result_data, dict)
                else None
            )
            # injected is expected to be a DataSource or None
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

            # --- Truncation Logic Start ---
            # Apply a global safety limit on tool output length to prevent
            # token exhaustion.
            p_str = str(result_data)
            # Default limit 10,000 to prevent context overflow while keeping useful info
            max_len = int(get_setting("max_tool_output_len", "general") or 10000)

            if len(p_str) > max_len:
                original_len = len(p_str)
                p_str = p_str[:max_len] + (
                    f"\n... (Output truncated by system safety limit. "
                    f"Shown {max_len} of {original_len} characters. "
                    "Use tool parameters (e.g., start_line, start_offset) "
                    "to read the rest.)"
                )
                # Update result_data so the truncated version is sent to the LLM
                result_data = p_str
            # --- Truncation Logic End ---

            # Display Result in a Panel
            if is_exec:
                self._print_block(
                    escape(p_str),
                    title="[bold green]✅ Tool Output[/bold green]",
                    style="green",
                )
            else:
                # Display full content without 300 chars limit
                self._print_block(
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

    def _preview_diff(self, args: dict[str, Any]) -> None:
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
                    self._print_block(
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
                self._print_block(
                    syn,
                    title=f"[bold green]New File: {path}[/bold green]",
                    style="green",
                )
        except Exception:
            pass

    def _preview_edit_diff(self, args: dict[str, Any]) -> None:
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
                self._print_block(
                    syn,
                    title=title,
                    style="yellow",
                )
            else:
                self._print_block(
                    "[yellow]No changes detected in search/replace block.[/yellow]",
                    title=title,
                    style="yellow",
                )
        except Exception:
            pass

    def _preview_command(self, args: dict[str, Any]) -> None:
        try:
            command = args.get("command", "")
            if not command:
                return

            syn = Syntax(command, "bash", theme="monokai", word_wrap=True)
            self._print_block(
                syn,
                title="[bold]Execute Command[/bold]",
                style="magenta",
            )
        except Exception:
            pass
