# llm_cli/apps/model_listing.py

"""Shared model listing functionality for all LLM providers."""

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests
from rich.console import Console
from rich.table import Table

from llm_cli.clients.config import get_setting

console = Console()


@dataclass
class ModelListingConfig:
    """Configuration for provider-specific model listing."""

    provider_name: str  # Display name (e.g., "Google", "OpenAI")
    config_section: str  # Config section name (e.g., "google", "openai")
    api_key_setting: str  # API key setting name (e.g., "api_key")
    api_url: str  # Base API URL
    response_data_key: str  # Key in response JSON ('models' or 'data')

    # Optional: Function to build headers from API key
    build_headers: Optional[Callable[[str], Dict[str, str]]] = None

    # Optional: Function to build URL from API key (for key-in-URL patterns)
    build_url: Optional[Callable[[str, str], str]] = None

    # Optional: Function to extract model name from model object
    extract_model_name: Optional[Callable[[Dict[str, Any]], str]] = None

    # Optional: Function to format non-verbose output line (deprecated)
    format_model_line: Optional[Callable[[Dict[str, Any]], str]] = None

    # Optional: Define columns for the table [(Header, Key/Callable)]
    columns: Optional[List[tuple[str, Any]]] = None

    # Optional: Function to get sort key from model object
    sort_key: Optional[Callable[[Dict[str, Any]], Any]] = None

    # Optional: Timeout for API request
    timeout: int = 10


def create_model_listing_parser() -> argparse.ArgumentParser:
    """Create standard argument parser for model listing tools."""
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*")
    parser.add_argument("-v", action="store_true", help="Verbose output")
    return parser


def list_models(config: ModelListingConfig) -> None:
    """
    Generic model listing implementation.

    Fetches and displays models from an LLM provider API based on the
    provided configuration.

    Args:
        config: ModelListingConfig with provider-specific details
    """
    # Get API key
    api_key = get_setting(config.api_key_setting, config.config_section)
    if api_key is None:
        console.print(f"[red]{config.provider_name} API Key not found in config.[/red]")
        console.print("[yellow]Please run 'llm-cli-config' to set it up.[/yellow]")
        sys.exit(1)

    # Parse arguments
    parser = create_model_listing_parser()
    args = parser.parse_args()
    verbose = args.v

    # Build URL
    if config.build_url:
        api_url = config.build_url(config.api_url, api_key)
    else:
        api_url = config.api_url

    # Build headers
    if config.build_headers:
        headers = config.build_headers(api_key)
    else:
        headers = {}

    # Make API request
    try:
        response = requests.get(api_url, headers=headers, timeout=config.timeout)
        response.raise_for_status()
    except Exception as e:
        console.print(f"[bold red]Error fetching models: {e}[/bold red]")
        sys.exit(1)

    # Parse response
    result = response.json()

    # Check for data in response
    if config.response_data_key not in result:
        console.print_json(data=result)
        return

    models = result[config.response_data_key]

    # Handle specific model queries
    if len(args.models) > 0:
        for model in models:
            # Extract model name
            if config.extract_model_name:
                model_name = config.extract_model_name(model)
            else:
                model_name = model.get("id", model.get("name", ""))

            if model_name in args.models:
                console.print_json(data=model)
        return

    # Sort models by name
    def get_model_name(m: Dict[str, Any]) -> str:
        if config.extract_model_name:
            return config.extract_model_name(m)
        return str(m.get("id", m.get("name", "")))

    models = sorted(models, key=get_model_name)

    # Display all models
    if verbose:
        # Display detailed table
        table = Table(title=f"{config.provider_name} Models")

        # Determine columns
        display_columns = config.columns or [("Model Name", "id")]

        for header, _ in display_columns:
            # Using overflow="fold" to wrap long IDs without truncation
            table.add_column(
                header,
                style="cyan" if "Name" in header or "ID" in header else "magenta",
                overflow="fold",
            )

        for model in models:
            row_data = []
            for header, key_or_func in display_columns:
                if callable(key_or_func):
                    val = key_or_func(model)
                elif isinstance(key_or_func, str):
                    val = model.get(key_or_func, "N/A")
                else:
                    val = str(key_or_func)
                row_data.append(str(val))
            table.add_row(*row_data)

        console.print(table)
    else:
        # Display model names only
        for model in models:
            console.print(get_model_name(model))
