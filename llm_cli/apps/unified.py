# llm_cli/apps/unified.py

from typing import Dict, List, Optional, Tuple

from llm_cli.apps.gemini import GeminiClient
from llm_cli.apps.openai import OpenAIClient
from llm_cli.apps.claude import ClaudeClient
from llm_cli.apps.grok import GrokClient
from llm_cli.clients.base import BaseLlmClient, DataSource, console, Conversation
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
            disable_system_prompt=kwargs.get('disable_system_prompt', False),
            enable_mcp=kwargs.get('enable_mcp', False),
            live_debug=kwargs.get('live_debug', False)
        )
        self.available_models = self.active_client.available_models
        self.active_client.conversation = self.conversation

    @property
    def conversation(self) -> Conversation:
        return getattr(self, "_conversation", [])

    @conversation.setter
    def conversation(self, value: Conversation):
        self._conversation = value
        if hasattr(self, 'active_client'):
            self.active_client.conversation = value

    @property
    def live_debug(self) -> bool:
        return getattr(self, "_live_debug", False)

    @live_debug.setter
    def live_debug(self, value: bool):
        self._live_debug = value
        if hasattr(self, 'active_client'):
            self.active_client.live_debug = value

    def _get_config_section(self, alias: str) -> str:
        mapping = {
            'gemini': 'google', 'google': 'google',
            'openai': 'openai', 'gpt': 'openai',
            'anthropic': 'anthropic', 'claude': 'anthropic',
            'xai': 'xai', 'grok': 'xai',
        }
        return mapping.get(alias, 'google')

    def _activate_provider(self, provider_alias: str) -> bool:
        if provider_alias not in self.PROVIDER_MAP:
            return False

        provider_name = self._get_config_section(provider_alias)
        if provider_name not in self.clients:
            client_class = self.PROVIDER_MAP.get(provider_alias)
            self.clients[provider_name] = client_class(**self.client_kwargs)

        self.active_client = self.clients[provider_name]
        self.active_client.live_debug = self.live_debug
        self.current_provider_name = provider_name
        self.config_section = self.active_client.config_section
        self.available_models = self.active_client.available_models
        self.pdf_as_base64 = self.active_client.pdf_as_base64

        # Share conversation history
        self.active_client.conversation = self.conversation

        # Sync tools
        if hasattr(self, 'active_tools'):
            self.active_client.active_tools = self.active_tools
        
        return True

    def _load_model_aliases(self):
        # Already handled by sub-clients
        pass

    def set_model(self, alias: str) -> bool:
        res = self.active_client.set_model(alias)
        if res:
            self.model = self.active_client.model
            self.current_alias = self.active_client.current_alias
        return res

    def _handle_command(
        self, user_input: str, sources: Optional[List[str]]
    ) -> bool:
        if not user_input.startswith('/'):
            return False
        cmd = user_input[1:]

        if cmd in self.PROVIDER_MAP:
            if self._activate_provider(cmd):
                console.print(f"[cyan]Switched to provider: {cmd}[/cyan]")
                return True

        return super()._handle_command(user_input, sources)

    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        self.active_client.active_tools = self.active_tools
        # Ensure conversation is synced just in case it was modified in-place 
        # but the reference wasn't updated (though property handles reassignments)
        self.active_client.conversation = self.conversation
        self.active_client.live_debug = self.live_debug
        return self.active_client._send(data)

    def _has_pending_tool_calls(self) -> bool:
        return self.active_client._has_pending_tool_calls()


def main():
    config = ClientConfig(
        client_class=UnifiedClient,
        description="Unified LLM CLI with multi-provider support",
        supports_provider_selection=True
    )
    run_client_cli(config)


if __name__ == "__main__":
    main()