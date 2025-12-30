# llm_cli/clients/session.py

import difflib
import subprocess
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markup import escape
from rich.rule import Rule
from rich.syntax import Syntax

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
        # initial_data is used only for the first turn
        # After that, it's already in conversation history
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
                # After first turn, initial_data is in conversation
                # Only new user input should be added in subsequent turns
                data = []
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                console.print(f"[bold red]Error: {e}[/bold red]")

    def process_and_print(self, data: List[DataSource]):
        """Executes the request and handles the ReAct agent loop."""
        self._log_chat(data, role="User")
        response_text, _ = self.client._send(data)

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
                    if res is None:  # Denied by user
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
                # Log tool outputs
                if injected_datas:
                    self._log_chat(injected_datas, role="Tool Output")

                response_text, _ = self.client._send(injected_datas)
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
            if isinstance(content, list):  # List[DataSource]
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

            # Trim log file if it exceeds max lines
            self.client._trim_log_file(path, self.client.max_chat_log_lines)
        except Exception as e:
            console.print(f"[dim red]Chat logging failed: {e}[/dim red]")

    def _execute_tool_call(self, call: Dict[str, Any]) -> Optional[tuple]:
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

        # Specific preview for write_file
        if name == "write_file":
            self._preview_diff(args)

        if prompt("Allow execution? (y/N): ").strip().lower() != 'y':
            console.print("[red]Operation denied.[/red]")
            return None

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
                    "name": name,
                    "response": {"result": result_data}
                }
            }, injected
        except Exception as e:
            console.print(f"[bold red]Tool execution failed: {e}[/bold red]")
            return {
                "functionResponse": {
                    "name": name,
                    "response": {"result": f"Error: {e}"}
                }
            }, None

    def _preview_diff(self, args: Dict[str, Any]):
        try:
            path = Path(args["path"])
            new_content = args["content"]
            if path.exists():
                old_content = path.read_text(encoding="utf-8")
                diff = list(difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{path}", tofile=f"b/{path}"
                ))
                if diff:
                    console.print(
                        Syntax("".join(diff), "diff", theme="monokai")
                    )
            else:
                console.print(f"[bold green]New file: {path}[/bold green]")
                lexer = Syntax.guess_lexer(str(path), code=new_content)
                console.print(Syntax(
                    new_content, lexer, theme="monokai", line_numbers=True
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
            if prompt("Add to context? (y/N): ").strip().lower() == 'y':
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
