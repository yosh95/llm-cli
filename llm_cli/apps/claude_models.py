#!/usr/bin/env python3

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main():
    """List available Claude models."""

    config = ModelListingConfig(
        provider_name="Anthropic",
        config_section="anthropic",
        api_key_setting="api_key",
        api_url="https://api.anthropic.com/v1/models",
        response_data_key="data",
        build_headers=lambda api_key: {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        extract_model_name=lambda model: model['id'],
        columns=[
            ("Model ID", "id"),
            ("Display Name", "display_name"),
            ("Created At", "created_at"),
        ],
        sort_key=lambda model: model.get('created_at', ''),
        timeout=10
    )

    list_models(config)


if __name__ == '__main__':
    main()
