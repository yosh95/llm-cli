# llm_cli/apps/model_listing.py

"""
Unified model listing functionality for all LLM providers.
Provides a single CLI command to list available models for any provider.
"""

import argparse
import datetime
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests
from rich.table import Table

from llm_cli.clients.config import config_manager
from llm_cli.security.permissions import setup_permissions
from llm_cli.ui import console


@dataclass
class ModelListingConfig:
    """Configuration for provider-specific model listing."""

    provider_name: str
    config_section: str
    api_key_setting: str
    api_url: str
    response_data_key: str
    build_headers: Callable[[str], dict[str, str]] | None = None
    build_url: Callable[[str, str], str] | None = None
    extract_model_name: Callable[[dict[str, Any]], str] | None = None
    columns: list[tuple[str, Any]] | None = None
    sort_key: Callable[[dict[str, Any]], Any] | None = None
    timeout: int = 10


# --- Provider Configurations ---


def get_openai_config() -> ModelListingConfig:
    def format_epoch(model: dict) -> str:
        created = model.get("created")
        if created:
            return datetime.datetime.fromtimestamp(created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return "N/A"

    return ModelListingConfig(
        provider_name="OpenAI",
        config_section="openai",
        api_key_setting="api_key",
        api_url="https://api.openai.com/v1/models",
        response_data_key="data",
        build_headers=lambda api_key: {"Authorization": f"Bearer {api_key}"},
        extract_model_name=lambda model: model["id"],
        columns=[
            ("Model ID", "id"),
            ("Owned By", "owned_by"),
            ("Created", format_epoch),
        ],
        sort_key=lambda model: model["id"],
    )


def get_anthropic_config() -> ModelListingConfig:
    return ModelListingConfig(
        provider_name="Anthropic",
        config_section="anthropic",
        api_key_setting="api_key",
        api_url="https://api.anthropic.com/v1/models",
        response_data_key="data",
        build_headers=lambda api_key: {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        extract_model_name=lambda model: model["id"],
        columns=[
            ("Model ID", "id"),
            ("Display Name", "display_name"),
            ("Created At", "created_at"),
        ],
        sort_key=lambda model: model.get("created_at", ""),
    )


def get_google_config() -> ModelListingConfig:
    return ModelListingConfig(
        provider_name="Google",
        config_section="google",
        api_key_setting="api_key",
        api_url="https://generativelanguage.googleapis.com/v1beta/models",
        response_data_key="models",
        build_headers=lambda api_key: {"x-goog-api-key": api_key},
        extract_model_name=lambda model: model["name"].split("/")[1],
        columns=[
            ("Model ID", lambda m: m["name"].split("/")[1]),
            ("Display Name", "displayName"),
            ("Input Limit", "inputTokenLimit"),
            ("Output Limit", "outputTokenLimit"),
        ],
        sort_key=lambda model: model["name"],
    )


def get_xai_config() -> ModelListingConfig:
    def format_epoch(model: dict) -> str:
        created = model.get("created")
        if created:
            return datetime.datetime.fromtimestamp(created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return "N/A"

    return ModelListingConfig(
        provider_name="xAI",
        config_section="xai",
        api_key_setting="api_key",
        api_url="https://api.x.ai/v1/models",
        response_data_key="data",
        build_headers=lambda api_key: {"Authorization": f"Bearer {api_key}"},
        extract_model_name=lambda model: model["id"],
        columns=[
            ("Model ID", "id"),
            ("Owned By", "owned_by"),
            ("Created", format_epoch),
        ],
        sort_key=lambda model: model["id"],
    )


def get_ollama_config() -> ModelListingConfig:
    api_url = (
        config_manager.get("ollama", "api_url")
        or "http://localhost:11434/v1/chat/completions"
    )
    if "/v1" in api_url:
        base_url = api_url.split("/v1")[0]
    else:
        from urllib.parse import urlparse

        parsed = urlparse(api_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    tags_url = f"{base_url}/api/tags"

    def format_size(model: dict) -> str:
        size_bytes = model.get("size", 0)
        return f"{size_bytes / (1024**3):.2f} GB"

    def format_modified(model: dict) -> str:
        modified = str(model.get("modified_at", ""))
        return modified[:19].replace("T", " ")

    return ModelListingConfig(
        provider_name="Ollama",
        config_section="ollama",
        api_key_setting="api_key",
        api_url=tags_url,
        response_data_key="models",
        extract_model_name=lambda model: model["name"],
        columns=[
            ("Model Name", "name"),
            ("Size", format_size),
            ("Modified", format_modified),
        ],
    )


MODEL_LISTING_REGISTRY: dict[str, Callable[[], ModelListingConfig]] = {
    "openai": get_openai_config,
    "gpt": get_openai_config,
    "anthropic": get_anthropic_config,
    "claude": get_anthropic_config,
    "google": get_google_config,
    "gemini": get_google_config,
    "xai": get_xai_config,
    "grok": get_xai_config,
    "ollama": get_ollama_config,
}


def list_models(config: ModelListingConfig, args: argparse.Namespace) -> None:
    """Generic model listing implementation."""
    api_key = config_manager.get(config.config_section, config.api_key_setting)
    if api_key is None and config.config_section not in ("ollama",):
        console.print(f"[red]{config.provider_name} API Key not found.[/red]")
        console.print(
            "[yellow]Please set the appropriate environment variable "
            "(e.g., export OPENAI_API_KEY='...').[/yellow]"
        )
        return

    api_url = (
        config.build_url(config.api_url, api_key or "")
        if config.build_url
        else config.api_url
    )
    headers = config.build_headers(api_key or "") if config.build_headers else {}
    headers["Connection"] = "close"

    try:
        response = requests.get(api_url, headers=headers, timeout=config.timeout)
        response.raise_for_status()
    except Exception as e:
        msg = (
            f"[bold red]Error fetching models for "
            f"{config.provider_name}: {e}[/bold red]"
        )
        console.print(msg)
        return

    result = response.json()
    if config.response_data_key not in result:
        console.print_json(data=result)
        return

    models = result[config.response_data_key]

    if len(args.models) > 0:
        for model in models:
            model_name = (
                config.extract_model_name(model)
                if config.extract_model_name
                else model.get("id", model.get("name", ""))
            )
            if model_name in args.models:
                console.print_json(data=model)
        return

    def get_model_name(m: dict[str, Any]) -> str:
        if config.extract_model_name:
            return config.extract_model_name(m)
        return str(m.get("id", m.get("name", "")))

    models = sorted(models, key=get_model_name)

    if args.v:
        table = Table(title=f"{config.provider_name} Models")
        display_columns = config.columns or [("Model Name", "id")]
        for header, _ in display_columns:
            table.add_column(
                header,
                style="cyan" if "Name" in header or "ID" in header else "magenta",
                overflow="fold",
            )
        for model in models:
            row_data = []
            for _, key_or_func in display_columns:
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
        for model in models:
            console.print(get_model_name(model))


def main() -> None:
    # Enforce strict user-only permissions and set umask
    setup_permissions()

    parser = argparse.ArgumentParser(description="Unified LLM Model Listing CLI")
    parser.add_argument(
        "provider",
        nargs="?",
        help=(
            f"Provider to list models for ({', '.join(sorted(MODEL_LISTING_REGISTRY))})"
        ),
    )
    parser.add_argument(
        "models", nargs="*", help="Specific models to show detail for (JSON)"
    )
    parser.add_argument("-v", action="store_true", help="Verbose output (table format)")

    args = parser.parse_args()

    if not args.provider:
        parser.print_help()
        sys.exit(0)

    provider = args.provider.lower()
    if provider not in MODEL_LISTING_REGISTRY:
        console.print(f"[bold red]Error: Unknown provider '{provider}'.[/bold red]")
        available = ", ".join(sorted(MODEL_LISTING_REGISTRY.keys()))
        console.print(f"Available providers: {available}")
        sys.exit(1)

    config_factory = MODEL_LISTING_REGISTRY[provider]
    config = config_factory()
    list_models(config, args)


if __name__ == "__main__":
    main()
