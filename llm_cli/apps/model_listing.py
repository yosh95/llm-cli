# llm_cli/apps/model_listing.py

"""Shared model listing functionality for all LLM providers."""

import argparse
import json
import requests
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from llm_cli.clients.config import get_setting


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

    # Optional: Function to format non-verbose output line
    format_model_line: Optional[Callable[[Dict[str, Any]], str]] = None

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
        print(f"{config.provider_name} API Key not found in config.",
              file=sys.stderr)
        print("Please run 'llm-cli-config' to set it up.", file=sys.stderr)
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
        response = requests.get(api_url,
                                headers=headers,
                                timeout=config.timeout)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching models: {e}", file=sys.stderr)
        sys.exit(1)

    # Parse response
    result = response.json()

    # Check for data in response
    if config.response_data_key not in result:
        print(json.dumps(result, indent=2))
        return

    models = result[config.response_data_key]

    # Handle specific model queries
    if len(args.models) > 0:
        for model in models:
            # Extract model name
            if config.extract_model_name:
                model_name = config.extract_model_name(model)
            else:
                model_name = model.get('id', model.get('name', ''))

            if model_name in args.models:
                print(json.dumps(model, ensure_ascii=False, indent=2))
        return

    # Display all models
    if verbose:
        # Verbose mode: print full JSON
        json_str = json.dumps(result, ensure_ascii=False, indent=2)
        print(json_str)
    else:
        # Non-verbose mode: sort if needed, then display
        if config.sort_key:
            models = sorted(models, key=config.sort_key)

        if config.format_model_line:
            # Provider has custom formatting
            for model in models:
                print(config.format_model_line(model))
        else:
            # Default: just print model names
            for model in models:
                if config.extract_model_name:
                    print(config.extract_model_name(model))
                else:
                    print(model.get('id', model.get('name', 'Unknown')))
