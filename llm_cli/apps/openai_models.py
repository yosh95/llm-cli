#!/usr/bin/env python3

import datetime

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main():
    """List available OpenAI models."""

    def format_openai_model(model):
        """Format OpenAI model with name and creation timestamp."""
        created_datetime = datetime.datetime.fromtimestamp(model['created'])
        formatted_created = created_datetime.strftime('%Y/%m/%d %H:%M:%S')
        return f"{model['id']}: {formatted_created}"

    config = ModelListingConfig(
        provider_name="OpenAI",
        config_section="openai",
        api_key_setting="api_key",
        api_url="https://api.openai.com/v1/models",
        response_data_key="data",
        # OpenAI uses Bearer token authentication
        build_headers=lambda api_key: {"Authorization": f"Bearer {api_key}"},
        # Model name is 'id' field
        extract_model_name=lambda model: model['id'],
        # Non-verbose: print name and creation timestamp
        format_model_line=format_openai_model,
        # Sort by creation timestamp
        sort_key=lambda model: model['created'],
        timeout=10
    )

    list_models(config)


if __name__ == '__main__':
    main()
