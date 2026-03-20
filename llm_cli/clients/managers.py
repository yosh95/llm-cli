# llm_cli/clients/managers.py

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from llm_cli.clients.config import config_manager
from llm_cli.modules.models import ContentPart, DataSource, Message, Role

if TYPE_CHECKING:
    pass

console = Console()


class ProviderConfigManager:
    """Manages provider-specific and general configuration settings."""

    def __init__(self, section: str, disable_system_prompt: bool = False):
        self.section = section
        self._disable_system_prompt = disable_system_prompt
        self.request_timeout: int | None = None
        self.max_chat_log_lines: int = 10000
        self.system_prompt: str = ""
        self.system_prompt_enabled: bool = not disable_system_prompt

        self.refresh()

    def refresh(self) -> None:
        """Reloads settings that can change at runtime."""
        self._refresh_general_settings()
        self._refresh_system_prompt()

    def _refresh_general_settings(self) -> None:
        raw_timeout = config_manager.get("general", "request_timeout")
        try:
            self.request_timeout = int(raw_timeout) if raw_timeout else None
        except (ValueError, TypeError):
            self.request_timeout = None

        raw_max_lines = config_manager.get("general", "max_chat_log_lines")
        try:
            self.max_chat_log_lines = int(raw_max_lines) if raw_max_lines else 10000
        except (ValueError, TypeError):
            self.max_chat_log_lines = 10000

    def _refresh_system_prompt(self) -> None:
        raw_prompt = config_manager.get(self.section, "system_prompt") or ""
        disable_date_prompt = config_manager.get(self.section, "disable_date_prompt")

        self.system_prompt = ""
        if not disable_date_prompt:
            now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d (%A)")
            self.system_prompt = f"Current date: {now}"

        if raw_prompt:
            if self.system_prompt:
                self.system_prompt += "\n"
            self.system_prompt += raw_prompt

        self.system_prompt_enabled = not self._disable_system_prompt


class ModelManager:
    """Manages model selection, aliases, and provider-specific display info."""

    def __init__(self, section: str):
        self.section = section
        self.available_models: dict[str, Any] = {}
        self.current_alias: str = ""
        self.model: str = ""
        self.model_config: dict[str, Any] = {}
        self.load_model_aliases()

    def load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        self.available_models = config_manager.get_model_aliases(self.section)
        if not self.available_models:
            console.print(
                f"[yellow]Warning: No models configured for {self.section}. "
                "Check config.toml.[/yellow]"
            )

    def set_model(self, alias: str) -> bool:
        """Sets the active model and its configuration using its alias."""
        if alias in self.available_models:
            self.current_alias = alias
            self.model_config = config_manager.get_model_config(self.section, alias)
            self.model = self.model_config.get("model", self.available_models[alias])
            return True
        return False

    def set_custom_model(self, model_name: str) -> None:
        """Sets a custom model that is not in the configuration."""
        self.current_alias = "custom"
        self.model = model_name
        self.model_config = {}

    def get_model_icon(self) -> str:
        """Returns an appropriate icon for the current provider."""
        provider = self.section.lower()
        icons = {
            "google": "✨",
            "gemini": "✨",
            "openai": "🤖",
            "anthropic": "🌿",
            "claude": "🌿",
            "xai": "🌌",
            "grok": "🌌",
            "ollama": "🦙",
        }
        for k, v in icons.items():
            if k in provider:
                return v
        return "💡"

    def get_display_name(self) -> str:
        """Returns the formatted display name including icon and model name."""
        return f"{self.get_model_icon()} ({self.model})"


