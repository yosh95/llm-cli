from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.unified import UnifiedClient
from llm_cli.clients.registry import client_registry


def test_unified_client_switches_provider_via_alias(mock_config):
    # Create mocks for the clients
    mock_openai_instance = MagicMock()
    mock_gemini_instance = MagicMock()

    mock_openai_class = MagicMock(return_value=mock_openai_instance)
    mock_gemini_class = MagicMock(return_value=mock_gemini_instance)

    # Setup mock attributes
    mock_openai_instance.available_models = {"default": "gpt-4"}
    mock_gemini_instance.available_models = {"default": "gemini-pro"}

    mock_openai_instance.current_alias = "default"
    mock_gemini_instance.current_alias = "default"

    mock_openai_instance.model = "gpt-4"
    mock_gemini_instance.model = "gemini-pro"

    mock_openai_instance.config_section = "openai"
    mock_gemini_instance.config_section = "google"
    mock_openai_instance.pdf_as_base64 = False
    mock_gemini_instance.pdf_as_base64 = True

    # Setup the registry with mocks
    with (
        patch.object(client_registry, "get_client_class") as mock_get_class,
        patch.object(client_registry, "get_config_section") as mock_get_section,
        patch.object(client_registry, "get_provider_info") as mock_get_info,
    ):

        def side_effect_class(alias):
            if alias in ("google", "gemini"):
                return mock_gemini_class
            if alias in ("openai", "gpt"):
                return mock_openai_class
            return None

        def side_effect_section(alias):
            if alias in ("google", "gemini"):
                return "google"
            if alias in ("openai", "gpt"):
                return "openai"
            return None

        mock_get_class.side_effect = side_effect_class
        mock_get_section.side_effect = side_effect_section
        mock_get_info.return_value = {
            "google": "google",
            "gemini": "google",
            "openai": "openai",
            "gpt": "openai",
        }

        # Initialize UnifiedClient with google/gemini initially
        client = UnifiedClient(initial_provider="google", stdout=True)

        # Check initial state
        assert client.current_provider_name == "google"
        assert client.clients["google"] == mock_gemini_instance

        # Switch to OpenAI using /p openai
        client._handle_command("/p openai", None)

        # Check if provider switched
        assert client.current_provider_name == "openai"
        assert "openai" in client.clients
        assert client.clients["openai"] == mock_openai_instance

        # Switch back to Gemini using /provider gemini
        client._handle_command("/provider gemini", None)
        assert (
            client.current_provider_name == "google"
        )  # The config section name is 'google'

        # Switch to OpenAI again using /p openai
        client._handle_command("/p openai", None)
        assert client.current_provider_name == "openai"


if __name__ == "__main__":
    pytest.main([__file__])
