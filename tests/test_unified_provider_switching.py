import pytest
from unittest.mock import patch, MagicMock
from llm_cli.apps.unified import UnifiedClient


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

    # Setup the new PROVIDER_MAP with mocks
    new_provider_map = {
        'google': mock_gemini_class,
        'gemini': mock_gemini_class,
        'openai': mock_openai_class,
        'gpt': mock_openai_class,
        'anthropic': MagicMock(),
        'claude': MagicMock(),
        'xai': MagicMock(),
        'grok': MagicMock(),
    }

    # Patch the PROVIDER_MAP on the UnifiedClient class
    with patch.dict(UnifiedClient.PROVIDER_MAP, new_provider_map):

        # Initialize UnifiedClient with google/gemini initially
        client = UnifiedClient(initial_provider="google", stdout=True)

        # Check initial state
        assert client.current_provider_name == "google"
        # We need to access the client stored in the clients dict, which is the mock
        assert client.clients['google'] == mock_gemini_instance

        # Switch to OpenAI using /gpt alias
        client._handle_command("/gpt", None)

        # Check if provider switched
        assert client.current_provider_name == "openai"
        assert "openai" in client.clients
        assert client.clients['openai'] == mock_openai_instance

        # Switch back to Gemini using /gemini
        client._handle_command("/gemini", None)
        assert client.current_provider_name == "google"  # The config section name is 'google'

        # Switch to OpenAI using /openai
        client._handle_command("/openai", None)
        assert client.current_provider_name == "openai"


if __name__ == "__main__":
    pytest.main([__file__])
