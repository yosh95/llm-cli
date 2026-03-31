# llm_cli/clients/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from llm_cli.clients.config import config_manager
from llm_cli.clients.managers import MediaManager, SessionManager
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.ui import console, report_error, report_success


@dataclass
class ProviderSpec:
    """Configuration specific to an LLM provider."""

    api_key_name: str
    config_section: str
    pdf_as_base64: bool


class BaseLlmClient(ABC):
    """
    Abstract Base Class for LLM API clients.
    Refactored to hold its own state (Model, Conversation, Config)
    instead of delegating to numerous tiny managers.
    """

    def __init__(
        self,
        initial_model_alias: str,
        spec: ProviderSpec,
        stdout: bool = False,
        render_markdown: bool = True,
        initial_tools: list[str] | None = None,
        disable_system_prompt: bool = False,
        enable_mcp: bool = False,
        live_debug: bool = False,
    ):
        # 1. Identity & Config
        self.config_section: str = spec.config_section
        self._api_key_name: str = spec.api_key_name
        self.api_key: str | None = config_manager.get(self.config_section, self._api_key_name)
        self.stdout: bool = stdout
        self.render_markdown: bool = render_markdown
        self.preferred_pdf_as_base64: bool = spec.pdf_as_base64
        self.live_debug: bool = live_debug

        # 4. Tool & Helper State
        from llm_cli.modules.tool_registry import registry

        self.active_tools = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )
        self.tools_enabled: bool = True

        # 2. Model State
        self.model: str = ""
        self.current_alias: str = ""
        self.available_models: dict[str, Any] = {}
        self.model_config: dict[str, Any] = {}
        self._load_model_aliases()
        self._set_initial_model(initial_model_alias)

        # 3. Session State
        self.conversation: list[Message] = []
        self.system_prompt: str = ""
        self.system_prompt_enabled: bool = not disable_system_prompt
        self._refresh_system_prompt()

        self.media_manager = MediaManager(spec.pdf_as_base64)
        self.request_timeout: int | None = None
        self.max_chat_log_lines: int = 10000
        self.refresh_config()

        from llm_cli.consts import CHAT_LOG_PATH, HISTORY_LOG_PATH

        self.history_path = str(HISTORY_LOG_PATH)
        self.chat_log_path = str(CHAT_LOG_PATH)

        self.last_usage: dict[str, int] | None = None
        self.last_request_duration: float | None = None
        self._session: Any = None

        if enable_mcp:
            self._init_mcp(initial_tools is None)

    # --- Property-like methods simplified ---

    @property
    def pdf_as_base64(self) -> bool:
        return self.media_manager.pdf_as_base64

    @pdf_as_base64.setter
    def pdf_as_base64(self, value: bool) -> None:
        self.media_manager.pdf_as_base64 = value

    @property
    def slash_commands(self) -> set[str]:
        """Names and aliases of available slash commands."""
        from llm_cli.clients.command_dispatcher import registry

        return registry.all_names_and_aliases

    # --- Core Methods (Inlined from Managers) ---

    def _load_model_aliases(self) -> None:
        self.available_models = config_manager.get_model_aliases(self.config_section)
        if not self.available_models:
            console.print(
                f"[yellow]Warning: No models configured for {self.config_section}. "
                "Check config.toml.[/yellow]"
            )

    def set_model(self, alias: str) -> bool:
        if alias in self.available_models:
            self.current_alias = alias
            self.model_config = config_manager.get_model_config(self.config_section, alias)
            self.model = self.model_config.get("model", self.available_models[alias])
            # Load tools_enabled from config, default to True
            self.tools_enabled = self.model_config.get("tools", True)
            return True
        return False

    def set_custom_model(self, model_name: str) -> None:
        self.current_alias = "custom"
        self.model = model_name
        self.model_config = {}
        self.tools_enabled = True

    def refresh_config(self) -> None:
        """Refreshes configuration settings from config_manager."""
        raw_timeout = config_manager.get("general", "request_timeout")
        self.request_timeout = int(raw_timeout) if raw_timeout else None
        raw_max_lines = config_manager.get("general", "max_chat_log_lines")
        self.max_chat_log_lines = int(raw_max_lines) if raw_max_lines else 10000
        self._refresh_system_prompt()

    def _refresh_system_prompt(self) -> None:
        self.system_prompt = config_manager.get(self.config_section, "system_prompt") or ""

    def _init_mcp(self, update_active_tools: bool) -> None:
        try:
            from llm_cli.clients.mcp_manager import mcp_manager
            from llm_cli.modules.tool_registry import registry

            remote_tool_names = registry.register_remote_tools(mcp_manager)
            if remote_tool_names and update_active_tools:
                for tn in remote_tool_names:
                    if tn not in self.active_tools:
                        self.active_tools.append(tn)
        except Exception as e:
            console.print(f"[yellow]Note: MCP initialization failed: {e}[/yellow]")

    # --- Session Management (Helper based) ---

    def load_session(self, path_str: str) -> bool:
        conv, message = SessionManager.load_session(path_str)
        if conv is not None:
            self.conversation = conv
            report_success(message)
            return True
        report_error(message)
        return False

    def save_session(self, path_str: str) -> bool:
        success, message = SessionManager.save_session(path_str, self.conversation)
        if success:
            report_success(message)
        else:
            report_error(message)
        return success

    def clear_history(self) -> None:
        self.conversation.clear()

    def get_conversation_state(self) -> dict[str, Any]:
        return {"conversation": self.conversation[:]}

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        self.conversation = state.get("conversation", [])

    def get_last_user_prompt(self) -> str | None:
        for msg in reversed(self.conversation):
            if msg.role == Role.USER:
                texts = [p.text for p in msg.parts if isinstance(p, ContentPart) and p.text]
                texts += [p for p in msg.parts if isinstance(p, str)]
                if texts:
                    return "\n".join(texts)
        return None

    def get_last_tool_result(self) -> str | None:
        """Retrieves the result of the most recent tool execution from history."""
        # The current message (at the end of conversation) is typically the
        # Assistant's message containing the tool call being verified.
        # The message before it would be the previous tool result.
        if len(self.conversation) < 2:
            return None

        # Look back from the end for the most recent TOOL message
        for msg in reversed(self.conversation[:-1]):
            if msg.role == Role.TOOL:
                results = []
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        res = part.function_response.get("response", {}).get("result")
                        if res:
                            results.append(str(res))
                if results:
                    return "\n".join(results)
        return None

    def _update_history(self, data: list[DataSource], model_msg: Message) -> None:
        user_parts = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                inline = {"mimeType": d.content_type, "data": d.content}
                if "filename" in d.metadata:
                    inline["filename"] = d.metadata["filename"]
                user_parts.append(ContentPart(inline_data=inline))
        if user_parts:
            self.conversation.append(
                Message(role=Role.USER, parts=list(user_parts))  # type: ignore
            )
        self.conversation.append(model_msg)

    # --- Utility methods ---

    def _log_debug(self, response_obj: Any = None, request_payload: Any = None) -> None:
        """
        Logs detailed request and response data when live_debug is enabled.
        Uses Rich for pretty-printing JSON payloads.
        """
        if not self.live_debug:
            return

        import json

        from rich.rule import Rule
        from rich.syntax import Syntax

        if request_payload:
            payload_str = json.dumps(request_payload, indent=2, ensure_ascii=False)
            console.print(
                Rule(
                    "[bold magenta]DEBUG: Request Payload[/bold magenta]",
                    style="magenta",
                )
            )
            console.print(
                Syntax(
                    payload_str,
                    "json",
                    word_wrap=True,
                )
            )

        if response_obj is not None:
            try:
                # Show URL if available
                if hasattr(response_obj, "url"):
                    console.print(f"[magenta]URL:[/magenta] [dim]{response_obj.url}[/dim]")

                # Handle requests.Response objects
                if hasattr(response_obj, "json"):
                    res_json = response_obj.json()
                    res_str = json.dumps(res_json, indent=2, ensure_ascii=False)
                    console.print(Rule("[bold cyan]DEBUG: Response JSON[/bold cyan]", style="cyan"))
                    console.print(
                        Syntax(
                            res_str,
                            "json",
                            word_wrap=True,
                        )
                    )
                else:
                    # Fallback for other object types
                    res_str = str(response_obj)
                    console.print(Rule("[bold cyan]DEBUG: Response Data[/bold cyan]", style="cyan"))
                    console.print(res_str)
            except Exception as e:
                console.print(f"[dim red]Debug logging failed: {e}[/dim red]")
                if hasattr(response_obj, "text"):
                    console.print(Rule("[bold cyan]DEBUG: Raw Response[/bold cyan]", style="cyan"))
                    console.print(response_obj.text)

    def _set_initial_model(self, initial_model_alias: str) -> None:
        if not self.set_model(initial_model_alias):
            if initial_model_alias and initial_model_alias != "default":
                self.set_custom_model(initial_model_alias)
            else:
                self.set_model("default")

    def get_model_icon(self) -> str:
        icons = {
            "google": "[bold blue]GEMINI[/bold blue]",
            "gemini": "[bold blue]GEMINI[/bold blue]",
            "openai": "[bold green]OPENAI[/bold green]",
            "anthropic": "[bold yellow]ANTHROPIC[/bold yellow]",
            "claude": "[bold yellow]ANTHROPIC[/bold yellow]",
            "ollama": "[bold cyan]OLLAMA[/bold cyan]",
        }
        for k, v in icons.items():
            if k in self.config_section.lower():
                return v
        return "[bold magenta]LLM[/bold magenta]"

    def get_display_name(self) -> str:
        return f"{self.get_model_icon()} ({self.model})"

    def process_sources(self, sources: list[str]) -> None:
        data = [processed for s in sources if (processed := self._process_single_source(s))]
        has_prompt = any(not d.is_file_or_url for d in data)
        session = self.create_session()
        if data:
            if self.stdout or has_prompt:
                session.process_and_print(data)
                if not self.stdout:
                    session.run(sources=sources)
            else:
                session.run(initial_data=data, sources=sources)
        else:
            session.run(sources=sources)

    def _process_single_source(self, source: str) -> DataSource | None:
        """
        Processes a single source using MediaManager.
        Can be overridden by subclasses.
        """
        return self.media_manager.process_single_source(source)

    def create_session(self) -> Any:
        from llm_cli.clients.session import ChatSession

        return ChatSession(self)

    def talk(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        if not self.api_key and self.config_section not in ("ollama",):
            report_error(f"API key for '{self.config_section}' missing.")
            return
        if not self.model:
            report_error(f"No model for '{self.config_section}'. Check model aliases.")
            return
        self.create_session().run(initial_data, sources)

    def _build_prompt_from_history(self, data: list[DataSource]) -> str:
        """Collects all text from history and data into a single string."""
        prompt_parts: list[str] = []
        for msg in self.conversation:
            for part in msg.parts:
                if isinstance(part, ContentPart) and part.text:
                    prompt_parts.append(part.text)
                elif isinstance(part, str):
                    prompt_parts.append(part)
        for d in data:
            if d.content_type == "text/plain":
                prompt_parts.append(str(d.content))
        return "\n".join(prompt_parts)

    def _handle_image_generation_response(
        self,
        response_json: dict[str, Any],
        full_prompt: str,
        original_data: list[DataSource],
        provider_name: str,
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Common logic to handle image generation response."""
        try:
            data_item = response_json["data"][0]
            revised_prompt = data_item.get("revised_prompt", "")
            img_data = None
            mime_type = "image/png"

            if "b64_json" in data_item:
                img_data = data_item["b64_json"]
            elif "url" in data_item:
                from llm_cli.modules.media_utils import fetch_url_content

                img_data, fetched_mime = fetch_url_content(data_item["url"])
                if fetched_mime:
                    mime_type = fetched_mime

            if not img_data:
                return ("Failed to retrieve image data.", ""), None

            display_text, _ = self._save_inline_media_and_get_log_entry(
                {"mimeType": mime_type, "data": img_data}, hint_text=full_prompt[:100]
            )
            if not display_text:
                display_text = "Generated image, but failed to save it locally."
            if revised_prompt:
                display_text += f"\n**Revised Prompt:** {revised_prompt}"

            model_msg = Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(text=display_text),
                    ContentPart(inline_data={"mimeType": mime_type, "data": img_data}),
                ],
            )
            self._update_history(original_data, model_msg)
            return (display_text.strip(), ""), None
        except Exception as e:
            self._report_error(f"{provider_name} Image processing", e)
            return (None, None), None

    def _trim_log_file(self, path: Path, max_lines: int) -> None:
        try:
            if not path.exists():
                return
            with path.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with path.open("w", encoding="utf-8", errors="replace") as f:
                    f.writelines(lines[-max_lines:])
        except Exception as e:
            console.print(f"[dim red]Log trimming failed: {e}[/dim red]")

    @abstractmethod
    def _send(self, data: list[DataSource]) -> tuple[tuple[str | None, str | None], dict | None]:

        pass

    @abstractmethod
    def utility_send(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        """
        Sends a single-turn, stateless request to the LLM.
        Used for background tasks like dual-LLM verification.
        """
        pass

    # --- Direct API Helpers ---
    def _post(
        self, url: str, headers: dict, json_data: dict, timeout: int | None = None
    ) -> requests.Response:
        res = requests.post(
            url,
            headers=headers,
            json=json_data,
            timeout=timeout or self.request_timeout,
        )
        self._log_debug(response_obj=res, request_payload=json_data)
        return res

    def _get(
        self, url: str, headers: dict | None = None, timeout: int | None = None
    ) -> requests.Response:
        res = requests.get(url, headers=headers or {}, timeout=timeout or self.request_timeout)
        self._log_debug(response_obj=res)
        return res

    # (Internal helpers like _has_pending_tool_calls, _handle_command etc.)
    def _has_pending_tool_calls(self) -> bool:
        if not self.conversation or self.conversation[-1].role != Role.MODEL:
            return False
        return any(
            part.function_call
            for part in self.conversation[-1].parts
            if isinstance(part, ContentPart)
        )

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        from llm_cli.clients.command_dispatcher import handle_command

        return handle_command(self, user_input, sources, pending_data)

    def _report_error(self, provider: str, e: Exception) -> None:
        import json

        error_msg = str(e)
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
            try:
                error_msg += f"\nResponse: {json.dumps(e.response.json(), indent=2)}"
            except Exception:
                if e.response.text:
                    error_msg += f"\nResponse: {e.response.text}"
        console.print(f"[bold red][{provider} ERROR] {error_msg}[/bold red]")

    def _save_inline_media_and_get_log_entry(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        return self.media_manager.save_inline_media(inline_data, hint_text)
