# llm_cli/clients/base.py

import base64
import copy
import datetime
import json
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax

from llm_cli.clients.config import get_setting, get_templates
from llm_cli.modules.media_utils import (
    fetch_url_content,
    process_file,
)
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

console = Console()


class ProviderSwitchRequest(Exception):
    """Exception raised to request a switch to a different LLM provider."""

    def __init__(self, provider: str):
        self.provider = provider


class CheckpointRequest(Exception):
    """Exception raised to request a conversation checkpoint (summarization)."""

    pass


class TemplateRequest(Exception):
    """Exception raised to request loading a template into the input buffer."""

    def __init__(self, text: str):
        self.text = text


class ExitRequest(Exception):
    """Exception raised to request exiting the application."""

    pass


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
            "tools",
            "help",
            "h",
        }
        self.config_section = config_section
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

        raw_prompt = get_setting("system_prompt", config_section) or ""
        disable_date_prompt = get_setting("disable_date_prompt", config_section)

        self.system_prompt = ""
        if not disable_date_prompt:
            now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d (%A)")
            self.system_prompt = f"Current date: {now}"

        if raw_prompt:
            if self.system_prompt:
                self.system_prompt += "\n"
            self.system_prompt += raw_prompt

        self.system_prompt_enabled = not disable_system_prompt

        self.conversation: list[Message] = []
        self.last_usage: dict[str, int] | None = None
        self.cumulative_total_tokens = 0
        self.last_request_duration: float | None = None

        from llm_cli.consts import CHAT_LOG_PATH, HISTORY_LOG_PATH

        self.history_path = str(HISTORY_LOG_PATH)
        self.chat_log_path = str(CHAT_LOG_PATH)
        self.max_chat_log_lines = int(
            get_setting("max_chat_log_lines", "general") or 10000
        )

        self.active_tools: list[str] = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )

        # Default to None (wait indefinitely) instead of a fixed 600s timeout.
        # This allows long-running reasoning processes to complete.
        # Users can manually interrupt with Ctrl+C if desired.
        raw_timeout = get_setting("request_timeout", "general")
        self.request_timeout = int(raw_timeout) if raw_timeout else None

        if enable_mcp:
            self._init_mcp(initial_tools is None)

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
        if not self.api_key and self.config_section != "ollama":
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
                return DataSource(
                    content=content,
                    content_type=ctype or "application/octet-stream",
                    is_file_or_url=True,
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
        _sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        """Handles in-chat slash commands."""
        if not user_input.startswith("/"):
            return False

        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("m", "model"):
            if not args:
                console.print("[bold]Available Models:[/bold]")
                for alias, name in self.available_models.items():
                    active = "*" if alias == self.current_alias else " "
                    console.print(
                        f" {active} [cyan]{alias:15}[/cyan] -> [dim]{name}[/dim]"
                    )
                return True

            model_alias = args
            if self.set_model(model_alias):
                console.print(
                    f"[cyan]Model switched to: {self.current_alias} "
                    f"({self.model})[/cyan]"
                )
            else:
                # Allow setting arbitrary models not in config
                self.set_custom_model(model_alias)
                console.print(
                    f"[yellow]Custom model set: {self.model} (not in config)[/yellow]"
                )
            return True

        if cmd in ("t", "template"):
            templates = get_templates()
            if not args:
                if not templates:
                    console.print(
                        "[yellow]No templates defined in [templates] section "
                        "of config.toml[/yellow]"
                    )
                else:
                    console.print("[bold]Available Templates:[/bold]")
                    for name, text in templates.items():
                        # Show a preview of the template text
                        preview = (text[:60] + "...") if len(text) > 60 else text
                        console.print(
                            f" [cyan]{name:15}[/cyan] -> [dim]{preview}[/dim]"
                        )
                return True

            template_name = args
            if template_name in templates:
                template_text = templates[template_name]
                if pending_data is not None:
                    # Instead of sending immediately,
                    # request to load it into the input buffer
                    raise TemplateRequest(template_text)
                else:
                    # If called from somewhere else without pending_data
                    console.print(f"[cyan]Selected template '{template_name}':[/cyan]")
                    console.print(Panel(template_text))
                    return True
            else:
                console.print(f"[red]Template not found: {template_name}[/red]")
                return True

        if cmd in ("checkpoint", "cp"):
            raise CheckpointRequest()

        if cmd == "save":
            path_str = args
            if not path_str:
                now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                default_filename = f"session_{now_str}"
                try:
                    user_input = prompt(
                        "Enter session filename: ",
                        default=default_filename,
                        completer=PathCompleter(expanduser=True),
                        complete_style=CompleteStyle.READLINE_LIKE,
                    ).strip()
                    if not user_input:
                        user_input = default_filename

                    if not user_input.lower().endswith(".json"):
                        path_str = f"{user_input}.json"
                    else:
                        path_str = user_input
                except (KeyboardInterrupt, EOFError):
                    console.print("[yellow]Save cancelled.[/yellow]")
                    return True

            try:
                save_path = Path(path_str)
                if save_path.exists():
                    if not Confirm.ask(
                        f"[yellow]File {save_path} already exists. Overwrite?[/yellow]",
                        default=False,
                    ):
                        console.print("[yellow]Save cancelled.[/yellow]")
                        return True

                # Ensure parent directory exists
                save_path.parent.mkdir(parents=True, exist_ok=True)

                with save_path.open("w", encoding="utf-8") as f:
                    json.dump(
                        [asdict(m) for m in self.conversation],
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                console.print(f"[green]Session saved to {save_path}[/green]")
            except Exception as e:
                console.print(f"[red]Failed to save session: {e}[/red]")
            return True

        if cmd == "load":
            path_str = args
            if not path_str:
                console.print("[red]Usage: /load <path>[/red]")
                return True

            self.load_session(path_str)
            return True

        if cmd == "attach":
            path_str = args
            if not path_str:
                console.print("[red]Usage: /attach <path>[/red]")
                return True

            res = self._process_single_source(path_str)
            if res and res.is_file_or_url:
                if res.content_type == "text/plain":
                    console.print(
                        f"[yellow]Notice: {path_str} is text. "
                        "Added as text context.[/yellow]"
                    )
                else:
                    console.print(
                        f"[green]Attached {res.content_type}: {path_str}[/green]"
                    )
                if pending_data is not None:
                    pending_data.append(res)
            else:
                console.print(
                    f"[red]Failed to attach: {path_str} (File not found or "
                    "invalid source)[/red]"
                )
            return True

        if cmd == "dump":
            json_str = json.dumps(
                [asdict(m) for m in self.conversation], indent=2, ensure_ascii=False
            )
            syn = Syntax(
                json_str,
                "json",
                theme="monokai",
                background_color="default",
                word_wrap=True,
            )
            console.print(Panel(syn, title="Conversation History", border_style="blue"))

            if pending_data:
                json_pending = json.dumps(
                    [asdict(d) for d in pending_data], indent=2, ensure_ascii=False
                )
                syn_pending = Syntax(
                    json_pending,
                    "json",
                    theme="monokai",
                    background_color="default",
                    word_wrap=True,
                )
                console.print(
                    Panel(
                        syn_pending,
                        title="Pending Context (Next Request)",
                        border_style="yellow",
                    )
                )
            return True

        if cmd == "raw":
            for msg in self.conversation:
                role = msg.role
                for p in msg.parts:
                    role_suffix = ""
                    text = ""
                    if isinstance(p, str):
                        text = p
                    elif isinstance(p, ContentPart):
                        if p.thought:
                            role_suffix = " (REASONING)"
                            text = p.thought
                        elif p.text:
                            text = p.text

                    if text:
                        print(f"[{role.upper()}{role_suffix}]\n{text}\n")
            return True

        if cmd in ("c", "clear"):
            self.clear_history()
            console.print("[yellow]Conversation history cleared.[/yellow]")
            return True

        if cmd in ("q", "quit"):
            raise ExitRequest

        if cmd == "tools":
            if args == "on":
                self.tools_enabled = True
                console.print("[green]Tools enabled.[/green]")
            elif args == "off":
                self.tools_enabled = False
                console.print("[yellow]Tools disabled.[/yellow]")
            elif not args:
                status = (
                    "[green]ENABLED[/green]"
                    if self.tools_enabled
                    else "[red]DISABLED[/red]"
                )
                active_for_provider = registry.get_active_names(
                    self.active_tools, provider=self.config_section
                )
                if active_for_provider:
                    tools_list = "\n".join([f"  - {t}" for t in active_for_provider])
                    tools_str = f"\n{tools_list}"
                else:
                    tools_str = " None"

                console.print(f"[bold]Tools Status:[/bold] {status}")
                if self.tools_enabled:
                    console.print(f"[bold]Active Tools:[/bold]{tools_str}")
                console.print("[dim]Usage: /tools on|off[/dim]")
            else:
                console.print(
                    f"[red]Error: Invalid argument '{args}'. Usage: /tools on|off[/red]"
                )
            return True

        if cmd in ("debug", "d"):
            self.live_debug = not self.live_debug
            status = "ENABLED" if self.live_debug else "DISABLED"
            console.print(f"[magenta]Live debug mode {status}.[/magenta]")
            return True

        if cmd in ("info", "i"):
            from rich.table import Table

            info_table = Table(show_header=False, box=None)
            info_table.add_row(
                "Provider",
                f"[bold green]{self.config_section}[/bold green]",
            )
            info_table.add_row("Model Alias", f"[cyan]{self.current_alias}[/cyan]")
            info_table.add_row("Full Model", f"[dim]{self.model}[/dim]")

            tool_status = (
                "[green]ENABLED[/green]"
                if self.tools_enabled
                else "[red]DISABLED[/red]"
            )
            info_table.add_row("Tools Status", tool_status)

            debug_status = "[green]ON[/green]" if self.live_debug else "[red]OFF[/red]"
            info_table.add_row("Live Debug", debug_status)

            if self.tools_enabled:
                active_for_provider = registry.get_active_names(
                    self.active_tools, provider=self.config_section
                )
                if active_for_provider:
                    tools_list = ", ".join(active_for_provider)
                    info_table.add_row("Active Tools", f"[dim]{tools_list}[/dim]")

            # Intent Analyzer Status
            from llm_cli.security.policy import policy_engine

            ia_enabled = policy_engine.config.get("intent_analyzer_enabled", False)
            if ia_enabled:
                ia_provider = policy_engine.config.get("intent_analyzer_provider", "?")
                ia_model = policy_engine.config.get("intent_analyzer_model", "?")
                info_table.add_row(
                    "Intent Analyzer",
                    f"[bold green]ON[/bold green] ({ia_provider}/{ia_model})",
                )
            else:
                info_table.add_row("Intent Analyzer", "[dim]OFF[/dim]")

            info_table.add_row("History Length", f"{len(self.conversation)} messages")
            info_table.add_row(
                "Total Tokens", f"[yellow]{self.cumulative_total_tokens:,}[/yellow]"
            )

            if self.last_usage:
                usage_str = ", ".join(f"{k}: {v}" for k, v in self.last_usage.items())
                info_table.add_row("Last Usage", f"[yellow]{usage_str}[/yellow]")

            console.print(
                Panel(
                    info_table,
                    title="[bold]Session Info[/bold]",
                    border_style="cyan",
                )
            )
            return True

        if cmd in ("help", "h"):
            self._print_help()
            return True

        return False

    def _print_help(self) -> None:
        console.print(
            "[bold]Available Commands:[/bold]\n"
            "  /attach <path> Attach media/file to context\n"
            "  /save <path>   Save conversation history to a JSON file\n"
            "  /load <path>   Load conversation history from a JSON file\n"
            "  /clear (c)     Clear conversation history\n"
            "  /checkpoint(cp)Summarize and clear history\n"
            "  /dump          Dump conversation history as JSON\n"
            "  /raw           Show conversation as raw text\n"
            "  /quit (q)      Exit the application\n"
            "  /info (i)      Show session info\n"
            "  /debug (d)     Toggle live debug mode\n"
            "  /model (m)     List available models or switch model\n"
            "                 (e.g. /m mage)\n"
            "  /provider (p)  List available providers or switch provider\n"
            "                 (e.g. /p openai)\n"
            "  /tools on|off  Show or toggle tool status\n"
            "\n"
            "[bold]Exit Application:[/bold]\n"
            "  Use [cyan]Ctrl+C[/cyan] or [cyan]Ctrl+D[/cyan] at any prompt to exit."
        )

    def _trim_log_file(self, path: Path, max_lines: int) -> None:
        try:
            if not path.exists():
                return

            # Robust line-based trimming.
            # We use errors="replace" to prevent UnicodeDecodeError if the log
            # is corrupted.
            with path.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if len(lines) > max_lines:
                with path.open("w", encoding="utf-8", errors="replace") as f:
                    f.writelines(lines[-max_lines:])
        except Exception as e:
            console.print(f"[dim red]Log trimming failed: {e}[/dim red]")

    def _save_inline_media_and_get_log_entry(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        """
        Saves inline media data (base64) to a file and returns a tuple of
        (formatted display string, saved file path).
        Supports images and audio.
        """
        mime_type = inline_data.get("mimeType", "")
        if (
            mime_type.startswith("image/")
            or mime_type.startswith("audio/")
            or mime_type.startswith("video/")
        ):
            import mimetypes

            from llm_cli.modules.media_utils import generate_safe_filename

            # Get save directories from config, default to current directory
            image_save_path = (
                self._expand(get_setting("image_save_path", "general")) or "."
            )
            audio_save_path = (
                self._expand(get_setting("audio_save_path", "general")) or "."
            )
            video_save_path = (
                self._expand(get_setting("video_save_path", "general")) or "."
            )

            if mime_type.startswith("audio/"):
                save_dir = Path(audio_save_path)
                default_ext = ".mp3"
                emoji = "🔊"
                type_name = "Audio"
            elif mime_type.startswith("video/"):
                save_dir = Path(video_save_path)
                default_ext = ".mp4"
                emoji = "🎥"
                type_name = "Video"
            else:
                save_dir = Path(image_save_path)
                default_ext = ".png"
                emoji = "🎨"
                type_name = "Image"

            save_dir.mkdir(parents=True, exist_ok=True)

            if "pcm" in mime_type.lower() or "l16" in mime_type.lower():
                import wave

                # PCM data needs a WAV header to be playable
                ext = ".wav"
                filename = generate_safe_filename(hint_text, ext=ext.strip("."))
                target_path = save_dir / filename

                # Parse sample rate from mime type (e.g. "audio/L16;rate=24000")
                # Default to 24000 Hz as per Gemini docs
                rate = 24000
                if "rate=" in mime_type:
                    try:
                        import re

                        match = re.search(r"rate=(\d+)", mime_type)
                        if match:
                            rate = int(match.group(1))
                    except Exception:
                        pass

                try:
                    data_bytes = base64.b64decode(inline_data["data"])
                    with wave.open(str(target_path), "wb") as wav_file:
                        wav_file.setnchannels(1)  # Mono
                        wav_file.setsampwidth(2)  # 16-bit
                        wav_file.setframerate(rate)
                        wav_file.writeframes(data_bytes)

                    msg = (
                        f"\n\n{emoji} {type_name} generated and saved to: "
                        f"**{target_path}**\n"
                    )
                    return msg, target_path
                except Exception as e:
                    console.print(f"[red]Failed to save PCM audio as WAV: {e}[/red]")
                    return None, None

            # Standard saving for other formats (MP3, Images, etc.)
            ext = mimetypes.guess_extension(mime_type) or default_ext
            filename = generate_safe_filename(hint_text, ext=ext.strip("."))
            target_path = save_dir / filename

            try:
                target_path.write_bytes(base64.b64decode(inline_data["data"]))
                # Inform user that media was saved
                msg = (
                    f"\n\n{emoji} {type_name} generated and saved to: "
                    f"**{target_path}**\n"
                )
                return msg, target_path
            except Exception as e:
                console.print(f"[red]Failed to save {type_name.lower()}: {e}[/red]")
        return None, None

    def _log_debug(
        self,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ) -> None:
        if not self.live_debug:
            return

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

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
        response_content: Any = None,
    ) -> None:
        def _format_json(data: Any) -> str | Syntax:
            if isinstance(data, (dict, list)):
                try:
                    return Syntax(
                        json.dumps(data, indent=2, ensure_ascii=False),
                        "json",
                        theme="monokai",
                        background_color="default",
                        word_wrap=True,
                    )
                except TypeError:
                    pass  # Fallback to string representation
            return str(data)

        if response_obj:
            req_info = []
            title_req = f"[bold cyan]API Request ({timestamp})[/bold cyan]"

            if request_payload:
                req_info.append(_format_json(request_payload))
            elif hasattr(response_obj, "request"):
                req = response_obj.request
                req_info.append(f"[bold]URL:[/bold] {req.url}")
                if req.body:
                    try:
                        b_str = (
                            req.body.decode("utf-8")
                            if isinstance(req.body, bytes)
                            else str(req.body)
                        )
                        req_info.append(_format_json(json.loads(b_str)))
                    except Exception:
                        req_info.append(f"[dim]Raw Body:[/dim]\n{str(req.body)}")

            if req_info:
                console.print(
                    Panel(
                        Group(*req_info),
                        title=title_req,
                        border_style="cyan",
                        expand=False,
                    )
                )

            res_info: list[str | Syntax] = [
                f"[bold]Status:[/bold] {response_obj.status_code}"
            ]
            if response_content:
                res_info.append(_format_json(response_content))
            else:
                try:
                    res_info.append(_format_json(response_obj.json()))
                except Exception:
                    res_info.append(response_obj.text)

            title_res = f"[bold green]API Response ({timestamp})[/bold green]"
            console.print(
                Panel(
                    Group(*res_info),
                    title=title_res,
                    border_style="green",
                    expand=False,
                )
            )
        else:
            if request_payload:
                title = f"[bold cyan]Payload Request ({timestamp})[/bold cyan]"
                console.print(
                    Panel(
                        _format_json(request_payload),
                        title=title,
                        border_style="cyan",
                        expand=False,
                    )
                )
            if response_content:
                title = f"[bold green]Payload Response ({timestamp})[/bold green]"
                console.print(
                    Panel(
                        _format_json(response_content),
                        title=title,
                        border_style="green",
                        expand=False,
                    )
                )

    def _report_error(self, provider_name: str, e: Exception) -> None:
        error_msg = str(e)
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
            try:
                body_str = json.dumps(e.response.json(), indent=2, ensure_ascii=False)
                error_msg += f"\nResponse Body: {body_str}"
            except Exception:
                if e.response.text:
                    error_msg += f"\nResponse Body: {e.response.text}"

        console.print(f"[bold red]{provider_name} Error: {error_msg}[/bold red]")

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
