#!/usr/bin/env python3

from llm_cli.apps.model_listing import ModelListingConfig, list_models
from llm_cli.clients.config import get_setting


def main() -> None:
    """List available Ollama models."""

    # Determine API URL
    api_url = (
        get_setting("api_url", "ollama") or "http://localhost:11434/v1/chat/completions"
    )

    # Convert chat completions URL to tags URL
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

    config = ModelListingConfig(
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
        timeout=10,
    )

    list_models(config)


if __name__ == "__main__":
    main()
