# llm_cli/apps/unified.py

from typing import Any, TypeVar

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients import client_registry
from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import config_manager
from llm_cli.modules.models import DataSource, Message
from llm_cli.ui import console

T = TypeVar("T")


class UnifiedClient:
    """
    A unified client (Facade) that delegates to provider-specific clients.
    Solves initialization order issues and reduces complexity by using composition.
    """

    def __init__(self, initial_provider: str | None = None, **kwargs: Any):
        # 0. Centralize and remove state-managed kwargs to avoid duplicate values
        # when passing them explicitly to provider-specific clients.
        self._shared_active_tools: list[str] | None = kwargs.pop("initial_tools", None)
        self._shared_live_debug: bool = kwargs.pop("live_debug", False)
        self._shared_system_prompt_enabled: bool = not kwargs.get(
            "disable_system_prompt", False
        )

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

        # 2. Shared state to be synced across clients
        self._shared_conversation: list[Message] = []
        self._shared_tools_enabled: bool = True

        # 3. Initialize the active client
        self._activate_provider(provider_name)

        # 4. Setup custom command registry
        from llm_cli.clients.command_handler import (
            Command,
            CommandRegistry,
        )
        from llm_cli.clients.command_handler import (
            registry as global_registry,
        )

        self.command_registry = CommandRegistry()
        for cmd in global_registry.commands.values():
            self.command_registry.register(cmd)
        self.command_registry.register(
            Command(
                "provider",
                self._handle_provider_command,
                "List or switch provider",
                ["p"],
            )
        )

    def _activate_provider(self, provider_alias: str) -> bool:
        """Switches the active provider and syncs state."""
        client_class = client_registry.get_client_class(provider_alias)
        config_section = client_registry.get_config_section(provider_alias)

        if not client_class or not config_section:
            return False

        # Capture state from current active client before switching
        if self.active_client:
            self._shared_conversation = self.active_client.conversation
            self._shared_active_tools = self.active_client.active_tools
            self._shared_live_debug = self.active_client.live_debug
            self._shared_tools_enabled = self.active_client.tools_enabled
            self._shared_system_prompt_enabled = (
                self.active_client.system_prompt_enabled
            )

        if config_section not in self.clients:
            # Create new client
            self.clients[config_section] = client_class(
                **self.client_kwargs,
                initial_tools=self._shared_active_tools,
                live_debug=self._shared_live_debug,
            )

        self.active_client = self.clients[config_section]

        # Apply shared state to the new/existing client
        self.active_client.conversation = self._shared_conversation
        if self._shared_active_tools is not None:
            self.active_client.active_tools = self._shared_active_tools
        self.active_client.live_debug = self._shared_live_debug
        self.active_client.tools_enabled = self._shared_tools_enabled
        self.active_client.system_prompt_enabled = self._shared_system_prompt_enabled

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

    def talk(
        self,
        initial_data: list[DataSource] | None = None,
        sources: list[str] | None = None,
    ) -> None:
        """Starts an interactive chat session bound to this UnifiedClient."""
        from llm_cli.clients.session import ChatSession

        ChatSession(self).run(initial_data, sources)  # type: ignore

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
