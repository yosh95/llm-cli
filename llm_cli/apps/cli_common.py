# llm_cli/apps/cli_common.py

"""Shared CLI entry point functionality for all LLM clients."""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Type

from rich.markup import escape
from llm_cli.clients.base import BaseLlmClient, ProviderSwitchRequest, console


@dataclass
class ClientConfig:
    """Configuration for CLI entry point."""

    client_class: Type[BaseLlmClient]  # The client class to instantiate
    description: str  # CLI description for argparse

    supports_provider_selection: bool = False  # For UnifiedClient
    extra_args: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)


def create_standard_parser(config: ClientConfig) -> argparse.ArgumentParser:
    """
    Create standard argument parser with common options.

    Args:
        config: ClientConfig with provider-specific details

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description=config.description,
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Common positional arguments
    parser.add_argument(
        'sources',
        nargs='*',
        help="Sources for the prompt (text, files, URLs). "
             "If no sources are provided, starts interactive mode."
    )

    # Common optional arguments
    parser.add_argument(
        '-m', '--model',
        default='default',
        help="Specify the model alias to use (default: 'default')"
    )

    parser.add_argument(
        '-t', '--tools',
        action='append',
        help="Enable a specific tool on startup (e.g., -t search). "
             "Can be used multiple times."
    )

    # Provider selection for UnifiedClient
    if config.supports_provider_selection:
        parser.add_argument(
            '-p', '--provider',
            choices=['google',
                     'gemini',
                     'openai',
                     'anthropic',
                     'claude',
                     'xai',
                     'grok'],
            help="Specify the provider to use "
                 "(default: from config or 'gemini')"
        )

    # Output control arguments
    parser.add_argument(
        '-s', '--stdout',
        action='store_true',
        help="Print response to stdout and exit (non-interactive mode)"
    )

    parser.add_argument(
        '--raw',
        action='store_true',
        help="Disable Markdown rendering in output"
    )

    parser.add_argument(
        '--no-system-prompt',
        action='store_true',
        help="Disable system prompt even if configured"
    )

    # MCP Server Mode
    parser.add_argument(
        '--mcp-server',
        action='store_true',
        help="Run as an MCP server to expose tools to other clients"
    )

    # Add any provider-specific extra arguments
    for arg_name, arg_config in config.extra_args:
        parser.add_argument(arg_name, **arg_config)

    return parser


def run_client_cli(config: ClientConfig) -> None:
    """
    Standard CLI entry point logic for all clients.

    Handles:
    - Argument parsing
    - Client instantiation
    - stdin input detection and processing
    - Mode selection (interactive vs one-shot)

    Args:
        config: ClientConfig with provider-specific details
    """
    # Parse arguments
    parser = create_standard_parser(config)
    args = parser.parse_args()

    # Handle MCP Server mode if requested
    if args.mcp_server:
        try:
            from llm_cli.apps.mcp_server import main as run_mcp_server
            run_mcp_server()
            sys.exit(0)
        except ImportError:
            console.print(
                "[red]Error: 'mcp' package is not installed.[/red]\n"
                "Please install it with: pip install 'mcp>=1.0.0'"
            )
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Failed to start MCP server: {e}[/red]")
            sys.exit(1)

    # Determine output mode
    stdout = args.stdout or not sys.stdin.isatty()
    render_markdown = not args.raw

    # Build client kwargs from args
    client_kwargs = {
        'initial_model_alias': args.model,
        'stdout': stdout,
        'render_markdown': render_markdown,
        'initial_tools': args.tools,
        'disable_system_prompt': args.no_system_prompt,
    }

    # Add optional capabilities if supported
    if config.supports_provider_selection and \
            hasattr(args, 'provider') and args.provider:
        client_kwargs['initial_provider'] = args.provider

    # Instantiate client
    client = config.client_class(**client_kwargs)

    try:
        # Handle input sources
        if not sys.stdin.isatty():
            # stdin is being piped in
            stdin_input = sys.stdin.read().strip()
            if stdin_input:
                # Combine stdin with command-line sources
                all_sources = [stdin_input] + args.sources
                client.process_sources(all_sources)
            elif args.sources:
                # Only command-line sources, no stdin
                client.process_sources(args.sources)
            else:
                # No input at all (shouldn't happen, but handle gracefully)
                client.talk()
        elif args.sources:
            # Command-line sources provided, process them
            client.process_sources(args.sources)
        else:
            # No sources provided, start interactive mode
            client.talk()
    except ProviderSwitchRequest as e:
        console.print(
            f"[bold red]Switching to provider '{escape(e.provider)}' "
            "is not supported in this specific tool.[/bold red]"
        )
        console.print(
            "Please use the [bold cyan]llm-unified[/bold cyan] command "
            "for dynamic provider switching."
        )
        sys.exit(0)
