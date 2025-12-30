#!/usr/bin/env python3

import datetime

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main():
    """List available Claude models."""

    def format_claude_model(model):
        """Format Claude model with name, creation time, and display name."""
        created_at = model.get('created_at')
        if created_at:
            dt = datetime.datetime.fromisoformat(
                created_at.replace('Z', '+00:00'))
            date_str = dt.strftime('%Y/%m/%d %H:%M')
        else:
            date_str = "Unknown"
        return f"{model['id']}: {date_str} ({model.get('display_name', '')})"

    config = ModelListingConfig(
        provider_name="Anthropic",
        config_section="anthropic",
        api_key_setting="api_key",
        api_url="https://api.anthropic.com/v1/models",
        response_data_key="data",
        # Claude uses x-api-key header with anthropic-version
        build_headers=lambda api_key: {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        # Model name is 'id' field
        extract_model_name=lambda model: model['id'],
        # Non-verbose: print name, creation time, and display name
        format_model_line=format_claude_model,
        # Sort by creation date
        sort_key=lambda model: model.get('created_at', ''),
        timeout=10
    )

    list_models(config)


if __name__ == '__main__':
    main()
