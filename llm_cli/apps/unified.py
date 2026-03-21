# llm_cli/apps/unified.py

from typing import Any, TypeVar

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import config_manager
from llm_cli.clients.registry import client_registry
from llm_cli.modules.models import DataSource
from llm_cli.ui import console

T = TypeVar("T")


class UnifiedClient(BaseLlmClient):
    """
    A unified client capable of switching between multiple
    providers within a single session.

    Uses dynamic delegation to route calls to the active provider's client.
    """

    def __init__(self, initial_provider: str | None = None, **kwargs: Any):
        self.clients: dict[str, BaseLlmClient] = {}
        self.client_kwargs = kwargs
        self._fallback_model_manager: Any = None
        self._fallback_config_manager: Any = None
        self.active_client: BaseLlmClient | None = None

        default_p = config_manager.get("general", "unified_default_provider")
        active_providers = config_manager.get_active_providers()

        if not initial_provider:
            if not default_p or default_p not in active_providers:
                if active_providers:
                    # Fallback to the first active provider
                    # Priority: google -> openai -> anthropic -> xai -> ollama
                    default_p = active_providers[0]
                else:
                    console.print(
                        "[bold red]Error: No active providers found.[/bold red]\n"
                        "Please set an API key environment variable "
                        "(e.g., export GOOGLE_API_KEY='...')."
                    )
                    import sys

                    sys.exit(1)

        initial_provider_name = str(initial_provider or default_p)
        config_section = (
            client_registry.get_config_section(initial_provider_name) or "openai"
        )

        # Initialize as a base client first. This creates the shared managers.
        from llm_cli.clients.base import ProviderSpec

        super().__init__(
            initial_model_alias=kwargs.get("initial_model_alias", "default"),
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section=config_section,
                pdf_as_base64=kwargs.get(
                    "pdf_as_base64",
                    config_manager.get_bool("general", "pdf_as_base64", True),
                ),
            ),
            stdout=kwargs.get("stdout", False),
            render_markdown=kwargs.get("render_markdown", True),
            initial_tools=kwargs.get("initial_tools"),
            disable_system_prompt=kwargs.get("disable_system_prompt", False),
            enable_mcp=kwargs.get("enable_mcp", False),
            live_debug=kwargs.get("live_debug", False),
        )

        # Setup custom command registry for Unified client
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

        self.current_provider_name = initial_provider_name
        self._activate_provider(self.current_provider_name)

    def _activate_provider(self, provider_alias: str) -> bool:
        """Switches the active provider and syncs managers."""
        try:
            client_class = client_registry.get_client_class(provider_alias)
            config_section = client_registry.get_config_section(provider_alias)
        except ImportError as e:
            if any(
                pkg in str(e)
                for pkg in ["torch", "tiktoken", "transformers", "accelerate"]
            ):
                console.print(
                    f"[red]Error: {provider_alias} client could not be loaded: {e}"
                    "[/red]"
                )
                console.print(
                    "[yellow]Hint: Run: pip install torch transformers "
                    "accelerate bitsandbytes[/yellow]"
                )
            else:
                console.print(
                    f"[red]Error loading provider {provider_alias}: {e}[/red]"
                )
            return False

        if not client_class or not config_section:
            return False

        if config_section not in self.clients:
            # Pass our shared managers to new client for seamless state sharing.
            self.clients[config_section] = client_class(
                **self.client_kwargs,
                session_manager=self._session_manager,
                tool_manager=self._tool_manager,
                logging_manager=self._logging_manager,
                media_manager=self._media_manager,
            )

        self.active_client = self.clients[config_section]

        # Update own state from active client
        self.current_provider_name = config_section
        self.config_section = self.active_client.config_section
        self.api_key = self.active_client.api_key

        return True

    # --- Property Overrides for Delegation ---

    @property
    def _model_manager(self) -> Any:
        return (
            self.active_client._model_manager
            if self.active_client
            else self._fallback_model_manager
        )

    @_model_manager.setter
    def _model_manager(self, value: Any) -> None:
        if self.active_client:
            self.active_client._model_manager = value
        else:
            self._fallback_model_manager = value

    @property
    def _config_manager(self) -> Any:
        return (
            self.active_client._config_manager
            if self.active_client
            else self._fallback_config_manager
        )

    @_config_manager.setter
    def _config_manager(self, value: Any) -> None:
        if self.active_client:
            self.active_client._config_manager = value
        else:
            self._fallback_config_manager = value

    @property
    def pdf_as_base64(self) -> bool:
        return (
            self.active_client.pdf_as_base64
            if self.active_client
            else super().pdf_as_base64
        )

    @pdf_as_base64.setter
    def pdf_as_base64(self, value: bool) -> None:
        if self.active_client:
            self.active_client.pdf_as_base64 = value
        self.preferred_pdf_as_base64 = value

    def _handle_provider_command(self, ctx: Any) -> bool:
        """Handler for the /provider command."""
        args = ctx.args
        active_providers = config_manager.get_active_providers()

        if not args:
            from rich.table import Table

            table = Table(
                title="Active Providers",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Status", justify="center", width=4)
            table.add_column("Alias", style="cyan", width=15)
            table.add_column("Config Section", style="dim")

            info = client_registry.get_provider_info()
            for alias in sorted(info.keys()):
                section = info[alias]
                # Filter by active providers only
                if section not in active_providers:
                    continue

                is_active = section == self.current_provider_name
                active_mark = "[bold green]*[/bold green]" if is_active else ""
                table.add_row(active_mark, alias, section)

            console.print(table)
            console.print("[dim]Usage: /p <alias> to switch provider[/dim]")
            return True

        if (
            args not in active_providers
            and client_registry.get_config_section(args) not in active_providers
        ):
            msg = f"[red]Error: {args} is inactive (API Key missing).[/red]"
            console.print(msg)
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
        """Delegate send to active client."""
        if not self.active_client:
            raise RuntimeError("No active provider client.")
        return self.active_client._send(data)


def main() -> None:
    config = ClientConfig(
        client_class=UnifiedClient,
        description="Unified LLM CLI with multi-provider support",
        supports_provider_selection=True,
        provider_choices=client_registry.list_aliases(),
    )
    run_client_cli(config)


if __name__ == "__main__":
    main()
