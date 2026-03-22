# llm_cli/apps/unified.py

from typing import Any, TypeVar

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.config import config_manager
from llm_cli.clients.registry import client_registry
from llm_cli.modules.models import DataSource
from llm_cli.ui import console

T = TypeVar("T")


class UnifiedClient:
    """
    A simple launcher that creates the initial provider-specific client.
    Unlike the previous version, it does not act as a proxy.
    Instead, ChatSession directly holds the real client instance.
    """

    def __init__(self, initial_provider: str | None = None, **kwargs: Any):
        self.client_kwargs = kwargs

        # 1. Determine initial provider
        default_p = config_manager.get("general", "unified_default_provider")
        active_providers = config_manager.get_active_providers()

        provider_name = str(initial_provider or default_p)
        if provider_name not in active_providers:
            if active_providers:
                provider_name = active_providers[0]
            else:
                console.print("[bold red]Error: No active providers found.[/bold red]")
                import sys

                sys.exit(1)

        # 2. Create the real client immediately
        client_class = client_registry.get_client_class(provider_name)
        if not client_class:
            console.print(
                f"[bold red]Error: Provider {provider_name} not found.[/bold red]"
            )
            import sys

            sys.exit(1)

        self.active_client = client_class(**self.client_kwargs)

    def load_session(self, path: str) -> bool:
        """Explicitly delegate to the active client."""
        return self.active_client.load_session(path)

    def process_sources(self, sources: list[str]) -> None:
        """Explicitly delegate to the active client."""
        self.active_client.process_sources(sources)

    def talk(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        """Starts an interactive chat session with the real client."""
        from llm_cli.clients.session import ChatSession

        # IMPORTANT: We pass the real client to the session.
        # This breaks the proxy chain and makes it AI-friendly.
        ChatSession(self.active_client).run(initial_data, sources)


def main() -> None:
    config = ClientConfig(
        client_class=UnifiedClient,  # type: ignore
        description="Unified LLM CLI with multi-provider support",
        supports_provider_selection=True,
        provider_choices=client_registry.list_aliases(),
    )
    run_client_cli(config)


if __name__ == "__main__":
    main()
