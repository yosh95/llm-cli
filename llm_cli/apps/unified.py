# llm_cli/apps/unified.py

from typing import Any, TypeVar

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import config_manager
from llm_cli.clients.managers import (
    LoggingManager,
    MediaManager,
    SessionManager,
    ToolManager,
)
from llm_cli.clients.registry import client_registry
from llm_cli.modules.models import DataSource, Message
from llm_cli.ui import console

T = TypeVar("T")


class UnifiedClient:
    """
    A unified client (Facade) that delegates to provider-specific clients.
    Solves initialization order issues and reduces complexity by using composition.
    """

    def __init__(self, initial_provider: str | None = None, **kwargs: Any):
        self.client_kwargs = kwargs
        self.clients: dict[str, BaseLlmClient] = {}
        self.active_client: BaseLlmClient = None  # type: ignore

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

        # 2. Create shared managers that will be passed to all internal clients
        pdf_as_base64 = kwargs.get(
            "pdf_as_base64", config_manager.get_bool("general", "pdf_as_base64", True)
        )
        live_debug = kwargs.get("live_debug", False)

        # We need a dummy client for ModelManager/ConfigManager initially?
        # No, they take a 'client' but often only need it for some properties.
        # This is the tricky part of the shared manager design.

        # To avoid the circular dependency during initialization:
        self.shared_session = SessionManager()
        self.shared_tool = ToolManager(kwargs.get("initial_tools"))
        self.shared_logging = LoggingManager(live_debug)
        self.shared_media = MediaManager(pdf_as_base64)

        # We'll initialize the active client now.
        # It will create the ModelManager and ConfigManager for its specific provider.
        self._activate_provider(provider_name)

        # 3. Setup custom command registry
        import copy

        from llm_cli.clients.command_handler import Command, registry

        self.command_registry = copy.copy(registry)
        self.command_registry.register(
            Command(
                "provider",
                self._handle_provider_command,
                "List or switch provider",
                ["p"],
            )
        )

    def _activate_provider(self, provider_alias: str) -> bool:
        """Switches the active provider and syncs managers."""
        client_class = client_registry.get_client_class(provider_alias)
        config_section = client_registry.get_config_section(provider_alias)

        if not client_class or not config_section:
            return False

        if config_section not in self.clients:
            # Create new client with shared managers
            self.clients[config_section] = client_class(
                **self.client_kwargs,
                session_manager=self.shared_session,
                tool_manager=self.shared_tool,
                logging_manager=self.shared_logging,
                media_manager=self.shared_media,
            )

        self.active_client = self.clients[config_section]
        self.current_provider_name = config_section
        return True

    # --- Delegation ---

    def __getattr__(self, name: str) -> Any:
        """Delegate everything to the active client."""
        return getattr(self.active_client, name)

    # Note: Properties must be handled explicitly if we want to support setters
    @property
    def model(self) -> str:
        return self.active_client.model

    @model.setter
    def model(self, value: str) -> None:
        self.active_client.model = value

    @property
    def conversation(self) -> list[Message]:
        return self.active_client.conversation

    @conversation.setter
    def conversation(self, value: list[Message]) -> None:
        self.active_client.conversation = value

    @property
    def api_key(self) -> str | None:
        return self.active_client.api_key

    @property
    def config_section(self) -> str:
        return self.active_client.config_section

    # Add other necessary properties for ChatSession/UI
    @property
    def stdout(self) -> bool:
        return self.active_client.stdout

    @property
    def live_debug(self) -> bool:
        return self.active_client.live_debug

    @live_debug.setter
    def live_debug(self, value: bool) -> None:
        self.active_client.live_debug = value

    @property
    def slash_commands(self) -> set[str]:
        """Dynamic slash commands for completer."""
        return self.command_registry.all_names_and_aliases

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        """Handles in-chat slash commands."""
        from llm_cli.clients.command_handler import handle_command

        # Cast self to Any to satisfy Mypy as UnifiedClient acts as BaseLlmClient
        # via delegation but does not inherit from it to avoid init complexity.
        return handle_command(self, user_input, sources, pending_data)  # type: ignore

    def _handle_provider_command(self, ctx: Any) -> bool:
        """Handler for the /provider command."""
        args = ctx.args
        active_providers = config_manager.get_active_providers()

        if not args:
            from rich.table import Table

            table = Table(
                title="Active Providers", show_header=True, header_style="bold magenta"
            )
            table.add_column("Status", justify="center", width=4)
            table.add_column("Alias", style="cyan", width=15)
            table.add_column("Config Section", style="dim")

            info = client_registry.get_provider_info()
            for alias in sorted(info.keys()):
                section = info[alias]
                if section not in active_providers:
                    continue
                is_active = section == self.active_client.config_section
                active_mark = "[bold green]*[/bold green]" if is_active else ""
                table.add_row(active_mark, alias, section)
            console.print(table)
            console.print("[dim]Usage: /p <alias> to switch provider[/dim]")
            return True

        if (
            args not in active_providers
            and client_registry.get_config_section(args) not in active_providers
        ):
            console.print(f"[red]Error: {args} is inactive (API Key missing).[/red]")
            return True

        if self._activate_provider(args):
            console.print(
                f"[cyan]Switched to provider: {args} (Model: {self.model})[/cyan]"
            )
            return True
        else:
            console.print(f"[red]Unknown or unavailable provider: {args}[/red]")
            return True

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        return self.active_client._send(data)


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
