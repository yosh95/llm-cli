from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.unified import UnifiedClient
from llm_cli.clients.command_handler import CommandContext, handle_provider
from llm_cli.clients.registry import client_registry
from llm_cli.clients.session import ChatSession


def test_unified_client_initialization(mock_config):
    """Test that UnifiedClient correctly initializes the initial specific client."""
    mock_gemini_instance = MagicMock()
    mock_gemini_class = MagicMock(return_value=mock_gemini_instance)

    with patch.object(
        client_registry, "get_client_class", return_value=mock_gemini_class
    ):
        client = UnifiedClient(initial_provider="google")

        # UnifiedClient should simply hold the real client instance
        assert client.active_client == mock_gemini_instance
        mock_gemini_class.assert_called_once()


def test_session_provider_switching(mock_config):
    """Test that ChatSession can explicitly switch between different client instances."""
    # 1. Setup mocks for two different providers
    mock_openai_instance = MagicMock()
    mock_gemini_instance = MagicMock()

    mock_openai_instance.config_section = "openai"
    mock_gemini_instance.config_section = "google"

    # State to be synced
    mock_gemini_instance.conversation = [{"role": "user", "content": "hello"}]
    mock_gemini_instance.active_tools = ["tool1"]
    mock_gemini_instance.tools_enabled = True
    mock_gemini_instance.live_debug = False
    mock_gemini_instance.system_prompt_enabled = True

    # 2. Initialize session with Gemini
    with (
        patch("llm_cli.clients.session.LlmCliCompleter"),
        patch("llm_cli.clients.session.ReasoningSentinelManager"),
        patch("llm_cli.clients.session.SessionUI"),
    ):
        session = ChatSession(mock_gemini_instance)
        assert session.client == mock_gemini_instance

        # 3. Perform the switch to OpenAI
        session.switch_client(mock_openai_instance)

        # 4. Verify state was synced to the new client
        assert session.client == mock_openai_instance
        assert mock_openai_instance.conversation == mock_gemini_instance.conversation
        assert mock_openai_instance.active_tools == ["tool1"]
        assert mock_openai_instance._session == session


def test_handle_provider_command_integration(mock_config):
    """Test the /provider command triggers a switch in the session."""
    mock_current_client = MagicMock()
    mock_current_client.config_section = "google"
    mock_current_client.active_tools = []
    mock_current_client.live_debug = False

    mock_session = MagicMock()
    mock_current_client._session = mock_session

    mock_new_client_class = MagicMock()

    with (
        patch(
            "llm_cli.clients.registry.client_registry.get_config_section", return_value="openai"
        ),
        patch(
            "llm_cli.clients.registry.client_registry.get_client_class",
            return_value=mock_new_client_class,
        ),
        patch(
            "llm_cli.clients.config.config_manager.get_active_providers",
            return_value=["google", "openai"],
        ),
    ):
        ctx = CommandContext(
            client=mock_current_client, args="openai", pending_data=None, sources=None
        )

        # Execute the command
        handle_provider(ctx)

        # Verify a new client was created and switched via the session
        mock_new_client_class.assert_called_once()
        mock_session.switch_client.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
