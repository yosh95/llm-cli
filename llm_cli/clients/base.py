# llm_cli/clients/base.py

import copy
import datetime
import json
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import fetch_url_content, process_file
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

console = Console()


class BaseLlmClient(ABC):
    """
    Abstract Base Class for LLM API clients.

    This class defines the interface and common logic for interacting with various
    LLM providers (OpenAI, Anthropic, Gemini, etc.).

    Attributes:
        config_section (str): The section name in the config file.
        api_key (str): The API key for the provider.
        pdf_as_base64 (bool): Whether to send PDFs as base64 or extract text.
        stdout (bool): Whether to output to stdout (non-interactive).
        render_markdown (bool): Whether to render markdown in the console.
        live_debug (bool): Whether to show debug information during generation.
        tools_enabled (bool): Whether tool calling is enabled.
        reasoning_enabled (bool): Whether "thinking/reasoning" mode is enabled.
        system_prompt (str): The system prompt text.
        system_prompt_enabled (bool): Whether the system prompt is active.
        available_models (Dict[str, str]): Map of aliases to model strings.
        current_alias (str): The currently active model alias.
        model (str): The currently active model string.
        conversation (List[Message]): The message history.
        active_tools (List[str]): List of enabled tool names.
    """

    def __init__(
        self,
        initial_model_alias: str,
        api_key_name: str,
        config_section: str,
        pdf_as_base64: bool,
        stdout: bool,
        render_markdown: bool = True,
        initial_tools: list[str] | None = None,
        disable_system_prompt: bool = False,
        enable_mcp: bool = False,
        live_debug: bool = False,
    ):
        """Initializes the LLM client with configuration and state."""
        self._slash_commands = {
            "attach",
            "save",
            "load",
            "dump",
            "raw",
            "view",
            "v",
            "clear",
            "c",
            "quit",
            "q",
            "info",
            "i",
            "debug",
            "d",
            "model",
            "m",
            "provider",
            "p",
            "template",
            "t",
            "checkpoint",
            "cp",
            "reload",
            "tools",
            "help",
            "h",
        }
        self.config_section = config_section
        self._api_key_name = api_key_name  # Store for reloads
        self._disable_system_prompt = disable_system_prompt
        self.api_key = get_setting(api_key_name, config_section)
        self.pdf_as_base64 = pdf_as_base64
        self.stdout = stdout
        self.render_markdown = render_markdown
        self.live_debug = live_debug

        self.tools_enabled = True

        # Load model and its specific configuration
        self.available_models: dict[str, Any] = {}
        self.current_alias = ""
        self.model = ""

        self._load_model_aliases()
        if not self.set_model(initial_model_alias):
            if initial_model_alias and initial_model_alias != "default":
                self.set_custom_model(initial_model_alias)
            else:
                self.set_model("default")

        self._refresh_general_settings()
        self._refresh_system_prompt()

        self.conversation: list[Message] = []
        self.last_usage: dict[str, int] | None = None
        self.cumulative_total_tokens = 0
        self.last_request_duration: float | None = None

        from llm_cli.consts import CHAT_LOG_PATH, HISTORY_LOG_PATH

        self.history_path = str(HISTORY_LOG_PATH)
        self.chat_log_path = str(CHAT_LOG_PATH)

        self.active_tools: list[str] = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )

        if enable_mcp:
            self._init_mcp(initial_tools is None)

    def _refresh_general_settings(self) -> None:
        """Reloads settings that can change at runtime."""
        raw_timeout = get_setting("request_timeout", "general")
        self.request_timeout = int(raw_timeout) if raw_timeout else None

        self.max_chat_log_lines = int(
            get_setting("max_chat_log_lines", "general") or 10000
        )

    def _refresh_system_prompt(self) -> None:
        """Constructs or refreshes the system prompt."""
        raw_prompt = get_setting("system_prompt", self.config_section) or ""
        disable_date_prompt = get_setting("disable_date_prompt", self.config_section)

        self.system_prompt = ""
        if not disable_date_prompt:
            now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d (%A)")
            self.system_prompt = f"Current date: {now}"

        if raw_prompt:
            if self.system_prompt:
                self.system_prompt += "\n"
            self.system_prompt += raw_prompt

        if self._disable_system_prompt:
            self.system_prompt_enabled = False
        else:
            self.system_prompt_enabled = True

    def _init_mcp(self, update_active_tools: bool) -> None:
        """Initializes Model Context Protocol (MCP) tools."""
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
            console.print(f"[yellow]Note: MCP initialization failed: {e}[/yellow]")

    def _expand(self, p: str | None) -> str | None:
        """Expands user path symbols."""
        return str(Path(p).expanduser()) if p else None

    @abstractmethod
    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        pass

    @abstractmethod
    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """
        Sends the request to the specific provider API.

        Args:
            data: A list of DataSource objects containing the user's latest input.

        Returns:
            A tuple of ((response_text, thought_text), usage_dict).
        """
        pass

    def _post(
        self,
        url: str,
        headers: dict,
        json_data: dict,
        timeout: int | None = None,
    ) -> requests.Response:
        """
        Performs a POST request.

        Args:
            url: The endpoint URL.
            headers: HTTP headers.
            json_data: The JSON payload.
            timeout: Request timeout in seconds (None for no timeout).

        Returns:
            The successful requests.Response object.
        """
        if headers is None:
            headers = {}

        return requests.post(url, headers=headers, json=json_data, timeout=timeout)

    def _get(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        """
        Performs a GET request.

        Args:
            url: The endpoint URL.
            headers: HTTP headers.
            timeout: Request timeout in seconds.

        Returns:
            The requests.Response object.
        """
        if headers is None:
            headers = {}

        return requests.get(url, headers=headers, timeout=timeout)

    @property
    def slash_commands(self) -> set[str]:
        """Dynamic slash commands for completer."""
        return self._slash_commands

    def set_model(self, alias: str) -> bool:
        """
        Sets the active model and its configuration using its alias.

        Args:
            alias: The model alias defined in config.

        Returns:
            True if the model was successfully set, False otherwise.
        """
        if alias in self.available_models:
            self.current_alias = alias
            self.model = self.available_models[alias]

            # Load additional settings for this specific alias/model
            # config = get_model_config(self.config_section, alias)
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
        if not self.api_key and self.config_section not in ("ollama", "mamba"):
            console.print(
                f"[bold red]Error: API key for '{self.config_section}' "
                "is missing.[/bold red]\n"
                "Please run [cyan]llm-cli-config[/cyan] to set it up."
            )
            return

        if not self.model:
            console.print(
                f"[bold red]Error: No model is configured for "
                f"'{self.config_section}'.[/bold red]\n"
                "Please run [cyan]llm-cli-config[/cyan] to define model aliases."
            )
            return

        from llm_cli.clients.session import ChatSession

        ChatSession(self).run(initial_data, sources)

    def process_sources(self, sources: list[str]) -> None:
        """Processes a list of input sources (files, URLs, text)."""
        data = [
            processed for s in sources if (processed := self._process_single_source(s))
        ]
        has_prompt = any(not d.is_file_or_url for d in data)

        from llm_cli.clients.session import ChatSession

        session = ChatSession(self)

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
        """Processes a single source string into a DataSource object."""
        if source.startswith("http"):
            content, ctype = fetch_url_content(source, self.pdf_as_base64)
            if content:
                # Try to extract filename from URL
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
            res_dict = process_file(path, self.pdf_as_base64)
            if res_dict:
                return DataSource(
                    content=res_dict["content"],
                    content_type=res_dict["content_type"],
                    is_file_or_url=True,
                    metadata={"filename": res_dict.get("filename", path.name)},
                )
            return None

        return DataSource(content=source, content_type="text/plain")

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
        try:
            load_path = Path(path_str)
            if not load_path.exists():
                console.print(f"[red]File not found: {load_path}[/red]")
                return False

            with load_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Convert list of dicts back to list of Message objects
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
            console.print(
                f"[green]Session loaded from {load_path} "
                f"({len(self.conversation)} messages)[/green]"
            )
            return True
        except Exception as e:
            console.print(f"[red]Failed to load session: {e}[/red]")
            return False

    def clear_history(self) -> None:
        """Clears the conversation history and resets token count."""
        self.conversation.clear()
        self.cumulative_total_tokens = 0

    def get_conversation_state(self) -> dict[str, Any]:
        """
        Returns the current state of the conversation.
        Override this to include provider-specific state (like interaction IDs).
        """
        return {
            "conversation": copy.deepcopy(self.conversation),
            "cumulative_total_tokens": self.cumulative_total_tokens,
        }

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        """
        Restores the conversation state from a dictionary.
        """
        self.conversation = state["conversation"]
        self.cumulative_total_tokens = state.get("cumulative_total_tokens", 0)

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

    def _trim_log_file(self, path: Path, max_lines: int) -> None:
        from llm_cli.clients.base_helpers import trim_log_file

        trim_log_file(console, path, max_lines)

    def _save_inline_media_and_get_log_entry(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        """
        Saves inline media data (base64) to a file and returns a tuple of
        (formatted display string, saved file path).
        Supports images and audio.
        """
        from llm_cli.clients.base_helpers import save_inline_media_and_get_log_entry

        return save_inline_media_and_get_log_entry(self, inline_data, hint_text)

    def _log_debug(
        self,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ) -> None:
        from llm_cli.clients.base_helpers import log_debug

        log_debug(self, response_obj, request_payload, response_content)

    def _print_live_debug(
        self,
        timestamp: str,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ) -> None:
        from llm_cli.clients.base_helpers import print_live_debug

        print_live_debug(timestamp, response_obj, request_payload, response_content)

    def _report_error(self, provider_name: str, e: Exception) -> None:
        from llm_cli.clients.base_helpers import report_error

        report_error(provider_name, e)

    def get_model_icon(self) -> str:
        """Get an appropriate icon for the current model provider."""
        provider = self.config_section.lower()
        if "google" in provider or "gemini" in provider:
            return "✨"
        if "openai" in provider:
            return "🤖"
        if "anthropic" in provider or "claude" in provider:
            return "🌿"
        if "xai" in provider or "grok" in provider:
            return "🌌"
        if "ollama" in provider:
            return "🦙"
        return "💡"

    def get_display_name(self) -> str:
        """Get the formatted display name including icon and model path."""
        icon = self.get_model_icon()
        return f"{icon} ({self.model})"

    def _format_response_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        display_name = self.get_display_name()
        return f"**{display_name}:**  \n{text.strip()}"
