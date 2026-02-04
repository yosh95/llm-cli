#!/usr/bin/env python3

import datetime

from llm_cli.apps.model_listing import ModelListingConfig, list_models
from llm_cli.clients.config import get_setting


def main():
    """List available vLLM models."""

    def format_epoch(model):
        created = model.get("created")
        if created:
            return datetime.datetime.fromtimestamp(created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return "N/A"

    # Load custom API URL from config or use default
    config_url = get_setting("api_url", "vllm")
    base_url = config_url if config_url else "http://localhost:8000/v1/chat/completions"

    # Adjust URL to point to /v1/models instead of /chat/completions
    if "/chat/completions" in base_url:
        models_url = base_url.replace("/chat/completions", "/models")
    else:
        # Fallback if the user set a custom base URL without endpoint
        models_url = f"{base_url.rstrip('/')}/models"

    config = ModelListingConfig(
        provider_name="vLLM",
        config_section="vllm",
        api_key_setting="api_key",
        api_url=models_url,
        response_data_key="data",
        build_headers=lambda api_key: {"Authorization": f"Bearer {api_key or 'EMPTY'}"},
        extract_model_name=lambda model: model["id"],
        columns=[
            ("Model ID", "id"),
            ("Owned By", "owned_by"),
            ("Created", format_epoch),
        ],
        sort_key=lambda model: model["id"],
        timeout=5,
    )

    list_models(config)


if __name__ == "__main__":
    main()
