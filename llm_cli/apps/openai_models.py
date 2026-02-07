#!/usr/bin/env python3

import datetime

from llm_cli.apps.model_listing import ModelListingConfig, list_models


def main() -> None:
    """List available OpenAI models."""

    def format_epoch(model: dict) -> str:
        created = model.get("created")
        if created:
            return datetime.datetime.fromtimestamp(created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return "N/A"

    config = ModelListingConfig(
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
        timeout=10,
    )

    list_models(config)


if __name__ == "__main__":
    main()
