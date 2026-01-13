# llm_cli/clients/base.py

import base64
import datetime
import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax

from llm_cli.clients.config import get_setting
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
        initial_tools: Optional[List[str]] = None,
        disable_system_prompt: bool = False,
        enable_mcp: bool = False,
        live_debug: bool = False,
    ):
        """Initializes the LLM client with configuration and state."""
        self.config_section = config_section
        self.api_key = get_setting(api_key_name, config_section)
        self.pdf_as_base64 = pdf_as_base64
        self.stdout = stdout
        self.render_markdown = render_markdown
        self.live_debug = live_debug

        self.tools_enabled = True
        self.reasoning_enabled = False

        raw_prompt = get_setting("system_prompt", config_section) or ""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
        self.system_prompt = f"Current date and time: {now}"
        if raw_prompt:
            self.system_prompt += f"\n{raw_prompt}"

        self.system_prompt_enabled = not disable_system_prompt

        self.available_models: Dict[str, str] = {}
        self.current_alias = ""
        self.model = ""
        self._load_model_aliases()
        self.set_model(initial_model_alias) or self.set_model("default")

        self.conversation: List[Message] = []
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_request_duration: Optional[float] = None

        self.history_path = self._expand(get_setting("LLM_PROMPT_HISTORY", "general"))
        self.chat_log_path = self._expand(get_setting("LLM_CHAT_LOG", "general"))
        self.max_chat_log_lines = int(
            get_setting("max_chat_log_lines", "general") or 10000
        )

        self.active_tools: List[str] = (
            initial_tools if initial_tools is not None else list(registry.tools.keys())
        )

        if enable_mcp:
            self._init_mcp(initial_tools is None)

    def _init_mcp(self, update_active_tools: bool):
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

    def _expand(self, p: Optional[str]) -> Optional[str]:
        """Expands user path symbols."""
        return str(Path(p).expanduser()) if p else None

    @abstractmethod
    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        pass

    @abstractmethod
    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Sends the request to the specific provider API.

        Args:
            data: A list of DataSource objects containing the user's latest input.

        Returns:
            A tuple of (response_text, usage_dict).
        """
        pass

    def _post_with_retry(
        self,
        url: str,
        headers: Dict,
        json_data: Dict,
        timeout: int = 120,
        max_retries: int = 3,
    ) -> requests.Response:
        """
        Performs a POST request with automatic retry and exponential backoff.

        Args:
            url: The endpoint URL.
            headers: HTTP headers.
            json_data: The JSON payload.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.

        Returns:
            The successful requests.Response object.

        Raises:
            requests.exceptions.RequestException: If all retries fail.
        """
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url, headers=headers, json=json_data, timeout=timeout
                )

                if response.status_code == 429 or 500 <= response.status_code < 600:
                    response.raise_for_status()

                return response
            except (
                requests.exceptions.RequestException,
                requests.exceptions.HTTPError,
            ) as e:
                last_exception = e

                if isinstance(e, requests.exceptions.HTTPError):
                    status_code = e.response.status_code
                    if status_code != 429 and status_code < 500:
                        raise e

                if attempt < max_retries - 1:
                    wait_time = (2**attempt) + 1
                    console.print(
                        f"[yellow]Request failed: {e}. "
                        f"Retrying in {wait_time}s... "
                        f"({attempt + 1}/{max_retries})[/yellow]"
                    )
                    time.sleep(wait_time)
                else:
                    raise last_exception

        raise last_exception if last_exception else Exception("Request failed")

    def set_model(self, alias: str) -> bool:
        """
        Sets the active model using its alias.

        Args:
            alias: The model alias defined in config.

        Returns:
            True if the model was successfully set, False otherwise.
        """
        if alias in self.available_models:
            self.current_alias = alias
            self.model = self.available_models[alias]
            return True
        return False

    def talk(
        self,
        initial_data: Optional[List[DataSource]] = None,
        sources: Optional[List[str]] = None,
    ):
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

    def process_sources(self, sources: List[str]):
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

    def _process_single_source(self, source: str) -> Optional[DataSource]:
        """Processes a single source string into a DataSource object."""
        if source.startswith("http"):
            content, ctype = fetch_url_content(source, self.pdf_as_base64)
            if content:
                return DataSource(
                    content=content,
                    content_type=ctype,
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

    def _handle_command(
        self,
        user_input: str,
        sources: Optional[List[str]],
        pending_data: Optional[List[DataSource]] = None,
    ) -> bool:
        """Handles in-chat slash commands."""
        if not user_input.startswith("/"):
            return False

        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in self.available_models:
            self.set_model(cmd)
            console.print(
                f"[cyan]Model switched to: {self.current_alias} ({self.model})[/cyan]"
            )
            return True

        if cmd in ("m", "models"):
            console.print("[bold]Available Models:[/bold]")
            for alias, name in self.available_models.items():
                active = "*" if alias == self.current_alias else " "
                console.print(f" {active} [cyan]{alias:15}[/cyan] -> [dim]{name}[/dim]")
            return True

        if cmd in ("google", "openai", "anthropic", "xai", "ollama"):
            raise ProviderSwitchRequest(cmd)

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

            try:
                load_path = Path(path_str)
                if not load_path.exists():
                    console.print(f"[red]File not found: {load_path}[/red]")
                    return True

                with load_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                # Convert list of dicts back to list of Message objects
                loaded_conversation = []
                for msg_data in data:
                    role = Role(msg_data["role"])
                    parts = []
                    for p in msg_data["parts"]:
                        if isinstance(p, str):
                            parts.append(p)
                        elif isinstance(p, dict):
                            parts.append(ContentPart(**p))
                    loaded_conversation.append(Message(role=role, parts=parts))

                self.conversation = loaded_conversation
                console.print(
                    f"[green]Session loaded from {load_path} "
                    f"({len(self.conversation)} messages)[/green]"
                )
            except Exception as e:
                console.print(f"[red]Failed to load session: {e}[/red]")
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
            self.conversation.clear()
            console.print("[yellow]Conversation history cleared.[/yellow]")
            return True

        if cmd in ("q", "quit"):
            raise EOFError

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
                    tools_list = "\n".join(
                        [f"  - {t}" for t in active_for_provider]
                    )
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

        if cmd == "reasoning":
            if args == "on":
                self.reasoning_enabled = True
                console.print("[green]Reasoning display enabled.[/green]")
            elif args == "off":
                self.reasoning_enabled = False
                console.print("[yellow]Reasoning display disabled.[/yellow]")
            elif not args:
                status = (
                    "[green]ENABLED[/green]"
                    if self.reasoning_enabled
                    else "[red]DISABLED[/red]"
                )
                console.print(f"[bold]Reasoning Status:[/bold] {status}")
                console.print("[dim]Usage: /reasoning on|off[/dim]")
            else:
                console.print(
                    f"[red]Error: Invalid argument '{args}'. "
                    "Usage: /reasoning on|off[/red]"
                )
            return True

        if cmd in ("debug", "d"):
            self.live_debug = not self.live_debug
            status = "ENABLED" if self.live_debug else "DISABLED"
            console.print(f"[magenta]Live debug mode {status}.[/magenta]")
            return True

        if cmd in ("info", "i"):
            debug_status = "ON" if self.live_debug else "OFF"
            reasoning_status = "ON" if self.reasoning_enabled else "OFF"
            if not self.tools_enabled:
                tools_str = " [red]Disabled[/red]"
            else:
                active_for_provider = registry.get_active_names(
                    self.active_tools, provider=self.config_section
                )
                if active_for_provider:
                    tools_list = "\n".join(
                        [f"    - {t}" for t in active_for_provider]
                    )
                    tools_str = f"\n{tools_list}"
                else:
                    tools_str = " None"
            console.print(
                "[bold]Session Info:[/bold]\n"
                f"  Provider: [cyan]{self.config_section}[/cyan]\n"
                f"  Model: [cyan]{self.model}[/cyan] "
                f"(Alias: {self.current_alias})\n"
                f"  Tools:{tools_str}\n"
                f"  Reasoning: {reasoning_status}\n"
                f"  Debug: [magenta]{debug_status}[/magenta]\n"
                f"  History: {len(self.conversation)} messages"
            )
            return True

        if cmd in ("help", "h"):
            self._print_help()
            return True

        return False

    def _print_help(self):
        models_str = ", ".join(self.available_models.keys())
        console.print(
            "[bold]Available Commands:[/bold]\n"
            "  /attach <path> Attach media/file to context\n"
            "  /save <path>   Save conversation history to a JSON file\n"
            "  /load <path>   Save conversation history to a JSON file\n"
            "  /clear (c)     Clear conversation history\n"
            "  /checkpoint(cp)Summarize and clear history\n"
            "  /dump          Dump conversation history as JSON\n"
            "  /raw           Show conversation as raw text\n"
            "  /quit (q)      Exit the application\n"
            "  /info (i)      Show session info\n"
            "  /debug (d)     Toggle live debug mode\n"
            "  /models (m)    List available models\n"
            "  /tools on|off  Show or toggle tool status\n"
            "  /reasoning on|off Show or toggle reasoning display\n"
            "  /google, /openai, /anthropic, /xai, /ollama  Switch provider\n"
            f"  <model_alias>  Switch to specific model ({models_str})\n\n"
            "[bold]Exit Application:[/bold]\n"
            "  Use [cyan]escape[/cyan], [cyan]Ctrl+C[/cyan], "
            "or [cyan]Ctrl+D[/cyan] at any prompt to exit."
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
        if inline_data.get("mimeType", "").startswith("image/"):
            ext = inline_data["mimeType"].split("/")[-1]
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            default_prefix = f"generated_{now_str}"

            if not self.stdout:
                try:
                    console.print("\n[cyan]Image generation detected.[/cyan]")
                    msg = (
                        f"Enter image file name (default extension .{ext} will "
                        "be added if missing): "
                    )
                    user_input = prompt(
                        msg,
                        default=default_prefix,
                        completer=PathCompleter(expanduser=True),
                        complete_style=CompleteStyle.READLINE_LIKE,
                    ).strip()
                    if not user_input:
                        user_input = default_prefix

                    if user_input.lower().endswith(f".{ext}"):
                        fname = user_input
                    else:
                        fname = f"{user_input}.{ext}"
                except (KeyboardInterrupt, EOFError):
                    fname = f"{default_prefix}.{ext}"
            else:
                fname = f"{default_prefix}.{ext}"

            # Honor image_output_dir from config
            output_dir_str = get_setting("image_output_dir", "general") or "."
            output_dir = Path(output_dir_str)
            target_path = output_dir / fname

            try:
                # Ensure parent directory of the target path exists
                target_path.parent.mkdir(parents=True, exist_ok=True)

                if target_path.exists():
                    if not Confirm.ask(
                        f"[yellow]File {target_path} already exists. "
                        "Overwrite?[/yellow]",
                        default=False,
                    ):
                        console.print("[yellow]Skipping image save.[/yellow]")
                        return None

                target_path.write_bytes(base64.b64decode(inline_data["data"]))
                return f"\n**output image: {target_path}**"
            except Exception as e:
                console.print(f"[red]Failed to save image: {e}[/red]")
        return None

    def _log_debug(
        self,
        response_obj: Any = None,
        request_payload: Any = None,
        response_content: Any = None,
    ):
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
    ):
        def _format_json(data):
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

            res_info = [f"[bold]Status:[/bold] {response_obj.status_code}"]
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

    def _report_error(self, provider_name: str, e: Exception):
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
        return f"{icon} ({self.config_section}/{self.current_alias}/{self.model})"

    def _format_response_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        display_name = self.get_display_name()
        return f"**{display_name}:**  \n{text.strip()}"
