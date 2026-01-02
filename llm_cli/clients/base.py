# llm_cli/clients/base.py

import datetime
import uuid
import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import process_file, fetch_url_content
from llm_cli.modules.tool_registry import registry

console = Console()

ContentPart = Dict[str, Any]
Message = Dict[str, Any]
Conversation = List[Message]
DataSource = Dict[str, Any]


class ProviderSwitchRequest(Exception):
    def __init__(self, provider: str):
        self.provider = provider


class CheckpointRequest(Exception):
    pass


class BaseLlmClient(ABC):
    """Abstract Base Class for LLM API clients."""

    def __init__(self,
                 initial_model_alias: str,
                 api_key_name: str,
                 config_section: str,
                 pdf_as_base64: bool,
                 stdout: bool,
                 render_markdown: bool = True,
                 initial_tools: Optional[List[str]] = None,
                 disable_system_prompt: bool = False,
                 enable_mcp: bool = False,
                 live_debug: bool = False):

        self.config_section = config_section
        self.api_key = get_setting(api_key_name, config_section)
        self.pdf_as_base64 = pdf_as_base64
        self.stdout = stdout
        self.render_markdown = render_markdown
        self.live_debug = live_debug

        raw_prompt = get_setting("system_prompt", config_section) or ""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S (%A)')
        self.system_prompt = f"Current date and time: {now}"
        if raw_prompt:
            self.system_prompt += f"\n{raw_prompt}"

        self.system_prompt_enabled = not disable_system_prompt

        self.available_models: Dict[str, str] = {}
        self.current_alias = ""
        self.model = ""
        self._load_model_aliases()
        self.set_model(initial_model_alias) or self.set_model('default')

        self.conversation: Conversation = []
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_request_duration: Optional[float] = None

        self.history_path = self._expand(
            get_setting("LLM_PROMPT_HISTORY", "general")
        )
        self.chat_log_path = self._expand(
            get_setting("LLM_CHAT_LOG", "general")
        )
        self.max_chat_log_lines = int(
            get_setting("max_chat_log_lines", "general") or 10000
        )

        self.active_tools: List[str] = (
            initial_tools if initial_tools is not None
            else list(registry.tools.keys())
        )

        if enable_mcp:
            self._init_mcp(initial_tools is None)

    def _init_mcp(self, update_active_tools: bool):
        try:
            from llm_cli.clients.mcp_manager import mcp_manager
            already_initialized = mcp_manager._initialized
            remote_tool_names = registry.register_remote_tools(mcp_manager)
            if remote_tool_names:
                if not already_initialized:
                    console.print(
                        f"[dim cyan]Registered {len(remote_tool_names)} "
                        "remote MCP tools.[/dim cyan]"
                    )
                if update_active_tools:
                    for tn in remote_tool_names:
                        if tn not in self.active_tools:
                            self.active_tools.append(tn)
        except ImportError:
            pass
        except Exception as e:
            console.print(
                f"[yellow]Note: MCP initialization failed: {e}[/yellow]"
            )

    def _expand(self, p: Optional[str]) -> Optional[str]:
        return str(Path(p).expanduser()) if p else None

    @abstractmethod
    def _load_model_aliases(self):
        """Load model aliases from config."""
        pass

    @abstractmethod
    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        """Send the request to the specific provider API."""
        pass

    def set_model(self, alias: str) -> bool:
        if alias in self.available_models:
            self.current_alias = alias
            self.model = self.available_models[alias]
            return True
        return False

    def talk(
        self,
        initial_data: Optional[List[DataSource]] = None,
        sources: Optional[List[str]] = None
    ):
        """Start an interactive chat session."""
        from llm_cli.clients.session import ChatSession
        ChatSession(self).run(initial_data, sources)

    def process_sources(self, sources: List[str]):
        """Process input sources and either output result or start chat."""
        data = [
            processed for s in sources
            if (processed := self._process_single_source(s))
        ]
        # Check if there is any explicit prompt (text not from a file or URL)
        has_prompt = any(not d.get("is_file_or_url") for d in data)

        from llm_cli.clients.session import ChatSession
        session = ChatSession(self)

        if data:
            # If prompt or stdout is requested, process immediately.
            # This handles cases like:
            # - llm "hi"
            # - llm "Summarize this" https://...
            # - llm -s README.md
            if self.stdout or has_prompt:
                session.process_and_print(data)
                # If not stdout, enter interactive mode for follow-up.
                if not self.stdout:
                    session.run(sources=sources)
            else:
                # No prompt, only external resources (files/URLs).
                # Start interactive session and wait for instructions.
                session.run(initial_data=data, sources=sources)
        else:
            session.run(sources=sources)

    def _process_single_source(self, source: str) -> Optional[DataSource]:
        if source.startswith("http"):
            content, ctype = fetch_url_content(source, self.pdf_as_base64)
            if content:
                return {
                    "content": content,
                    "content_type": ctype,
                    "is_file_or_url": True
                }
            return None

        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            res = process_file(path, self.pdf_as_base64)
            if res:
                res["is_file_or_url"] = True
            return res

        return {"content": source, "content_type": "text/plain"}

    def _has_pending_tool_calls(self) -> bool:
        if (
            not self.conversation or
            self.conversation[-1].get("role") != "model"
        ):
            return False
        return any(
            "functionCall" in p
            for p in self.conversation[-1].get("parts", [])
        )

    def _handle_command(
        self,
        user_input: str,
        sources: Optional[List[str]],
        pending_data: Optional[List[DataSource]] = None
    ) -> bool:
        """Handle in-chat slash commands."""
        if not user_input.startswith('/'):
            return False
        
        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd in self.available_models:
            self.set_model(cmd)
            console.print(
                f"[cyan]Model switched to: {self.current_alias}[/cyan]"
            )
            return True

        if cmd in ('m', 'models'):
            console.print("[bold]Available Models:[/bold]")
            for alias, name in self.available_models.items():
                active = "*" if alias == self.current_alias else " "
                console.print(
                    f" {active} [cyan]{alias:15}[/cyan] -> [dim]{name}[/dim]"
                )
            return True

        if cmd in ('google', 'openai', 'anthropic', 'xai'):
            raise ProviderSwitchRequest(cmd)

        if cmd in ('checkpoint', 'cp'):
            raise CheckpointRequest()

        if cmd == 'attach':
            path_str = args.strip()
            if not path_str:
                console.print("[red]Usage: /attach <path>[/red]")
                return True
            
            res = self._process_single_source(path_str)
            if res and res.get("is_file_or_url"):
                if res.get("content_type") == "text/plain":
                    console.print(
                        f"[yellow]Notice: {path_str} is text. "
                        "Added as text context.[/yellow]"
                    )
                else:
                    console.print(
                        f"[green]Attached {res['content_type']}: "
                        f"{path_str}[/green]"
                    )
                if pending_data is not None:
                    pending_data.append(res)
            else:
                console.print(
                    f"[red]Failed to attach: {path_str} (File not found or "
                    "invalid source)[/red]"
                )
            return True

        if cmd == 'dump':
            # 1. Display conversation history first
            json_str = json.dumps(
                self.conversation, indent=2, ensure_ascii=False
            )
            syn = Syntax(
                json_str, "json", theme="monokai",
                background_color="default", word_wrap=True
            )
            console.print(Panel(
                syn, title="Conversation History", border_style="blue"
            ))

            # 2. Display pending context if it exists (at the end)
            if pending_data:
                json_pending = json.dumps(
                    pending_data, indent=2, ensure_ascii=False
                )
                syn_pending = Syntax(
                    json_pending, "json", theme="monokai",
                    background_color="default", word_wrap=True
                )
                console.print(Panel(
                    syn_pending, title="Pending Context (Next Request)",
                    border_style="yellow"
                ))
            return True

        if cmd == 'raw':
            for msg in self.conversation:
                role = msg.get("role", "unknown")
                for p in msg.get("parts", []):
                    role_suffix = " (THOUGHT)" if "thought" in p else ""
                    text = p.get("text") or p.get("thought")
                    if text:
                        print(f"[{role.upper()}{role_suffix}]\n{text}\n")
            return True

        if cmd in ('c', 'clear'):
            self.conversation.clear()
            console.print("[yellow]Conversation history cleared.[/yellow]")
            return True

        if cmd in ('q', 'quit'):
            raise EOFError

        if cmd == 'tools':
            tools_str = ', '.join(self.active_tools) or 'None'
            console.print(f"[bold]Active Tools:[/bold] {tools_str}")
            return True

        if cmd in ('debug', 'd'):
            self.live_debug = not self.live_debug
            status = "ENABLED" if self.live_debug else "DISABLED"
            console.print(f"[magenta]Live debug mode {status}.[/magenta]")
            return True

        if cmd in ('info', 'i'):
            debug_status = "ON" if self.live_debug else "OFF"
            tools_str = ', '.join(self.active_tools) or 'None'
            console.print(
                "[bold]Session Info:[/bold]\n"
                f"  Provider: [cyan]{self.config_section}[/cyan]\n"
                f"  Model: [cyan]{self.model}[/cyan] "
                f"(Alias: {self.current_alias})\n"
                f"  Tools: {tools_str}\n"
                f"  Debug: [magenta]{debug_status}[/magenta]\n"
                f"  History: {len(self.conversation)} messages"
            )
            return True

        if cmd in ('help', 'h'):
            self._print_help()
            return True

        return False

    def _print_help(self):
        models_str = ', '.join(self.available_models.keys())
        console.print(
            "[bold]Available Commands:[/bold]\n"
            "  /attach <path> Attach media/file to context\n"
            "  /clear (c)     Clear conversation history\n"
            "  /checkpoint(cp)Summarize and clear history\n"
            "  /dump          Dump conversation history as JSON\n"
            "  /raw           Show conversation as raw text\n"
            "  /quit (q)      Exit the application\n"
            "  /info (i)      Show session info\n"
            "  /debug (d)     Toggle live debug mode\n"
            "  /models (m)    List available models\n"
            "  /tools         Show active tools\n"
            "  /google, /openai, /anthropic, /xai  Switch provider\n"
            f"  <model_alias>  Switch to specific model ({models_str})"
        )

    def _trim_log_file(self, path: Path, max_lines: int):
        try:
            if not path.exists():
                return
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            if len(lines) > max_lines:
                path.write_text("".join(lines[-max_lines:]), encoding="utf-8")
        except Exception as e:
            console.print(f"[dim red]Log trimming failed: {e}[/dim red]")

    def _save_inline_image_and_get_log_entry(
        self, inline_data: Dict[str, Any]
    ) -> Optional[str]:
        if inline_data.get('mimeType', '').startswith('image/'):
            ext = inline_data['mimeType'].split('/')[-1]
            now_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = f"output_image_{now_str}_{uuid.uuid4().hex[:4]}.{ext}"
            try:
                Path(fname).write_bytes(base64.b64decode(inline_data['data']))
                return f"\n**output image: {fname}**"
            except Exception as e:
                console.print(f"[red]Failed to save image: {e}[/red]")
        return None

    def _log_debug(
        self,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None
    ):
        if not self.live_debug:
            return

        timestamp = datetime.datetime.now().strftime('%H:%M:%S')

        try:
            self._print_live_debug(
                timestamp, response_obj, request_payload, response_content
            )
        except Exception as e:
            console.print(f"[dim red]Live debug display failed: {e}[/dim red]")

    def _print_live_debug(
        self,
        timestamp: str,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None
    ):
        def _format_json(data):
            if isinstance(data, (dict, list)):
                return Syntax(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    "json", theme="monokai",
                    background_color="default", word_wrap=True
                )
            return str(data)

        if response_obj:
            req_info = []
            if hasattr(response_obj, 'request'):
                req = response_obj.request
                req_info.append(f"[bold]URL:[/bold] {req.url}")
                if req.body:
                    try:
                        b_str = (
                            req.body.decode('utf-8')
                            if isinstance(req.body, bytes)
                            else str(req.body)
                        )
                        req_info.append(_format_json(json.loads(b_str)))
                    except Exception:
                        req_info.append(str(req.body))

            if req_info:
                title = f"[bold cyan]API Request ({timestamp})[/bold cyan]"
                console.print(Panel(
                    Group(*req_info), title=title,
                    border_style="cyan", expand=False
                ))

            res_info = [f"[bold]Status:[/bold] {response_obj.status_code}"]
            try:
                res_info.append(_format_json(response_obj.json()))
            except Exception:
                res_info.append(response_obj.text)

            title = f"[bold green]API Response ({timestamp})[/bold green]"
            console.print(Panel(
                Group(*res_info), title=title,
                border_style="green", expand=False
            ))
        else:
            if request_payload:
                title = f"[bold cyan]Payload Request ({timestamp})[/bold cyan]"
                console.print(Panel(
                    _format_json(request_payload), title=title,
                    border_style="cyan", expand=False
                ))
            if response_content:
                title = (
                    f"[bold green]Payload Response ({timestamp})"
                    "[/bold green]"
                )
                console.print(Panel(
                    _format_json(response_content), title=title,
                    border_style="green", expand=False
                ))

    def _report_error(self, provider_name: str, e: Exception):
        import requests
        error_msg = str(e)
        if (
            isinstance(e, requests.exceptions.HTTPError) and
            e.response is not None
        ):
            try:
                body_str = json.dumps(
                    e.response.json(), indent=2, ensure_ascii=False
                )
                error_msg += f"\nResponse Body: {body_str}"
            except Exception:
                if e.response.text:
                    error_msg += f"\nResponse Body: {e.response.text}"

        console.print(
            f"[bold red]{provider_name} Error: {error_msg}[/bold red]"
        )

    def _format_response_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        prefix = f"({self.config_section}/{self.current_alias}/{self.model})"
        return f"**{prefix}:**  \n{text.strip()}"
