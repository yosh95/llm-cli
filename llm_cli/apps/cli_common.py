# llm_cli/apps/cli_common.py

"""Shared CLI entry point functionality for all LLM clients."""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from rich.markup import escape

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.exceptions import ProviderSwitchRequest
from llm_cli.modules.tool_registry import registry
from llm_cli.ui import console


@dataclass
class ClientConfig:
    """Configuration for CLI entry point."""

    client_class: type[BaseLlmClient]
    description: str
    supports_provider_selection: bool = False
    provider_choices: list[str] | None = None
    extra_args: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


def create_standard_parser(config: ClientConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=config.description, formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("sources", nargs="*", help="Sources (text, files, URLs).")
    parser.add_argument(
        "-m", "--model", default="default", help="Model alias (default: 'default')"
    )

    if config.supports_provider_selection:
        from llm_cli.clients.registry import client_registry

        parser.add_argument(
            "-p",
            "--provider",
            choices=config.provider_choices or client_registry.list_aliases(),
            help="Provider to use",
        )

    parser.add_argument(
        "-s", "--stdout", action="store_true", help="Print to stdout and exit"
    )
    parser.add_argument("--raw", action="store_true", help="Disable Markdown rendering")
    parser.add_argument("--mcp", action="store_true", help="Enable MCP integration")
    parser.add_argument(
        "--mcp-server", action="store_true", help="Run as an MCP server"
    )
    parser.add_argument("--session", help="Load a saved session JSON file on startup")

    for arg_name, arg_config in config.extra_args:
        parser.add_argument(arg_name, **arg_config)

    return parser


def run_client_cli(config: ClientConfig) -> None:
    parser = create_standard_parser(config)
    args = parser.parse_args()

    from llm_cli.apps.configure import init_config
    from llm_cli.clients.config import config_manager
    from llm_cli.consts import CONFIG_FILE_PATH
    from llm_cli.security.integrity import verify_installation

    # Automatically initialize configuration if it doesn't exist
    if not CONFIG_FILE_PATH.exists():
        init_config()

    # Verify system integrity (Checks manifest, audit logs, etc.)
    verify_installation()

    # Check for at least one active provider
    active_providers = config_manager.get_active_providers()
    if not active_providers:
        console.print("[bold red]Error: No active LLM providers found.[/bold red]")
        console.print(
            "\nPlease set an API key environment variable for at least one provider:"
        )
        console.print("  - [cyan]GEMINI_API_KEY[/cyan] (or GOOGLE_API_KEY)")
        console.print("  - [cyan]OPENAI_API_KEY[/cyan]")
        console.print("  - [cyan]ANTHROPIC_API_KEY[/cyan]")
        console.print("  - [cyan]XAI_API_KEY[/cyan]")
        console.print("  - [cyan]OLLAMA_API_KEY[/cyan] (required for remote Ollama)")
        console.print(
            "\n[yellow]Note: Ollama is available without a key if hosted on "
            "localhost.[/yellow]"
        )
        sys.exit(1)

    if args.stdout and args.mcp:
        console.print("[red]Error: --stdout and --mcp cannot be used together.[/red]")
        sys.exit(1)

    if args.stdout and args.mcp_server:
        console.print(
            "[red]Error: --stdout and --mcp-server cannot be used together.[/red]"
        )
        sys.exit(1)

    # Check if MCP module is installed when --mcp or --mcp-server is used
    if args.mcp or args.mcp_server:
        # Custom MCP implementation used on Termux
        pass

    if args.mcp_server:
        try:
            from llm_cli.apps.mcp_server import main as run_mcp_server

            run_mcp_server()
            sys.exit(0)
        except (ImportError, Exception) as e:
            console.print(f"[red]Failed to start MCP server: {e}[/red]")
            sys.exit(1)

    stdout = args.stdout or not sys.stdin.isatty()

    initial_tools: list[str] | None = None
    enable_mcp = args.mcp

    if stdout:
        enable_mcp = False
        initial_tools = []

    client_kwargs = {
        "initial_model_alias": args.model,
        "stdout": stdout,
        "render_markdown": not args.raw,
        "initial_tools": initial_tools,
        "disable_system_prompt": False,
        "enable_mcp": enable_mcp,
        "live_debug": False,
    }

    if config.supports_provider_selection and getattr(args, "provider", None):
        client_kwargs["initial_provider"] = args.provider

    client = config.client_class(**client_kwargs)

    if args.session:
        client.load_session(args.session)

    try:
        if not sys.stdin.isatty():
            stdin_input = sys.stdin.read().strip()
            all_sources = ([stdin_input] if stdin_input else []) + args.sources
            if all_sources:
                client.process_sources(all_sources)
            else:
                client.talk()
        elif args.sources:
            client.process_sources(args.sources)
        else:
            if stdout:
                console.print("[red]Error: --stdout requires input[/red]")
                console.print("[red](from stdin or arguments).[/red]")
                sys.exit(1)
            client.talk()
    except ProviderSwitchRequest as e:
        console.print(
            f"[bold red]Switching to provider '{escape(e.provider)}' "
            "is not supported here.[/bold red]"
        )
        console.print("Use [bold cyan]llm-cli[/bold cyan] for switching.")
        sys.exit(0)
    finally:
        # Ensure all resources (like browser sessions) are cleaned up on exit.
        registry.shutdown()
