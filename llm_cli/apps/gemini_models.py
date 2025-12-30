#!/usr/bin/env python3

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main():
    """List available Google Gemini models."""

    config = ModelListingConfig(
        provider_name="Google",
        config_section="google",
        api_key_setting="api_key",
        api_url="https://generativelanguage.googleapis.com/v1beta/models",
        response_data_key="models",
        # Gemini uses x-goog-api-key header authentication
        build_headers=lambda api_key: {'x-goog-api-key': api_key},
        # Extract model name from 'name' field (format: "models/gemini-...")
        extract_model_name=lambda model: model['name'].split("/")[1],
        # Non-verbose: just print model name
        format_model_line=lambda model: model['name'].split("/")[1],
        # Sort by model name
        sort_key=lambda model: model['name'],
        timeout=10
    )

    list_models(config)


if __name__ == '__main__':
    main()
