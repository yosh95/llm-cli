# llm_cli/clients/session.py

import difflib
import subprocess
import datetime
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markup import escape
from rich.rule import Rule
from rich.syntax import Syntax
from rich.panel import Panel

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.modules.custom_markdown import CustomMarkdown
from llm_cli.modules.agent_tools import TOOL_FUNCTIONS

kb = KeyBindings()
console = Console()
md_separator = Rule()


@kb.add('c-delete')
def _(event):
    raise KeyboardInterrupt


@kb.add('c-j')
def _(event):
    event.current_buffer.insert_text('\n')


class ChatSession:
    """Manages the interactive CLI session and the ReAct loop."""

    def __init__(self, client: BaseLlmClient):
        self.client = client
        self.history_path = client.history_path

        if self.history_path:
            Path(self.history_path).parent.mkdir(parents=True, exist_ok=True)
            self.prompt_history = FileHistory(self.history_path)
        else:
            self.prompt_history = InMemoryHistory()

    def run(
        self,
        initial_data: Optional[List[DataSource]] = None,
        sources: Optional[List[str]] = None
    ):
        """Entry point for the interactive chat loop."""
        data = initial_data or []

        while True:
            try:
                console.print(md_separator)
                user_input = prompt(
                    '> ', history=self.prompt_history, key_bindings=kb,
                    enable_system_prompt=True,
                    enable_open_in_editor=True
                ).strip()

                if not user_input:
                    continue

                console.print(md_separator)

                if user_input.startswith('!'):
                    if self._handle_shell_command(user_input, data):
                        continue

                if self.client._handle_command(user_input, sources):
                    continue

                data.append({
                    "content": user_input,
                    "content_type": "text/plain"
                })
                self.process_and_print(data)
                data = []
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                console.print(f"[bold red]Error: {e}[/bold red]")

    def process_and_print(self, data: List[DataSource]):
        """Executes the request and handles the ReAct agent loop."""
        self._log_chat(data, role="User")
        response_text, _ = self.client._send(data)
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

            # Handle Tool Calls
            last_msg = self.client.conversation[-1]
            tool_results_parts = []
            injected_datas = []

            for part in last_msg.get("parts", []):
                if "functionCall" in part:
                    res = self._execute_tool_call(part["functionCall"])
                    if res == "CHECKPOINT_SUCCESS":
                        # History already cleared and summary injected.
                        return

                    if res is None:
                        # Unexpected error in tool execution logic
                        return

                    tool_result, injected = res
                    tool_results_parts.append(tool_result)
                    if injected:
                        injected_datas.append(injected)

            if tool_results_parts:
                self.client.conversation.append({
                    "role": "function",
                    "parts": tool_results_parts
                })
                if injected_datas:
                    self._log_chat(injected_datas, role="Tool Output")

                response_text, _ = self.client._send(injected_datas)
                response_text = self.client._format_response_text(
                    response_text
                )
            else:
                break

    def _log_chat(self, content: Any, role: str):
        """Append entry to chat log."""
        if not self.client.chat_log_path:
            return

        try:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            path = Path(self.client.chat_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            text_content = ""
            if isinstance(content, list):
                parts = []
                for item in content:
                    if item.get("content"):
                        parts.append(str(item["content"]))
                    elif item.get("file_uri"):
                        parts.append(f"[File/Media: {item['file_uri']}]")
                text_content = "\n".join(parts)
            else:
                text_content = str(content)

            with path.open("a", encoding="utf-8") as f:
                f.write(f"--- {timestamp} [{role}] ---\n{text_content}\n\n")

            self.client._trim_log_file(path, self.client.max_chat_log_lines)
        except Exception as e:
            console.print(f"[dim red]Chat logging failed: {e}[/dim red]")

    def _confirm(self, message: str) -> bool:
        """
        Ask for y/n confirmation, handling cases where stdin is redirected.
        """
        if sys.stdin.isatty():
            try:
                return prompt(message).strip().lower() == 'y'
            except (EOFError, KeyboardInterrupt):
                return False

        # If stdin is not a TTY (e.g. piped input), try to read from /dev/tty
        try:
            tty_path = '/dev/tty' if sys.platform != 'win32' else 'CON'
            with open(tty_path, 'r') as tty:
                # Use stderr for the prompt message to avoid polluting stdout
                # which might be piped to another process.
                sys.stderr.write(message)
                sys.stderr.flush()
                line = tty.readline()
                if not line:
                    return False
                return line.strip().lower() == 'y'
        except Exception:
            # Fallback: if we cannot open TTY, we must deny to be safe
            console.print(
                "[yellow]Warning: Could not access TTY for confirmation. "
                "Denying for safety.[/yellow]"
            )
            return False

    def _execute_tool_call(self, call: Dict[str, Any]) -> Optional[Any]:
        tool_id = call.get("id", "unknown")
        name = call["name"]
        args = call.get("args", {})

        # Display request
        display_args = {
            k: (v[:200] + "...")
            if isinstance(v, str) and len(v) > 200 else v
            for k, v in args.items()
        }
        console.print(
            f"[bold yellow]🤖 Agent Request:[/bold yellow] "
            f"[cyan]{escape(name)}[/cyan]({escape(str(display_args))})"
        )

        if name == "checkpoint_conversation":
            summary = args.get("summary", "")
            panel_title = "[bold cyan]Proposed Context Summary[/bold cyan]"
            console.print(Panel(summary, title=panel_title))
            if self._confirm("Clear history and use this summary? (y/N): "):
                self.client.conversation = []
                # Inject summary from user role
                self.client.conversation.append({
                    "role": "user",
                    "parts": [{
                        "text": f"SYSTEM: History cleared. "
                                f"Continue from this summary:\n\n{summary}"
                    }]
                })
                console.print("[green]✅ Context refreshed.[/green]")
                return "CHECKPOINT_SUCCESS"
            else:
                console.print("[yellow]Checkpoint denied.[/yellow]")
                return {
                    "functionResponse": {
                        "id": tool_id,
                        "name": name,
                        "response": {
                            "result": (
                                "Error: User denied checkpoint. "
                                "Do not attempt to summarize again "
                                "unless instructed. Continue the "
                                "conversation normally or ask the user "
                                "how they want to manage the context."
                            )
                        }
                    }
                }, None

        if name == "write_file":
            self._preview_diff(args)

        if not self._confirm("Allow execution? (y/N): "):
            console.print("[red]Operation denied.[/red]")
            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {
                        "result": (
                            "Error: Operation denied by user. "
                            "DO NOT retry this tool or proceed with other "
                            "tool calls. Stop and ask the user for the "
                            "reason for denial or for further instructions."
                        )
                    }
                }
            }, None

        try:
            result_data = TOOL_FUNCTIONS[name](**args)
            injected = None
            if (
                isinstance(result_data, dict) and
                "__llm_cli_data__" in result_data
            ):
                injected = result_data.pop("__llm_cli_data__")

            p_str = str(result_data)
            if name == "execute_command":
                console.print(f"[dim]Result:[/dim]\n{escape(p_str)}")
            else:
                preview = p_str[:300] + ("..." if len(p_str) > 300 else "")
                console.print(f"[dim]Result: {escape(preview)}[/dim]")

            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {"result": result_data}
                }
            }, injected
        except Exception as e:
            console.print(f"[bold red]Tool execution failed: {e}[/bold red]")
            return {
                "functionResponse": {
                    "id": tool_id,
                    "name": name,
                    "response": {"result": f"Error: {e}"}
                }
            }, None

    def _preview_diff(self, args: Dict[str, Any]):
        """Show what will be changed in write_file."""
        try:
            path = Path(args.get("path", ""))
            new_content = args.get("content", "")
            if not path or not new_content:
                console.print(
                    "[yellow]Missing path or content for preview.[/yellow]"
                )
                return

            if path.exists():
                if path.is_dir():
                    console.print(f"[red]Error: {path} is a directory.[/red]")
                    return
                try:
                    old_content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    console.print(
                        f"[yellow]Cannot preview binary file: {path}[/yellow]"
                    )
                    return

                diff = list(difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{path}", tofile=f"b/{path}"
                ))
                if diff:
                    console.print(Panel(
                        Syntax("".join(diff), "diff", theme="monokai"),
                        title=f"[bold]Diff: {path}[/bold]",
                        border_style="yellow"
                    ))
                else:
                    console.print(f"[dim]No changes to {path}[/dim]")
            else:
                lexer = Syntax.guess_lexer(str(path), code=new_content)
                console.print(Panel(
                    Syntax(new_content, lexer,
                           theme="monokai", line_numbers=True),
                    title=f"[bold green]New File: {path}[/bold green]",
                    border_style="green"
                ))
        except Exception as e:
            console.print(f"[dim]Preview failed: {e}[/dim]")

    def _handle_shell_command(
        self, user_input: str, data: List[DataSource]
    ) -> bool:
        cmd = user_input[1:].strip()
        console.print(f"[dim]Executing: {cmd}[/dim]")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True
            )
            output = (
                result.stdout +
                (f"\nSTDERR:\n{result.stderr}" if result.stderr else "")
            )
            print(output)
            if self._confirm("Add to context? (y/N): "):
                data.append({
                    "content": f"Command: `{cmd}`\nOutput:\n"
                               f"```\n{output}\n```",
                    "content_type": "text/plain"
                })
                console.print("[green]Added.[/green]")
                return True
        except Exception as e:
            console.print(f"[bold red]Execution Error: {e}[/bold red]")
        return False
