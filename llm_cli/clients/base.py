# llm_cli/clients/base.py

import datetime
import uuid
import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
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
                 enable_mcp: bool = False):

        self.config_section = config_section
        self.api_key = get_setting(api_key_name, config_section)
        self.pdf_as_base64 = pdf_as_base64
        self.stdout = stdout
        self.render_markdown = render_markdown

        raw_prompt = get_setting("system_prompt", config_section) or ""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S (%A)')

        # Context management instruction
        context_instruction = (
            "\n\n[CONTEXT MANAGEMENT]\n"
            "If the conversation becomes long or the context window is "
            "cluttered with large outputs, use the `checkpoint_conversation` "
            "tool. This tool allows you to summarize current progress and "
            "clear history. Your summary must be exhaustive enough to "
            "continue the task without any previous messages."
        )

        if raw_prompt:
            self.system_prompt = (
                f"Current date and time: {now}\n{raw_prompt}"
                f"{context_instruction}"
            )
        else:
            self.system_prompt = (
                f"Current date and time: {now}"
                f"{context_instruction}"
            )

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
        self.request_debug_log_path = self._expand(
            get_setting("LLM_REQUEST_DEBUG_LOG", "general")
        )
        self.max_chat_log_lines = int(
            get_setting("max_chat_log_lines", "general") or 10000
        )
        self.max_debug_log_lines = int(
            get_setting("max_debug_log_lines", "general") or 10000
        )

        # Initialize base tools first
        self.active_tools: List[str] = (
            initial_tools if initial_tools is not None
            else list(registry.tools.keys())
        )

        # Handle MCP Remote Tools
        if enable_mcp:
            try:
                from llm_cli.clients.mcp_manager import mcp_manager
                # Check if already initialized to avoid double printing
                # when using UnifiedClient which wraps other clients.
                already_initialized = mcp_manager._initialized

                remote_tool_names = registry.register_remote_tools(mcp_manager)
                if remote_tool_names:
                    if not already_initialized:
                        console.print(
                            f"[dim cyan]Registered {len(remote_tool_names)} "
                            "remote MCP tools.[/dim cyan]"
                        )
                    # Ensure remote tools are added to active list
                    # if not overriding
                    if initial_tools is None:
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
        data = []
        for s in sources:
            processed = self._process_single_source(s)
            if processed:
                data.append(processed)

        from llm_cli.clients.session import ChatSession
        session = ChatSession(self)

        if data:
            has_media = any(d.get("is_file_or_url") for d in data)
            if self.stdout or not has_media:
                session.process_and_print(data)
                if not self.stdout and not has_media:
                    session.run(sources=sources)
            else:
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
        if not self.conversation:
            return False
        if self.conversation[-1].get("role") != "model":
            return False
        return any(
            "functionCall" in p
            for p in self.conversation[-1].get("parts", [])
        )

    def _handle_command(
        self, user_input: str, sources: Optional[List[str]]
    ) -> bool:
        """Handle in-chat slash commands."""
        if not user_input.startswith('/'):
            return False
        cmd = user_input[1:]

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

        if cmd in ('c', 'clear'):
            self.conversation.clear()
            console.print("[yellow]Conversation history cleared.[/yellow]")
            return True

        if cmd in ('q', 'quit'):
            raise EOFError

        if cmd == 'tools':
            console.print(
                f"[bold]Active Tools:[/bold] "
                f"{', '.join(self.active_tools) or 'None'}"
            )
            return True

        if cmd == 'info' or cmd == 'i':
            console.print(
                "[bold]Session Info:[/bold]\n"
                f"  Provider: [cyan]{self.config_section}[/cyan]\n"
                f"  Model: [cyan]{self.model}[/cyan] "
                f"(Alias: {self.current_alias})\n"
                f"  Tools: {', '.join(self.active_tools) or 'None'}\n"
                f"  History: {len(self.conversation)} messages"
            )
            return True

        if cmd == 'help' or cmd == 'h':
            console.print(
                "[bold]Available Commands:[/bold]\n"
                "  /clear (c)     Clear conversation history\n"
                "  /quit (q)      Exit the application\n"
                "  /info (i)      Show session info\n"
                "  /models (m)    List available models (aliases)\n"
                "  /tools         Show active tools\n"
                "  /google        Switch to Google (Gemini)\n"
                "  /openai        Switch to OpenAI\n"
                "  /anthropic     Switch to Anthropic (Claude)\n"
                "  /xai           Switch to xAI (Grok)\n"
                f"  <model_alias>  Switch to specific model "
                f"(Available: {', '.join(self.available_models.keys())})"
            )
            return True

        return False

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
            fname = (
                f"output_image_{now_str}_{uuid.uuid4().hex[:4]}.{ext}"
            )
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
        if not self.request_debug_log_path:
            return
        try:
            import json
            import os
            path = Path(self.request_debug_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch(mode=0o600)
            os.chmod(path, 0o600)
            now = datetime.datetime.now()
            timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
            log_parts = []
            log_parts.append(f"=== DEBUG LOG ENTRY {timestamp} ===")
            log_parts.append(f"Provider: {self.config_section}")
            log_parts.append(f"Model: {self.model}")
            if response_obj:
                log_parts.append("\n--- Request ---")
                if hasattr(response_obj, 'request'):
                    log_parts.append(f"URL: {response_obj.request.url}")
                    log_parts.append("Headers:")
                    for k, v in response_obj.request.headers.items():
                        log_parts.append(f"  {k}: {v}")
                    log_parts.append("Body:")
                    if response_obj.request.body:
                        try:
                            if isinstance(response_obj.request.body, bytes):
                                b_dec = response_obj.request.body.decode(
                                    'utf-8'
                                )
                                body_str = b_dec
                            else:
                                body_str = str(response_obj.request.body)
                            parsed = json.loads(body_str)
                            log_parts.append(
                                json.dumps(
                                    parsed, indent=2, ensure_ascii=False
                                )
                            )
                        except Exception:
                            log_parts.append(str(response_obj.request.body))
                    else:
                        log_parts.append("(no body)")
                log_parts.append("\n--- Response ---")
                log_parts.append(f"Status: {response_obj.status_code}")
                log_parts.append("Headers:")
                for k, v in response_obj.headers.items():
                    log_parts.append(f"  {k}: {v}")
                log_parts.append("Body:")
                try:
                    parsed = response_obj.json()
                    log_parts.append(
                        json.dumps(parsed, indent=2, ensure_ascii=False)
                    )
                except Exception:
                    log_parts.append(response_obj.text)
            else:
                if request_payload:
                    log_parts.append("\n--- Request Payload ---")
                    if isinstance(request_payload, (dict, list)):
                        log_parts.append(
                            json.dumps(
                                request_payload, indent=2, ensure_ascii=False
                            )
                        )
                    else:
                        log_parts.append(str(request_payload))
                if response_content:
                    log_parts.append("\n--- Response Content ---")
                    if isinstance(response_content, (dict, list)):
                        log_parts.append(
                            json.dumps(
                                response_content, indent=2, ensure_ascii=False
                            )
                        )
                    else:
                        log_parts.append(str(response_content))
            log_parts.append("\n" + "="*80 + "\n")
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(log_parts))
            self._trim_log_file(path, self.max_debug_log_lines)
        except Exception as e:
            console.print(f"[dim red]Debug logging failed: {e}[/dim red]")

    def _report_error(self, provider_name: str, e: Exception):
        """Helper to report errors with detailed API response if available."""
        import requests
        error_msg = str(e)
        if (
            isinstance(e, requests.exceptions.HTTPError) and
            e.response is not None
        ):
            try:
                error_data = e.response.json()
                body_str = json.dumps(
                    error_data, indent=2, ensure_ascii=False
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
