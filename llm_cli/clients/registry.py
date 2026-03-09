from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient


class ProviderRegistry:
    """
    Registry for LLM providers and their client classes.
    Supports lazy loading of clients to avoid slow imports.
    """

    def __init__(self) -> None:
        self._providers: dict[str, tuple[str, str, str]] = {}
        self._loaded_clients: dict[str, type[BaseLlmClient]] = {}

    def register(
        self, alias: str, module_path: str, class_name: str, config_section: str
    ) -> None:
        """
        Registers a provider.

        Args:
            alias: The alias for the provider (e.g., 'openai').
            module_path: The full module path to import
            (e.g., 'llm_cli.clients.openai').
            class_name: The class name to load (e.g., 'OpenAIClient').
            config_section: The section name in the config file.
        """
        self._providers[alias] = (module_path, class_name, config_section)

    def get_client_class(self, alias: str) -> type["BaseLlmClient"] | None:
        """Loads and returns the client class for a given alias."""
        if alias not in self._providers:
            return None

        if alias in self._loaded_clients:
            return self._loaded_clients[alias]

        module_path, class_name, _ = self._providers[alias]
        try:
            import importlib
            from typing import cast

            module = importlib.import_module(module_path)
            client_class = cast(type["BaseLlmClient"], getattr(module, class_name))
            self._loaded_clients[alias] = client_class
            return client_class
        except (ImportError, AttributeError) as e:
            # Re-raise or handle appropriately. For Mamba specifically,
            # we might want to provide a helpful message if torch is missing.
            raise e

    def get_config_section(self, alias: str) -> str | None:
        """Returns the config section for a given alias."""
        if alias in self._providers:
            return self._providers[alias][2]
        return None

    def list_aliases(self) -> list[str]:
        """Returns a list of all registered aliases."""
        return list(self._providers.keys())

    def get_provider_info(self) -> dict[str, str]:
        """Returns a mapping of alias to config section."""
        return {alias: info[2] for alias, info in self._providers.items()}


# Global registry instance
client_registry = ProviderRegistry()

# Register default providers
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
client_registry.register("mamba", "llm_cli.clients.mamba", "MambaClient", "mamba")
client_registry.register(
    "huggingface", "llm_cli.clients.huggingface", "HuggingFaceClient", "huggingface"
)
client_registry.register(
    "hf", "llm_cli.clients.huggingface", "HuggingFaceClient", "huggingface"
)
