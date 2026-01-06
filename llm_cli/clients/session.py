# llm_cli/clients/session.py

import copy
import datetime
import difflib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax

from llm_cli.clients.base import BaseLlmClient, CheckpointRequest, DataSource
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.tool_registry import registry
from llm_cli.security import CommandValidationError, validate_command

kb = KeyBindings()
kb_exit = KeyBindings()
console = Console()
md_separator = Rule()


@kb.add("c-delete")
def _(event):
    raise KeyboardInterrupt


@kb.add("c-j")
def _(event):
    event.current_buffer.insert_text("\n")


@kb_exit.add("escape")
def _(event):
    event.app.exit(exception=KeyboardInterrupt)


class ChatSession:
    """Manages the interactive CLI session and the ReAct loop."""

    def __init__(self, client: BaseLlmClient):
        self.client = client
        self.history_path = client.history_path
        self._checkpoint_hint_shown = False

        if self.history_path:
            Path(self.history_path).parent.mkdir(parents=True, exist_ok=True)
            self.prompt_history = FileHistory(self.history_path)
        else:
            self.prompt_history = InMemoryHistory()

    def run(
        self,
        initial_data: Optional[List[DataSource]] = None,
        sources: Optional[List[str]] = None,
    ):
        data = initial_data or []
        while True:
            try:
                if (
                    len(self.client.conversation) >= 30
                    and not self._checkpoint_hint_shown
                ):
                    console.print(
                        "[dim]Tip: Use /checkpoint to compress context.[/dim]"
                    )
                    self._checkpoint_hint_shown = True

                console.print(md_separator)
                # Apply both standard key bindings and exit-on-escape bindings
                combined_kb = merge_key_bindings([kb, kb_exit])
                user_input = prompt(
                    "> ",
                    history=self.prompt_history,
                    key_bindings=combined_kb,
                    enable_system_prompt=True,
                    enable_open_in_editor=True,
                ).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue

            try:
                console.print(md_separator)
                if user_input.startswith("!"):
                    if self._handle_shell_command(user_input, data):
                        continue

                try:
                    if self.client._handle_command(user_input, sources, data):
                        continue
                except CheckpointRequest:
                    self._handle_checkpoint()
                    continue

                data.append({"content": user_input, "content_type": "text/plain"})
                self.process_and_print(data)
                data = []
            except (KeyboardInterrupt, EOFError):
                console.print(
                    "\n[yellow]Interrupted. Returning to main prompt...[/yellow]"
                )
                data = []
            except Exception as e:
                console.print(f"[bold red]Error: {e}[/bold red]")
                data = []

    def process_and_print(self, data: List[DataSource]):
        self._log_chat(data, role="User")
        response_text, _ = self.client._send(data)
        if response_text is None:
            # Error already reported or request failed
            return
        response_text = self.client._format_response_text(response_text)

        while True:
            if response_text:
                self._log_chat(response_text, role="Model")
                if self.client.stdout:
                    print(response_text)
                else:
                    console.print(CustomMarkdown(response_text))

            if not self.client._has_pending_tool_calls():
                break

            last_msg = self.client.conversation[-1]
            tool_results_parts = []
            injected_datas = []

            for part in last_msg.get("parts", []):
                if "functionCall" in part:
                    res = self._execute_tool_call(part["functionCall"])
                    if not res:
                        return
                    tool_result, injected = res
                    tool_results_parts.append(tool_result)
                    if injected:
                        injected_datas.append(injected)

            if tool_results_parts:
                self.client.conversation.append(
                    {"role": "function", "parts": tool_results_parts}
                )
                if injected_datas:
                    self._log_chat(injected_datas, role="Tool Output")
                response_text, _ = self.client._send(injected_datas)
                if response_text is None:
                    break
                response_text = self.client._format_response_text(response_text)
            else:
                break

    def _handle_checkpoint(self):
        console.print("[yellow]Generating summary...[/yellow]")
        summarize_prompt = (
            "Summarize the conversation so far, preserving key context, "
            "decisions, code changes, and remaining tasks. "
            "Be comprehensive but concise."
        )

        temp_conversation = copy.deepcopy(self.client.conversation)
        temp_conversation.append(
            {"role": "user", "parts": [{"text": summarize_prompt}]}
        )

        original_conversation = self.client.conversation
        self.client.conversation = temp_conversation

        try:
            summary, _ = self.client._send([])
            if not summary:
                console.print("[red]Failed to generate summary.[/red]")
                self.client.conversation = original_conversation
                return

            title = "[bold cyan]Proposed Context Summary[/bold cyan]"
            console.print(Panel(summary, title=title, expand=False))

            if self._confirm("Clear history and use this summary? (y/N): "):
                self.client.conversation = [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": f"SYSTEM: History cleared. "
                                f"Continue from this summary:\n\n{summary}"
                            }
                        ],
                    }
                ]
                console.print("[green]✅ Context refreshed.[/green]")
                self._checkpoint_hint_shown = False
            else:
                console.print("[yellow]Checkpoint canceled.[/yellow]")
                self.client.conversation = original_conversation
        except (KeyboardInterrupt, EOFError):
            self.client.conversation = original_conversation
            raise
        except Exception as e:
            console.print(f"[bold red]Checkpoint failed: {e}[/bold red]")
            self.client.conversation = original_conversation

    def _log_chat(self, content: Any, role: str):
        if not self.client.chat_log_path:
            return

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            path = Path(self.client.chat_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            text_content = ""
            if isinstance(content, list):
                text_content = "\n".join(
                    str(item.get("content", f"[File/Media: {item.get('file_uri')}]"))
                    for item in content
                )
            else:
                text_content = str(content)

            with path.open("a", encoding="utf-8") as f:
                f.write(f"--- {timestamp} [{role}] ---\n{text_content}\n\n")

            self.client._trim_log_file(path, self.client.max_chat_log_lines)
        except Exception as e:
            console.print(f"[dim red]Chat logging failed: {e}[/dim red]")

    def _get_input(self, message: str, exit_on_escape: bool = False, **kwargs) -> str:
        """Helper for console input, supporting both TTY and prompt_toolkit."""
        if sys.stdin.isatty():
            # Use provided kwargs, but set defaults for key_bindings and editor
            # to match the main prompt's behavior.
            current_kb = merge_key_bindings([kb, kb_exit]) if exit_on_escape else kb
            kwargs.setdefault("key_bindings", current_kb)
            kwargs.setdefault("enable_open_in_editor", True)
            kwargs.setdefault("enable_system_prompt", True)
            return prompt(message, **kwargs).strip()

        try:
            tty_path = "/dev/tty" if sys.platform != "win32" else "CON"
            with open(tty_path, "r") as tty:
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

    def _execute_tool_call(self, call: Dict[str, Any]) -> Optional[Any]:
        tool_id, name, args = (
            call.get("id", "unknown"),
            call["name"],
            call.get("args", {}),
        )

        # Extract thought/reasoning for visibility
        thought = args.get("thought") or args.get("reasoning")
        if thought:
            console.print(
                Panel(
                    thought,
                    title="[bold cyan]🤔 Thought[/bold cyan]",
                    border_style="cyan",
                )
            )

        title_prefix = "[bold yellow]🤖 Agent Request:[/bold yellow]"
        if name in ("write_file", "execute_command", "generate_image"):
            # Detailed preview panel will be shown, so skip inline args
            console.print(f"{title_prefix} [cyan]{escape(name)}[/cyan]")
        else:
            # Exclude thought from display args for cleaner output
            display_args = {
                k: (v[:200] + "...") if isinstance(v, str) and len(v) > 200 else v
                for k, v in args.items()
                if k not in ("thought", "reasoning")
            }
            console.print(
                f"{title_prefix} [cyan]{escape(name)}[/cyan]"
                f"({escape(str(display_args))})"
            )

        if name == "write_file":
            self._preview_diff(args)
        elif name == "execute_command":
            self._preview_command(args)
        elif name == "generate_image":
            self._preview_image_prompt(args)

        user_input = self._get_input(
            "Allow execution? (y/N or feedback): ",
            exit_on_escape=True,
            history=self.prompt_history,
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

            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {"result": result_msg},
                }
            }, None

        try:
            if name not in registry.tools:
                raise ValueError(f"Tool '{name}' not found.")

            result_data = registry.tools[name]["func"](**args)
            injected = (
                result_data.pop("__llm_cli_data__", None)
                if isinstance(result_data, dict)
                else None
            )

            p_str = str(result_data)
            if "execute_command" in name:
                console.print(f"[dim]Result:[/dim]\n{escape(p_str)}")
            else:
                preview = p_str[:300] + ("..." if len(p_str) > 300 else "")
                console.print(f"[dim]Result: {escape(preview)}[/dim]")

            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {"result": result_data},
                }
            }, injected
        except Exception as e:
            console.print(f"[bold red]Tool execution failed: {e}[/bold red]")
            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {"result": f"Error: {e}"},
                }
            }, None

    def _preview_diff(self, args: Dict[str, Any]):
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
                    syn = Syntax("".join(diff), "diff", theme="monokai", word_wrap=True)
                    console.print(
                        Panel(
                            syn,
                            title=f"[bold]Diff: {path}[/bold]",
                            border_style="yellow",
                            expand=False,
                        )
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
                console.print(
                    Panel(
                        syn,
                        title=f"[bold green]New File: {path}[/bold green]",
                        border_style="green",
                        expand=False,
                    )
                )
        except Exception:
            pass

    def _preview_command(self, args: Dict[str, Any]):
        try:
            command = args.get("command", "")
            if not command:
                return

            syn = Syntax(command, "bash", theme="monokai", word_wrap=True)
            console.print(
                Panel(
                    syn,
                    title="[bold]Execute Command[/bold]",
                    border_style="magenta",
                    expand=False,
                )
            )
        except Exception:
            pass

    def _preview_image_prompt(self, args: Dict[str, Any]):
        try:
            prompt_text = args.get("prompt", "")
            output_path = args.get("output_path", "default")
            if not prompt_text:
                return

            console.print(
                Panel(
                    prompt_text,
                    title=f"[bold]Image Prompt (Output: {output_path})[/bold]",
                    border_style="green",
                    expand=False,
                )
            )
        except Exception:
            pass

    def _handle_shell_command(self, user_input: str, data: List[DataSource]) -> bool:
        cmd = user_input[1:].strip()

        # Validate command against security whitelist
        try:
            validate_command(cmd)
        except CommandValidationError as e:
            console.print(f"[bold red]Security Error:[/bold red] {e}")
            console.print(
                "[yellow]For security reasons, only whitelisted commands "
                "are allowed.[/yellow]\n"
                "[dim]Check the allowed commands list in your config file "
                "(~/.config/llm_cli/config.toml) or see the default "
                "whitelist in llm_cli/security/command_validator.py[/dim]"
            )
            return True

        console.print(f"[dim]Executing: {cmd}[/dim]")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            output = result.stdout + (
                f"\nSTDERR:\n{result.stderr}" if result.stderr else ""
            )
            print(output)
            if self._confirm("Add to context? (y/N): "):
                data.append(
                    {
                        "content": f"Command: `{cmd}`\nOutput:\n```\n{output}\n```",
                        "content_type": "text/plain",
                    }
                )
                console.print("[green]Output added to context.[/green]")
            else:
                console.print("[yellow]Canceled.[/yellow]")
            return True
        except Exception as e:
            console.print(f"[bold red]Execution Error: {e}[/bold red]")
            return True
