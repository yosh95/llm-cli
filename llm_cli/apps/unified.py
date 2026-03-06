# llm_cli/apps/unified.py

from typing import Any

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.clients.config import get_setting
from llm_cli.clients.registry import client_registry
from llm_cli.modules.models import DataSource, Message


class UnifiedClient(BaseLlmClient):
    """
    A unified client capable of switching between multiple
    providers within a single session.
    """

    def __init__(self, initial_provider: str | None = None, **kwargs: Any):
        self.clients: dict[str, BaseLlmClient] = {}
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

        self.current_provider_name = str(initial_provider or default_p)
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
        self.active_client.conversation = self.conversation

    def __getattr__(self, name: str) -> Any:
        """Delegate any unknown attributes to the active client."""
        if "active_client" in self.__dict__:
            return getattr(self.active_client, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    @property
    def model(self) -> str:
        return self.active_client.model

    @model.setter
    def model(self, value: str) -> None:
        self.active_client.model = value

    @property
    def available_models(self) -> dict[str, Any]:
        return self.active_client.available_models

    @available_models.setter
    def available_models(self, value: dict[str, Any]) -> None:
        self.active_client.available_models = value

    @property
    def current_alias(self) -> str:
        return self.active_client.current_alias

    @current_alias.setter
    def current_alias(self, value: str) -> None:
        self.active_client.current_alias = value

    @property
    def conversation(self) -> list[Message]:
        return getattr(self, "_conversation", [])

    @conversation.setter
    def conversation(self, value: list[Message]) -> None:
        self._conversation = value
        if hasattr(self, "active_client"):
            self.active_client.conversation = value

    @property
    def live_debug(self) -> bool:
        return getattr(self, "_live_debug", False)

    @live_debug.setter
    def live_debug(self, value: bool) -> None:
        self._live_debug = value
        if hasattr(self, "active_client"):
            self.active_client.live_debug = value

    @property
    def tools_enabled(self) -> bool:
        return getattr(self, "_tools_enabled", True)

    @tools_enabled.setter
    def tools_enabled(self, value: bool) -> None:
        self._tools_enabled = value
        if hasattr(self, "active_client"):
            self.active_client.tools_enabled = value

    def _activate_provider(self, provider_alias: str) -> bool:
        try:
            client_class = client_registry.get_client_class(provider_alias)
            config_section = client_registry.get_config_section(provider_alias)
        except ImportError as e:
            if "torch" in str(e) or "tiktoken" in str(e):
                console.print(
                    f"[red]Error: {provider_alias} client could not be loaded: {e}"
                    "[/red]"
                )
                console.print("[yellow]Hint: Run: pip install torch tiktoken[/yellow]")
            else:
                console.print(
                    f"[red]Error loading provider {provider_alias}: {e}[/red]"
                )
            return False

        if not client_class or not config_section:
            return False

        if config_section not in self.clients:
            self.clients[config_section] = client_class(**self.client_kwargs)

        self.active_client = self.clients[config_section]

        # Sync attributes
        for attr in ["live_debug", "tools_enabled", "conversation", "active_tools"]:
            if hasattr(self, attr):
                setattr(self.active_client, attr, getattr(self, attr))

        # Update own state from active client
        self.current_provider_name = config_section
        self.config_section = self.active_client.config_section
        self.pdf_as_base64 = self.active_client.pdf_as_base64

        return True

    def _load_model_aliases(self) -> None:
        """Delegate to the active client."""
        if hasattr(self, "active_client"):
            self.active_client._load_model_aliases()

    def set_model(self, alias: str) -> bool:
        """Delegate to the active client."""
        return self.active_client.set_model(alias)

    def set_custom_model(self, model_name: str) -> None:
        """Delegate to the active client."""
        self.active_client.set_custom_model(model_name)

    def _process_single_source(self, source: str) -> DataSource | None:
        """Delegate to the active client."""
        return self.active_client._process_single_source(source)

    def clear_history(self) -> None:
        """Delegate to the active client."""
        self.active_client.clear_history()

    def get_conversation_state(self) -> dict[str, Any]:
        """Delegate to the active client."""
        return self.active_client.get_conversation_state()

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        """Delegate to the active client."""
        self.active_client.set_conversation_state(state)

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        if not user_input.startswith("/"):
            return False

        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("p", "provider"):
            if not args:
                console.print("[bold]Available Providers:[/bold]")
                seen_sections = set()
                for alias, section in client_registry.get_provider_info().items():
                    if section not in seen_sections:
                        active = "*" if section == self.current_provider_name else " "
                        console.print(
                            f" {active} [cyan]{alias:15}[/cyan] -> [dim]{section}[/dim]"
                        )
                        seen_sections.add(section)
                return True

            if self._activate_provider(args):
                console.print(
                    f"[cyan]Switched to provider: {args} (Model: {self.model})[/cyan]"
                )
                return True
            else:
                console.print(f"[red]Unknown or unavailable provider: {args}[/red]")
                return True

        return super()._handle_command(user_input, sources, pending_data)

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        # Ensure all synced state is up to date before sending
        self.active_client.active_tools = self.active_tools
        self.active_client.conversation = self.conversation
        self.active_client.live_debug = self.live_debug
        self.active_client.tools_enabled = self.tools_enabled
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
