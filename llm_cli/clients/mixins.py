# llm_cli/clients/mixins.py

import datetime
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from rich.console import Console

from llm_cli.modules.models import DataSource, Message

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient

# Default console for when not used via BaseLlmClient
_default_console = Console()


@runtime_checkable
class LlmClientProtocol(Protocol):
    """Protocol defining the expected interface for Mixin targets."""

    config_section: str
    stdout: bool
    pdf_as_base64: bool
    available_models: dict[str, Any]
    model: str
    current_alias: str
    live_debug: bool
    max_chat_log_lines: int
    request_timeout: int | None
    system_prompt: str
    system_prompt_enabled: bool
    history_path: str
    chat_log_path: str
    conversation: list[Message]

    def set_model(self, alias: str) -> bool: ...
    def set_custom_model(self, model_name: str) -> None: ...
    def _process_single_source(self, source: str) -> DataSource | None: ...


class ConfigMixin:
    """Mixin for configuration and prompt management."""

    def _refresh_general_settings(self: LlmClientProtocol) -> None:
        """Reloads settings that can change at runtime."""
        from llm_cli.clients import base as base_mod

        raw_timeout = base_mod.get_setting("request_timeout", "general")
        try:
            self.request_timeout = int(raw_timeout) if raw_timeout else None
        except (ValueError, TypeError):
            self.request_timeout = None

        raw_max_lines = base_mod.get_setting("max_chat_log_lines", "general")
        try:
            self.max_chat_log_lines = int(raw_max_lines) if raw_max_lines else 10000
        except (ValueError, TypeError):
            self.max_chat_log_lines = 10000

    def _refresh_system_prompt(self: LlmClientProtocol) -> None:
        """Constructs or refreshes the system prompt."""
        from llm_cli.clients import base as base_mod

        raw_prompt = base_mod.get_setting("system_prompt", self.config_section) or ""
        disable_date_prompt = base_mod.get_setting(
            "disable_date_prompt", self.config_section
        )

        self.system_prompt = ""
        if not disable_date_prompt:
            now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d (%A)")
            self.system_prompt = f"Current date: {now}"

        if raw_prompt:
            if self.system_prompt:
                self.system_prompt += "\n"
            self.system_prompt += raw_prompt

        self.system_prompt_enabled = (
            getattr(self, "_disable_system_prompt", False) is False
        )

    def _load_model_aliases(self: LlmClientProtocol) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients import base as base_mod

        # Use console from base if available to support existing tests
        console = getattr(base_mod, "console", _default_console)

        self.available_models = base_mod.get_model_aliases(self.config_section)
        if not self.available_models:
            console.print(
                f"[yellow]Warning: No models configured for {self.config_section}. "
                "Check config.toml.[/yellow]"
            )


class MediaMixin:
    """Mixin for processing media sources (files, URLs, etc.)."""

    def process_sources(self: LlmClientProtocol, sources: list[str]) -> None:
        """Processes a list of input sources (files, URLs, text)."""
        data = [
            processed for s in sources if (processed := self._process_single_source(s))
        ]
        has_prompt = any(not d.is_file_or_url for d in data)

        from typing import cast

        from llm_cli.clients.session import ChatSession

        session = ChatSession(cast("BaseLlmClient", self))

        if data:
            if self.stdout or has_prompt:
                session.process_and_print(data)
                if not self.stdout:
                    session.run(sources=sources)
            else:
                session.run(initial_data=data, sources=sources)
        else:
            session.run(sources=sources)

    def _process_single_source(
        self: LlmClientProtocol, source: str
    ) -> DataSource | None:
        """Processes a single source string into a DataSource object."""
        from llm_cli.clients import base as base_mod

        if source.startswith("http"):
            content, ctype = base_mod.fetch_url_content(source, self.pdf_as_base64)
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
            res_dict = base_mod.process_file(path, self.pdf_as_base64)
            if res_dict:
                return DataSource(
                    content=res_dict["content"],
                    content_type=res_dict["content_type"],
                    is_file_or_url=True,
                    metadata={"filename": res_dict.get("filename", path.name)},
                )
            return None

        return DataSource(content=source, content_type="text/plain")

    def _expand(self, p: str | None) -> str | None:
        """Expands user path symbols."""
        return str(Path(p).expanduser()) if p else None


class LoggingMixin:
    """Mixin for logging, debug display and error reporting."""

    def _log_debug(
        self: LlmClientProtocol,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ) -> None:
        from typing import cast

        from llm_cli.clients.base_helpers import log_debug

        log_debug(
            cast("BaseLlmClient", self), response_obj, request_payload, response_content
        )

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

    def _trim_log_file(self, path: Path, max_lines: int) -> None:
        from llm_cli.clients import base as base_mod

        console = getattr(base_mod, "console", _default_console)
        from llm_cli.clients.base_helpers import trim_log_file

        trim_log_file(console, path, max_lines)