class SessionManager:
    """Manages conversation history and session persistence."""

    def __init__(self) -> None:
        self.conversation: list[Message] = []

    def clear_history(self) -> None:
        """Clears the current conversation history."""
        self.conversation.clear()

    def update_history(self, data: list[DataSource], model_msg: Message) -> None:
        """Converts input data to USER messages and appends MODEL message."""
        user_parts: list[str | ContentPart] = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                inline_data = {"mimeType": d.content_type, "data": d.content}
                if "filename" in d.metadata:
                    inline_data["filename"] = d.metadata["filename"]
                user_parts.append(ContentPart(inline_data=inline_data))

        if user_parts:
            self.conversation.append(Message(role=Role.USER, parts=user_parts))
        self.conversation.append(model_msg)

    def load_session(self, path_str: str) -> tuple[bool, str]:
        """Loads a conversation session from a JSON file."""
        try:
            load_path = Path(path_str)
            if not load_path.exists():
                return False, f"File not found: {load_path}"

            with load_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            loaded_conversation = []
            for msg_data in data:
                role = Role(msg_data["role"])
                parts: list[str | ContentPart] = []
                for p in msg_data["parts"]:
                    if isinstance(p, str):
                        parts.append(p)
                    elif isinstance(p, dict):
                        parts.append(ContentPart(**p))
                loaded_conversation.append(Message(role=role, parts=parts))

            self.clear_history()
            self.conversation = loaded_conversation
            msg = f"Session loaded from {load_path} ({len(self.conversation)} messages)"
            return True, msg
        except Exception as e:
            return False, f"Failed to load session: {e}"

    def save_session(self, path_str: str) -> tuple[bool, str]:
        """Saves the current conversation to a JSON file."""
        try:
            save_path = Path(path_str)
            save_path.parent.mkdir(parents=True, exist_ok=True)

            serializable_conversation = []
            for msg in self.conversation:
                msg_dict: dict[str, Any] = {"role": str(msg.role), "parts": []}
                for part in msg.parts:
                    if isinstance(part, str):
                        msg_dict["parts"].append(part)
                    else:
                        import dataclasses

                        p_dict = dataclasses.asdict(part)
                        clean_part = {k: v for k, v in p_dict.items() if v is not None}
                        msg_dict["parts"].append(clean_part)
                serializable_conversation.append(msg_dict)

            with save_path.open("w", encoding="utf-8") as f:
                json.dump(serializable_conversation, f, indent=2, ensure_ascii=False)

            return True, f"Session saved to {save_path}"
        except Exception as e:
            return False, f"Failed to save session: {e}"

    def get_state(self) -> dict[str, Any]:
        """Returns the serializable state of the conversation."""
        import copy

        return {
            "conversation": copy.deepcopy(self.conversation),
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Restores the conversation state from a dictionary."""
        self.conversation = state.get("conversation", [])

    def get_last_user_prompt(self) -> str | None:
        """Retrieves the most recent user prompt from history."""
        for msg in reversed(self.conversation):
            if msg.role == Role.USER:
                texts = [
                    p.text for p in msg.parts if isinstance(p, ContentPart) and p.text
                ]
                texts += [p for p in msg.parts if isinstance(p, str)]
                if texts:
                    return "\n".join(texts)
        return None


class ToolManager:
    """Manages tool registration, MCP integration, and state."""

    def __init__(self, initial_tools: list[str] | None = None):
        from llm_cli.modules.tool_registry import registry

        self.active_tools: list[str] = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )
        self.tools_enabled: bool = True

    def init_mcp(self, update_active_tools: bool) -> None:
        """Initializes Model Context Protocol (MCP) tools."""
        try:
            from llm_cli.clients.mcp_manager import mcp_manager
            from llm_cli.modules.tool_registry import registry

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
            console.print(f"[yellow]Note: MCP initialization failed: {e}[/yellow]")

    def get_responded_tool_ids(self, conversation: list[Message]) -> set[str]:
        """Returns tool IDs that have responses in history."""
        responded: set[str] = set()
        for msg in conversation:
            if msg.role == Role.TOOL:
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        tool_id = part.function_response.get("id")
                        if tool_id and tool_id != "unknown":
                            responded.add(tool_id)
        return responded


class MediaManager:
    """Handles processing of media sources (files, URLs, etc.)."""

    def __init__(self, pdf_as_base64: bool = False):
        self.pdf_as_base64 = pdf_as_base64

    def process_sources(self, sources: list[str]) -> list[DataSource]:
        """Processes a list of input sources into DataSources."""
        return [
            processed for s in sources if (processed := self.process_single_source(s))
        ]

    def process_single_source(self, source: str) -> DataSource | None:
        """Processes a single source string into a DataSource object."""
        import urllib.parse

        from llm_cli.modules import media_utils

        if source.startswith("http"):
            content, ctype = media_utils.fetch_url_content(source, self.pdf_as_base64)
            if content:
                parsed_url = urllib.parse.urlparse(source)
                filename = Path(parsed_url.path).name or "downloaded_file"
                return DataSource(
                    content=content,
                    content_type=ctype or "application/octet-stream",
                    is_file_or_url=True,
                    metadata={"filename": filename},
                )
            return None

        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            res_dict = media_utils.process_file(path, self.pdf_as_base64)
            if res_dict:
                return DataSource(
                    content=res_dict["content"],
                    content_type=res_dict["content_type"],
                    is_file_or_url=True,
                    metadata={"filename": res_dict.get("filename", path.name)},
                )
            return None

        return DataSource(content=source, content_type="text/plain")

    def save_inline_media(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        """Saves generated media (images, audio, video) to disk."""
        from llm_cli.clients import base_helpers

        # Dummy client-like object for base_helpers
        class _Proxy:
            def _expand(self, p: str | None) -> str | None:
                return str(Path(p).expanduser()) if p else None

        return base_helpers.save_inline_media_and_get_log_entry(
            _Proxy(),
            inline_data,
            hint_text,  # type: ignore
        )


class LoggingManager:
    """Handles logging, debug display, and error reporting."""

    def __init__(self, live_debug: bool = False):
        self.live_debug = live_debug

    def log_debug(
        self,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ) -> None:
        if not self.live_debug:
            return

        from llm_cli.clients import base_helpers

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            base_helpers.print_live_debug(
                timestamp, response_obj, request_payload, response_content
            )
        except Exception as e:
            console.print(f"[dim red]Live debug display failed: {e}[/dim red]")

    def report_error(self, provider_name: str, e: Exception) -> None:
        from llm_cli.clients import base_helpers

        base_helpers.report_error(provider_name, e)

    def trim_log_file(self, path: Path, max_lines: int) -> None:
        from llm_cli.clients import base_helpers

        base_helpers.trim_log_file(console, path, max_lines)
