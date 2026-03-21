# llm_cli/clients/base.py

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from llm_cli.clients.config import config_manager
from llm_cli.clients.managers import (
    LoggingManager,
    MediaManager,
    ModelManager,
    ProviderConfigManager,
    SessionManager,
    ToolManager,
)
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.ui import console


@dataclass
class ProviderSpec:
    """Configuration specific to an LLM provider."""

    api_key_name: str
    config_section: str
    pdf_as_base64: bool


class BaseLlmClient(ABC):
    """
    Abstract Base Class for LLM API clients.

    This class defines the interface and delegates responsibilities to
    specialized manager classes for configuration, models, sessions,
    tools, media, and logging.
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
        provider_config_manager: ProviderConfigManager | None = None,
        model_manager: ModelManager | None = None,
        session_manager: SessionManager | None = None,
        tool_manager: ToolManager | None = None,
        media_manager: MediaManager | None = None,
        logging_manager: LoggingManager | None = None,
    ):
        """Initializes the LLM client by setting up its managers."""
        self.config_section = spec.config_section
        self._api_key_name = spec.api_key_name
        self.stdout = stdout
        self.render_markdown = render_markdown
        self.preferred_pdf_as_base64 = spec.pdf_as_base64

        # Specialized Managers (Injected or Newly Created)
        self._config_manager = provider_config_manager or ProviderConfigManager(
            self.config_section, disable_system_prompt
        )
        self._model_manager = model_manager or ModelManager(self.config_section)
        self._session_manager = session_manager or SessionManager()
        self._tool_manager = tool_manager or ToolManager(initial_tools)
        self._media_manager = media_manager or MediaManager(spec.pdf_as_base64)
        self._logging_manager = logging_manager or LoggingManager(live_debug)

        # Initial Setup
        self.api_key = config_manager.get(self.config_section, self._api_key_name)
        self._set_initial_model(initial_model_alias)

        from llm_cli.consts import CHAT_LOG_PATH, HISTORY_LOG_PATH

        self.history_path = str(HISTORY_LOG_PATH)
        self.chat_log_path = str(CHAT_LOG_PATH)

        self.last_usage: dict[str, int] | None = None
        self.last_request_duration: float | None = None
        self._session: Any = None

        if enable_mcp:
            self._tool_manager.init_mcp(initial_tools is None)

    # --- Property Delegation to Managers ---

    @property
    def model(self) -> str:
        return self._model_manager.model

    @model.setter
    def model(self, value: str) -> None:
        self._model_manager.model = value

    @property
    def model_config(self) -> dict[str, Any]:
        return self._model_manager.model_config

    @model_config.setter
    def model_config(self, value: dict[str, Any]) -> None:
        self._model_manager.model_config = value

    @property
    def available_models(self) -> dict[str, Any]:
        return self._model_manager.available_models

    @available_models.setter
    def available_models(self, value: dict[str, Any]) -> None:
        self._model_manager.available_models = value

    @property
    def current_alias(self) -> str:
        return self._model_manager.current_alias

    @current_alias.setter
    def current_alias(self, value: str) -> None:
        self._model_manager.current_alias = value

    @property
    def conversation(self) -> list[Message]:
        return self._session_manager.conversation

    @conversation.setter
    def conversation(self, value: list[Message]) -> None:
        self._session_manager.conversation = value

    @property
    def active_tools(self) -> list[str]:
        return self._tool_manager.active_tools

    @active_tools.setter
    def active_tools(self, value: list[str]) -> None:
        self._tool_manager.active_tools = value

    @property
    def tools_enabled(self) -> bool:
        return self._tool_manager.tools_enabled

    @tools_enabled.setter
    def tools_enabled(self, value: bool) -> None:
        self._tool_manager.tools_enabled = value

    @property
    def system_prompt(self) -> str:
        return self._config_manager.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._config_manager.system_prompt = value

    @property
    def system_prompt_enabled(self) -> bool:
        return self._config_manager.system_prompt_enabled

    @system_prompt_enabled.setter
    def system_prompt_enabled(self, value: bool) -> None:
        self._config_manager.system_prompt_enabled = value

    @property
    def request_timeout(self) -> int | None:
        return self._config_manager.request_timeout

    @request_timeout.setter
    def request_timeout(self, value: int | None) -> None:
        self._config_manager.request_timeout = value

    @property
    def max_chat_log_lines(self) -> int:
        return self._config_manager.max_chat_log_lines

    @max_chat_log_lines.setter
    def max_chat_log_lines(self, value: int) -> None:
        self._config_manager.max_chat_log_lines = value

    @property
    def live_debug(self) -> bool:
        return self._logging_manager.live_debug

    @live_debug.setter
    def live_debug(self, value: bool) -> None:
        self._logging_manager.live_debug = value

    @property
    def pdf_as_base64(self) -> bool:
        return self._media_manager.pdf_as_base64

    @pdf_as_base64.setter
    def pdf_as_base64(self, value: bool) -> None:
        self._media_manager.pdf_as_base64 = value

    # --- Methods ---

    def _set_initial_model(self, initial_model_alias: str) -> None:
        """Sets the starting model for the client."""
        if not self.set_model(initial_model_alias):
            if initial_model_alias and initial_model_alias != "default":
                self.set_custom_model(initial_model_alias)
            else:
                self.set_model("default")

    def set_model(self, alias: str) -> bool:
        return self._model_manager.set_model(alias)

    def set_custom_model(self, model_name: str) -> None:
        self._model_manager.set_custom_model(model_name)

    def load_session(self, path_str: str) -> bool:
        success, message = self._session_manager.load_session(path_str)
        from llm_cli.ui import report_error, report_success

        if success:
            report_success(message)
        else:
            report_error(message)
        return success

    def save_session(self, path_str: str) -> bool:
        success, message = self._session_manager.save_session(path_str)
        from llm_cli.ui import report_error, report_success

        if success:
            report_success(message)
        else:
            report_error(message)
        return success

    def clear_history(self) -> None:
        self._session_manager.clear_history()

    def get_conversation_state(self) -> dict[str, Any]:
        return self._session_manager.get_state()

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        self._session_manager.set_state(state)

    def get_last_user_prompt(self) -> str | None:
        return self._session_manager.get_last_user_prompt()

    def _update_history(self, data: list[DataSource], model_msg: Message) -> None:
        self._session_manager.update_history(data, model_msg)

    def _get_responded_tool_ids(self) -> set[str]:
        return self._tool_manager.get_responded_tool_ids(self.conversation)

    def _refresh_general_settings(self) -> None:
        self._config_manager._refresh_general_settings()

    def _refresh_system_prompt(self) -> None:
        self._config_manager._refresh_system_prompt()

    def refresh_config(self) -> None:
        """Refreshes all configuration settings."""
        self._config_manager.refresh()

    def _load_model_aliases(self) -> None:
        self._model_manager.load_model_aliases()

    def _log_debug(self, **kwargs: Any) -> None:
        self._logging_manager.log_debug(**kwargs)

    def _report_error(self, provider: str, e: Exception) -> None:
        self._logging_manager.report_error(provider, e)

    def _trim_log_file(self, path: Path, max_lines: int) -> None:
        self._logging_manager.trim_log_file(path, max_lines)

    def _is_valid_tool_id(self, tool_id: str | None, responded: set[str]) -> bool:
        """Helper to validate tool ID against responded set."""
        from llm_cli.consts import UNKNOWN_TOOL_ID

        return bool(tool_id and tool_id != UNKNOWN_TOOL_ID and tool_id in responded)

    def _iter_history(self) -> Generator[tuple[Message, set[str]]]:
        """Iterates through conversation history with responded tool IDs."""
        responded_ids = self._get_responded_tool_ids()
        for msg in self.conversation:
            yield msg, responded_ids

    def _process_single_source(self, source: str) -> DataSource | None:
        return self._media_manager.process_single_source(source)

    def process_sources(self, sources: list[str]) -> None:
        """Processes a list of input sources and starts/updates session."""
        data = self._media_manager.process_sources(sources)
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

    def create_session(self) -> Any:
        """Factory method to create a chat session."""
        from llm_cli.clients.session import ChatSession

        return ChatSession(self)

    def _save_inline_media_and_get_log_entry(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        return self._media_manager.save_inline_media(inline_data, hint_text)

    def _expand(self, p: str | None) -> str | None:
        return str(Path(p).expanduser()) if p else None

    def get_model_icon(self) -> str:
        return self._model_manager.get_model_icon()

    def get_display_name(self) -> str:
        return self._model_manager.get_display_name()

    def _format_response_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        return f"**{self.get_display_name()}:**  \n{text.strip()}"

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
            mime_type = "image/png"  # Default

            # Handle both URL and Base64 response formats
            if "b64_json" in data_item:
                img_data = data_item["b64_json"]
            elif "url" in data_item:
                img_url = data_item["url"]
                from llm_cli.modules.media_utils import fetch_url_content

                img_data, fetched_mime = fetch_url_content(img_url)
                if fetched_mime:
                    mime_type = fetched_mime

            if not img_data:
                return ("Failed to retrieve image data from the response.", ""), None

            # Use shared media saving logic from BaseLlmClient
            display_text, _ = self._save_inline_media_and_get_log_entry(
                {"mimeType": mime_type, "data": img_data}, hint_text=full_prompt[:100]
            )
            if not display_text:
                display_text = (
                    "Successfully generated image, but failed to save it locally."
                )

            if revised_prompt:
                display_text += f"\n**Revised Prompt:** {revised_prompt}"

            # Update history with the image data (base64)
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

    def _poll_until_complete(
        self,
        poll_url: str,
        headers: dict,
        status_key: str = "status",
        completed_value: Any = "succeeded",
        failed_values: tuple[Any, ...] = ("failed", "cancelled"),
        timeout_seconds: int = 1800,
        interval: int = 5,
        request_timeout: int | None = None,
    ) -> dict[Any, Any] | None:
        """Common polling logic for asynchronous jobs."""

        start_time = time.time()
        console.print("[dim]Operation started. Polling for results...[/dim]")

        while time.time() - start_time < timeout_seconds:
            try:
                response = self._get(poll_url, headers=headers, timeout=request_timeout)
                response.raise_for_status()
                res = response.json()
                if not isinstance(res, dict):
                    return None

                status = res.get(status_key)
                if status == completed_value:
                    return res
                elif status in failed_values:
                    error = res.get("error", "Unknown error")
                    if isinstance(error, dict):
                        error = error.get("message", error)
                    raise RuntimeError(str(error))

                time.sleep(interval)
            except Exception as e:
                # Log and re-raise or handle as needed
                raise e

        raise TimeoutError("Polling timed out")

    def _send_deferred_generation(
        self,
        start_url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        provider_name: str,
        poll_url_template: str,  # e.g. "https://api.example.com/v1/jobs/{}"
        data: list[DataSource],
        status_key: str = "status",
        completed_value: str = "completed",
        failed_values: tuple[str, ...] = ("failed",),
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Common logic for deferred generation (video, etc.) with polling."""
        try:
            # Step 1: Start generation
            response = self._post(
                start_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            request_id = res.get("id") or res.get("request_id")
            if not request_id:
                return (
                    (f"Failed to get request ID for {provider_name} generation.", ""),
                    None,
                )

            # Step 2: Poll for results
            poll_url = (
                poll_url_template.format(request_id)
                if "{}" in poll_url_template
                else poll_url_template
            )
            poll_res = self._poll_until_complete(
                poll_url=poll_url,
                headers=headers,
                status_key=status_key,
                completed_value=completed_value,
                failed_values=failed_values,
                timeout_seconds=1800,
                request_timeout=self.request_timeout,
            )

            if not poll_res:
                return (("Failed to get poll result.", ""), None)

            # Look for URL in common fields
            video_url = poll_res.get("url") or poll_res.get("result_url")
            if not video_url and "data" in poll_res:
                items = poll_res["data"]
                if isinstance(items, list) and items:
                    video_url = items[0].get("url")
                elif isinstance(items, dict):
                    video_url = items.get("url")
            if not video_url and "video" in poll_res:
                video_url = poll_res["video"].get("url")

            if not video_url:
                return (
                    (
                        f"{provider_name} generation failed to retrieve URL.",
                        "",
                    ),
                    None,
                )

            display_text = (
                f"Successfully generated media.\n\n"
                f"[Download Link]({video_url})\n\n**URL:** `{video_url}`"
            )

            # Download and save if possible
            from llm_cli.modules.media_utils import fetch_url_content

            media_data, mime_type = fetch_url_content(video_url)
            if media_data and mime_type:
                hint = payload.get("prompt", "")[:100]
                log, _ = self._save_inline_media_and_get_log_entry(
                    {"mimeType": mime_type, "data": media_data}, hint_text=hint
                )
                if log:
                    display_text += f"\n\n{log}"

                model_msg = Message(
                    role=Role.MODEL,
                    parts=[
                        ContentPart(text=display_text),
                        ContentPart(
                            inline_data={"mimeType": mime_type, "data": media_data}
                        ),
                    ],
                )
            else:
                model_msg = Message(
                    role=Role.MODEL, parts=[ContentPart(text=display_text)]
                )

            self._update_history(data, model_msg)
            return (display_text.strip(), ""), None

        except TimeoutError:
            self._report_error(provider_name, TimeoutError("Polling timed out"))
            return (f"{provider_name} generation timed out", ""), None
        except Exception as e:
            self._report_error(provider_name, e)
            return (f"{provider_name} generation failed: {e}", ""), None

    def talk(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        """Starts an interactive chat session."""
        if not self.api_key and self.config_section not in ("ollama",):
            from llm_cli.ui import report_error

            report_error(
                f"API key for '{self.config_section}' missing.\n"
                f"Please set the '{self.config_section.upper()}_API_KEY' "
                "environment variable."
            )
            return

        if not self.model:
            from llm_cli.ui import report_error

            report_error(
                f"No model for '{self.config_section}'.\n"
                "Please check your model aliases in config.toml."
            )
            return

        self.create_session().run(initial_data, sources)

    def _has_pending_tool_calls(self) -> bool:
        """Checks if the last model response contains tool calls."""
        from llm_cli.modules.models import Role

        if not self.conversation or self.conversation[-1].role != Role.MODEL:
            return False
        from llm_cli.modules.models import ContentPart

        for part in self.conversation[-1].parts:
            if isinstance(part, ContentPart) and part.function_call:
                return True
        return False

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        """Handles in-chat slash commands."""
        from llm_cli.clients.command_handler import handle_command

        return handle_command(self, user_input, sources, pending_data)

    @property
    def slash_commands(self) -> set[str]:
        """Dynamic slash commands for completer."""
        from llm_cli.clients.command_handler import registry

        reg = getattr(self, "command_registry", registry)
        return reg.all_names_and_aliases

    def _print_help(self) -> None:
        from llm_cli.clients.command_handler import print_help

        print_help(self)

    def _build_prompt_from_history(self, data: list[DataSource]) -> str:
        """Collects all text from history and data into a single string."""
        from llm_cli.modules.models import ContentPart

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
