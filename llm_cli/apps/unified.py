# llm_cli/apps/unified.py

from typing import Dict, List, Optional, Tuple

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.clients.claude import ClaudeClient
from llm_cli.clients.config import get_setting
from llm_cli.clients.gemini import GeminiClient
from llm_cli.clients.grok import GrokClient
from llm_cli.clients.ollama import OllamaClient
from llm_cli.clients.openai import OpenAIClient
from llm_cli.modules.models import DataSource, Message


class UnifiedClient(BaseLlmClient):
    """
    A unified client capable of switching between multiple
    providers within a single session.
    """

    # Maps aliases to (ClientClass, config_section)
    PROVIDER_CONFIG = {
        "google": (GeminiClient, "google"),
        "gemini": (GeminiClient, "google"),
        "openai": (OpenAIClient, "openai"),
        "gpt": (OpenAIClient, "openai"),
        "anthropic": (ClaudeClient, "anthropic"),
        "claude": (ClaudeClient, "anthropic"),
        "xai": (GrokClient, "xai"),
        "grok": (GrokClient, "xai"),
        "ollama": (OllamaClient, "ollama"),
    }

    def __init__(self, initial_provider: Optional[str] = None, **kwargs):
        self.clients: Dict[str, BaseLlmClient] = {}
        self.client_kwargs = kwargs

        default_p = get_setting("unified_default_provider", "general")
        if not initial_provider and not default_p:
            console.print(
                "[bold red]Error: No default provider is configured.[/bold red]\n"
                "Please set 'unified_default_provider' in the [general] section "
                "of your config.toml or run [cyan]llm-cli-config[/cyan] to set it up."
            )
            import sys

            sys.exit(1)

        self.current_provider_name = initial_provider or default_p
        self._activate_provider(self.current_provider_name)

        super().__init__(
            initial_model_alias=kwargs.get("initial_model_alias", "default"),
            api_key_name="api_key",
            config_section=self.active_client.config_section,
            pdf_as_base64=self.active_client.pdf_as_base64,
            stdout=kwargs.get("stdout", False),
            render_markdown=kwargs.get("render_markdown", True),
            initial_tools=kwargs.get("initial_tools"),
            disable_system_prompt=kwargs.get("disable_system_prompt", False),
            enable_mcp=kwargs.get("enable_mcp", False),
            live_debug=kwargs.get("live_debug", False),
        )
        self.available_models = self.active_client.available_models
        self.active_client.conversation = self.conversation

    @property
    def conversation(self) -> List[Message]:
        return getattr(self, "_conversation", [])

    @conversation.setter
    def conversation(self, value: List[Message]):
        self._conversation = value
        if hasattr(self, "active_client"):
            self.active_client.conversation = value

    @property
    def live_debug(self) -> bool:
        return getattr(self, "_live_debug", False)

    @live_debug.setter
    def live_debug(self, value: bool):
        self._live_debug = value
        if hasattr(self, "active_client"):
            self.active_client.live_debug = value

    @property
    def tools_enabled(self) -> bool:
        return getattr(self, "_tools_enabled", True)

    @tools_enabled.setter
    def tools_enabled(self, value: bool):
        self._tools_enabled = value
        if hasattr(self, "active_client"):
            self.active_client.tools_enabled = value

    @property
    def reasoning_enabled(self) -> bool:
        return getattr(self, "_reasoning_enabled", False)

    @reasoning_enabled.setter
    def reasoning_enabled(self, value: bool):
        self._reasoning_enabled = value
        if hasattr(self, "active_client"):
            self.active_client.reasoning_enabled = value

    def _activate_provider(self, provider_alias: str) -> bool:
        if provider_alias not in self.PROVIDER_CONFIG:
            return False

        client_class, config_section = self.PROVIDER_CONFIG[provider_alias]
        if config_section not in self.clients:
            self.clients[config_section] = client_class(**self.client_kwargs)

        self.active_client = self.clients[config_section]
        self.active_client.live_debug = self.live_debug
        self.active_client.tools_enabled = self.tools_enabled
        self.active_client.reasoning_enabled = self.reasoning_enabled
        self.current_provider_name = config_section
        self.config_section = self.active_client.config_section
        self.available_models = self.active_client.available_models
        self.pdf_as_base64 = self.active_client.pdf_as_base64
        self.model = self.active_client.model
        self.current_alias = self.active_client.current_alias

        # Sync state
        self.active_client.conversation = self.conversation
        if hasattr(self, "active_tools"):
            self.active_client.active_tools = self.active_tools

        return True

    def _load_model_aliases(self):
        """Handled by sub-clients."""
        pass

    def set_model(self, alias: str) -> bool:
        if self.active_client.set_model(alias):
            self.model = self.active_client.model
            self.current_alias = self.active_client.current_alias
            return True
        return False

    def _process_single_source(self, source: str) -> Optional[DataSource]:
        """Delegate source processing to the active provider client."""
        return self.active_client._process_single_source(source)

    def _handle_command(
        self,
        user_input: str,
        sources: Optional[List[str]],
        pending_data: Optional[List[DataSource]] = None,
    ) -> bool:
        if not user_input.startswith("/"):
            return False

        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("p", "provider"):
            if not args:
                console.print("[bold]Available Providers:[/bold]")
                # Get unique provider aliases mapping to config sections
                seen_sections = set()
                for alias, (_, section) in self.PROVIDER_CONFIG.items():
                    if section not in seen_sections:
                        active = "*" if section == self.current_provider_name else " "
                        console.print(
                            f" {active} [cyan]{alias:15}[/cyan] -> [dim]{section}[/dim]"
                        )
                        seen_sections.add(section)
                return True

            provider_alias = args
            if self._activate_provider(provider_alias):
                console.print(
                    f"[cyan]Switched to provider: {provider_alias} "
                    f"(Model: {self.model})[/cyan]"
                )
                return True
            else:
                console.print(f"[red]Unknown provider: {provider_alias}[/red]")
                return True

        return super()._handle_command(user_input, sources, pending_data)

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        self.active_client.active_tools = self.active_tools
        self.active_client.conversation = self.conversation
        self.active_client.live_debug = self.live_debug
        self.active_client.tools_enabled = self.tools_enabled
        self.active_client.reasoning_enabled = self.reasoning_enabled
        return self.active_client._send(data)

    def _has_pending_tool_calls(self) -> bool:
        return self.active_client._has_pending_tool_calls()


def main():
    config = ClientConfig(
        client_class=UnifiedClient,
        description="Unified LLM CLI with multi-provider support",
        supports_provider_selection=True,
    )
    run_client_cli(config)


if __name__ == "__main__":
    main()
