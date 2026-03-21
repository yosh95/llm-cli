# llm_cli/clients/__init__.py

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient


class ProviderRegistry:
    """Registry for LLM providers. Merged from registry.py."""

    def __init__(self) -> None:
        self._providers: dict[str, tuple[str, str, str]] = {}
        self._loaded_clients: dict[str, type[BaseLlmClient]] = {}

    def register(
        self, alias: str, module_path: str, class_name: str, config_section: str
    ) -> None:
        self._providers[alias] = (module_path, class_name, config_section)

    def get_client_class(self, alias: str) -> type["BaseLlmClient"] | None:
        if alias not in self._providers:
            return None
        if alias in self._loaded_clients:
            return self._loaded_clients[alias]

        module_path, class_name, _ = self._providers[alias]
        try:
            import importlib

            module = importlib.import_module(module_path)
            client_class = getattr(module, class_name)
            if not isinstance(client_class, type):
                return None

            self._loaded_clients[alias] = client_class
            return client_class
        except (ImportError, AttributeError) as e:
            raise e

    def get_config_section(self, alias: str) -> str | None:
        return self._providers[alias][2] if alias in self._providers else None

    def list_aliases(self) -> list[str]:
        return list(self._providers.keys())

    def get_provider_info(self) -> dict[str, str]:
        return {alias: info[2] for alias, info in self._providers.items()}


client_registry = ProviderRegistry()

# Default providers
client_registry.register("google", "llm_cli.clients.gemini", "GeminiClient", "google")
client_registry.register("gemini", "llm_cli.clients.gemini", "GeminiClient", "google")
client_registry.register("openai", "llm_cli.clients.openai", "OpenAIClient", "openai")
client_registry.register("gpt", "llm_cli.clients.openai", "OpenAIClient", "openai")
client_registry.register(
    "anthropic", "llm_cli.clients.claude", "ClaudeClient", "anthropic"
)
client_registry.register(
    "claude", "llm_cli.clients.claude", "ClaudeClient", "anthropic"
)
client_registry.register("xai", "llm_cli.clients.grok", "GrokClient", "xai")
client_registry.register("grok", "llm_cli.clients.grok", "GrokClient", "xai")
client_registry.register("ollama", "llm_cli.clients.ollama", "OllamaClient", "ollama")
