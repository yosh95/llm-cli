# llm_cli/apps/unified.py

from typing import Dict, List, Optional, Tuple

from llm_cli.apps.gemini import GeminiClient
from llm_cli.apps.openai import OpenAIClient
from llm_cli.apps.claude import ClaudeClient
from llm_cli.apps.grok import GrokClient
from llm_cli.clients.base import BaseLlmClient, DataSource, console
from llm_cli.clients.config import get_setting
from llm_cli.apps.cli_common import ClientConfig, run_client_cli


class UnifiedClient(BaseLlmClient):
    """
    A unified client capable of switching between multiple
    providers within a single session.
    """

    PROVIDER_MAP = {
        'google': GeminiClient, 'gemini': GeminiClient,
        'openai': OpenAIClient, 'gpt': OpenAIClient,
        'anthropic': ClaudeClient, 'claude': ClaudeClient,
        'xai': GrokClient, 'grok': GrokClient,
    }

    def __init__(self, initial_provider: Optional[str] = None, **kwargs):
        self.clients: Dict[str, BaseLlmClient] = {}
        self.client_kwargs = kwargs

        # Determine initial provider
        self.current_provider_name = (
            initial_provider or
            get_setting("unified_default_provider", "general") or "google"
        )
        self._activate_provider(self.current_provider_name)

        # Inherit settings from active client
        super().__init__(
            initial_model_alias=kwargs.get('initial_model_alias', 'default'),
            api_key_name="api_key",
            config_section=self.active_client.config_section,
            pdf_as_base64=self.active_client.pdf_as_base64,
            stdout=kwargs.get('stdout', False),
            render_markdown=kwargs.get('render_markdown', True),
            initial_tools=kwargs.get('initial_tools'),
            disable_system_prompt=kwargs.get('disable_system_prompt', False)
        )

        # Synchronize state
        self.available_models = self.active_client.available_models
        self.active_client.conversation = self.conversation

    def _get_config_section(self, alias: str) -> str:
        mapping = {
            'gemini': 'google', 'google': 'google',
            'openai': 'openai', 'gpt': 'openai',
            'claude': 'anthropic', 'anthropic': 'anthropic',
            'grok': 'xai', 'xai': 'xai'
        }
        return mapping.get(alias, alias)

    def _activate_provider(self, provider_alias: str) -> bool:
        config_section = self._get_config_section(provider_alias)
        provider_class = self.PROVIDER_MAP.get(provider_alias)

        if not provider_class:
            console.print(f"[red]Provider '{provider_alias}' unknown.[/red]")
            return False

        if config_section not in self.clients:
            self.clients[config_section] = provider_class(**self.client_kwargs)

        self.active_client = self.clients[config_section]
        self.config_section = config_section
        self.current_provider_name = config_section  # For test compatibility

        # Sync current state
        self.api_key = self.active_client.api_key
        self.available_models = self.active_client.available_models
        self.current_alias = self.active_client.current_alias
        self.model = self.active_client.model
        self.pdf_as_base64 = self.active_client.pdf_as_base64

        # Share conversation history
        if hasattr(self, 'conversation'):
            self.active_client.conversation = self.conversation

        # Sync tools
        if hasattr(self, 'active_tools'):
            self.active_client.active_tools = self.active_tools

        return True

    def _load_model_aliases(self):
        pass

    def set_model(self, alias: str) -> bool:
        if self.active_client.set_model(alias):
            self.current_alias = self.active_client.current_alias
            self.model = self.active_client.model
            return True
        return False

    def _handle_command(
        self, user_input: str, sources: Optional[List[str]]
    ) -> bool:
        if not user_input.startswith('/'):
            return False
        cmd = user_input[1:]

        if cmd in self.PROVIDER_MAP:
            if self.config_section == self._get_config_section(cmd):
                console.print(f"[yellow]Already using {cmd}[/yellow]")
            elif self._activate_provider(cmd):
                console.print(
                    f"[green]Switched to {cmd}. "
                    f"Model: {self.current_alias}[/green]"
                )
            return True

        return super()._handle_command(user_input, sources)

    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        self.active_client.active_tools = self.active_tools
        return self.active_client._send(data)

    def _has_pending_tool_calls(self) -> bool:
        return self.active_client._has_pending_tool_calls()

    def _process_single_source(self, source: str) -> Optional[DataSource]:
        """
        Delegate to active client for provider-specific processing
        (like Gemini uploads).
        """
        return self.active_client._process_single_source(source)


def main():
    """CLI entry point for the unified client."""
    config = ClientConfig(
        client_class=UnifiedClient,
        description="Unified CLI for interacting with multiple LLM providers "
                    "(Gemini, OpenAI, Claude, Grok)",
        supports_provider_selection=True
    )
    run_client_cli(config)


if __name__ == "__main__":
    main()
