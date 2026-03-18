# llm_cli/clients/base.py

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from llm_cli.clients import config as _config
from llm_cli.clients.command_handler import SUPPORTED_COMMANDS
from llm_cli.clients.mixins import ConfigMixin, LoggingMixin, MediaMixin
from llm_cli.clients.session_manager import SessionManager
from llm_cli.modules import media_utils as _media_utils
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

console = Console()


# Proxy functions to support tests that patch llm_cli.clients.base
# and those that patch the underlying modules.
def get_setting(key: str, section: str | None = None) -> Any:
    return _config.get_setting(key, section or "general")


def get_model_aliases(section: str) -> dict[str, str]:
    return _config.get_model_aliases(section)


def get_model_config(section: str, alias: str) -> dict[str, Any]:
    return _config.get_model_config(section, alias)


def fetch_url_content(
    url: str, pdf_as_base64: bool = False
) -> tuple[bytes | str | None, str | None]:
    return _media_utils.fetch_url_content(url, pdf_as_base64)


def process_file(path: Path, pdf_as_base64: bool = False) -> dict[str, Any] | None:
    return _media_utils.process_file(path, pdf_as_base64)


class BaseLlmClient(ABC, ConfigMixin, MediaMixin, LoggingMixin):
    """
    Abstract Base Class for LLM API clients.

    This class defines the interface and common logic for interacting with various
    LLM providers (OpenAI, Anthropic, Gemini, etc.).
    """

    def __init__(
        self,
        initial_model_alias: str,
        api_key_name: str,
        config_section: str,
        pdf_as_base64: bool,
        stdout: bool = False,
        render_markdown: bool = True,
        initial_tools: list[str] | None = None,
        disable_system_prompt: bool = False,
        enable_mcp: bool = False,
        live_debug: bool = False,
    ):
        """Initializes the LLM client with configuration and state."""
        self._slash_commands = SUPPORTED_COMMANDS
        self.config_section = config_section
        self._api_key_name = api_key_name
        self._disable_system_prompt = disable_system_prompt
        self.api_key = get_setting(api_key_name, config_section)
        self.pdf_as_base64 = pdf_as_base64
        self.stdout = stdout
        self.render_markdown = render_markdown
        self.live_debug = live_debug
        self.tools_enabled = True

        self.available_models: dict[str, Any] = {}
        self.current_alias = ""
        self.model = ""
        self.model_config: dict[str, Any] = {}

        self._load_model_aliases()
        self._set_initial_model(initial_model_alias)
        self._refresh_general_settings()
        self._refresh_system_prompt()

        self._session_manager = SessionManager()
        self.last_usage: dict[str, int] | None = None
        self.last_request_duration: float | None = None

        from llm_cli.consts import CHAT_LOG_PATH, HISTORY_LOG_PATH

        self.history_path = str(HISTORY_LOG_PATH)
        self.chat_log_path = str(CHAT_LOG_PATH)

        self.active_tools: list[str] = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )
        self._session: Any = None

        if enable_mcp:
            self._init_mcp(initial_tools is None)

    @property
    def conversation(self) -> list[Message]:
        """Accessor for conversation history managed by SessionManager."""
        return self._session_manager.conversation

    @conversation.setter
    def conversation(self, value: list[Message]) -> None:
        """Setter for conversation history."""
        self._session_manager.conversation = value

    def _init_mcp(self, update_active_tools: bool) -> None:
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

    def _set_initial_model(self, initial_model_alias: str) -> None:
        """Sets the starting model for the client."""
        if not self.set_model(initial_model_alias):
            if initial_model_alias and initial_model_alias != "default":
                self.set_custom_model(initial_model_alias)
            else:
                self.set_model("default")

    def _update_history(self, data: list[DataSource], model_msg: Message) -> None:
        """Standard history update for most clients."""
        self._session_manager.update_history(data, model_msg)

    def _get_responded_tool_ids(self) -> set[str]:
        """Returns tool IDs that have responses in history."""
        responded: set[str] = set()
        for msg in self.conversation:
            if msg.role == Role.TOOL:
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        tool_id = part.function_response.get("id")
                        if tool_id and tool_id != "unknown":
                            responded.add(tool_id)
        return responded

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
            else:
                prompt_parts.append(f"[Attached {d.content_type}]")
        return "\n".join(prompt_parts)

    @abstractmethod
    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Sends the request to the specific provider API."""
        pass

    def _post(
        self, url: str, headers: dict, json_data: dict, timeout: int | None = None
    ) -> requests.Response:
        return requests.post(url, headers=headers, json=json_data, timeout=timeout)

    def _get(
        self, url: str, headers: dict | None = None, timeout: int | None = None
    ) -> requests.Response:
        return requests.get(url, headers=headers or {}, timeout=timeout)

    @property
    def slash_commands(self) -> set[str]:
        """Dynamic slash commands for completer."""
        return self._slash_commands

    def set_model(self, alias: str) -> bool:
        """Sets the active model and its configuration using its alias."""
        if alias in self.available_models:
            self.current_alias = alias
            self.model_config = get_model_config(self.config_section, alias)
            self.model = self.model_config.get("model", self.available_models[alias])
            return True
        return False

    def set_custom_model(self, model_name: str) -> None:
        """Sets a custom model that is not in the configuration."""
        self.current_alias = "custom"
        self.model = model_name

    def talk(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        """Starts an interactive chat session."""
        if not self.api_key and self.config_section not in ("ollama",):
            console.print(
                f"[bold red]Error: API key for '{self.config_section}' "
                "missing.[/bold red]\n"
                "Please run [cyan]llm-cli-config[/cyan] to set it up."
            )
            return

        if not self.model:
            console.print(
                f"[bold red]Error: No model for '{self.config_section}'."
                "[/bold red]\n"
                "Please run [cyan]llm-cli-config[/cyan] to define model aliases."
            )
            return

        from llm_cli.clients.session import ChatSession

        ChatSession(self).run(initial_data, sources)

    def _has_pending_tool_calls(self) -> bool:
        """Checks if the last model response contains tool calls."""
        if not self.conversation or self.conversation[-1].role != Role.MODEL:
            return False
        for part in self.conversation[-1].parts:
            if isinstance(part, ContentPart) and part.function_call:
                return True
        return False

    def load_session(self, path_str: str) -> bool:
        """Loads a conversation session from a JSON file."""
        success, message = self._session_manager.load_session(path_str)
        color = "green" if success else "red"
        console.print(f"[{color}]{message}[/{color}]")
        return success

    def save_session(self, path_str: str) -> bool:
        """Saves a conversation session to a JSON file."""
        success, message = self._session_manager.save_session(path_str)
        color = "green" if success else "red"
        console.print(f"[{color}]{message}[/{color}]")
        return success

    def clear_history(self) -> None:
        """Clears the conversation history."""
        self._session_manager.clear_history()

    def get_conversation_state(self) -> dict[str, Any]:
        """Returns the current state of the conversation."""
        return self._session_manager.get_state()

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        """Restores the conversation state from a dictionary."""
        self._session_manager.set_state(state)

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        """Handles in-chat slash commands."""
        from llm_cli.clients.command_handler import handle_command

        return handle_command(self, user_input, sources, pending_data)

    def _print_help(self) -> None:
        from llm_cli.clients.command_handler import print_help

        print_help()

    def _save_inline_media_and_get_log_entry(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        from llm_cli.clients.base_helpers import save_inline_media_and_get_log_entry

        return save_inline_media_and_get_log_entry(self, inline_data, hint_text)

    def get_model_icon(self) -> str:
        """Get an appropriate icon for the current model provider."""
        provider = self.config_section.lower()
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
        """Get the formatted display name including icon and model name."""
        return f"{self.get_model_icon()} ({self.model})"

    def _format_response_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        return f"**{self.get_display_name()}:**  \n{text.strip()}"
