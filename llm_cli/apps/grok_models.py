#!/usr/bin/env python3

import datetime

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main():
    """List available Grok models."""

    def format_grok_model(model):
        """Format Grok model with name, creation time, and owner."""
        created = model.get('created')
        if created:
            dt = datetime.datetime.fromtimestamp(created)
            date_str = dt.strftime('%Y/%m/%d %H:%M')
        else:
            date_str = "-"
        return f"{model['id']}: {date_str} by {model.get('owned_by', 'xai')}"

    config = ModelListingConfig(
        provider_name="xAI",
        config_section="xai",
        api_key_setting="api_key",
        api_url="https://api.x.ai/v1/models",
        response_data_key="data",
        # Grok uses Bearer token authentication
        build_headers=lambda api_key: {"Authorization": f"Bearer {api_key}"},
        # Model name is 'id' field
        extract_model_name=lambda model: model['id'],
        # Non-verbose: print name, creation time, and owner
        format_model_line=format_grok_model,
        # Sort by creation timestamp
        sort_key=lambda model: model.get('created', 0),
        timeout=10
    )

    list_models(config)


if __name__ == '__main__':
    main()
