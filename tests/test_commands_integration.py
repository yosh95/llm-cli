from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.command_dispatcher import CommandContext
from llm_cli.clients.command_impl import (
    handle_clear,
    handle_debug,
    handle_model,
    handle_reload,
    handle_tools,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.available_models = {"gpt-4": "gpt-4-model", "gpt-3.5": "gpt-3.5-turbo"}
    client.current_alias = "gpt-4"
    client.model = "gpt-4-model"
    client.active_tools = []
    client.tools_enabled = True
    client.live_debug = False
    client.config_section = "openai"
    client._api_key_name = "api_key"
    return client


def test_handle_model_list(mock_client):
    ctx = CommandContext(client=mock_client, args="", pending_data=None, sources=None)
    with patch("llm_cli.clients.command_impl.console.print") as mock_print:
        assert handle_model(ctx) is True
        # Should print available models
        mock_print.assert_any_call("[bold]Available Models:[/bold]")


def test_handle_model_switch(mock_client):
    ctx = CommandContext(client=mock_client, args="gpt-3.5", pending_data=None, sources=None)
    mock_client.set_model.return_value = True
    mock_client.current_alias = "gpt-3.5"
    mock_client.model = "gpt-3.5-turbo"

    with patch("llm_cli.clients.command_impl.console.print"):
        assert handle_model(ctx) is True
        mock_client.set_model.assert_called_once_with("gpt-3.5")


def test_handle_tools_toggle(mock_client):
    ctx = CommandContext(client=mock_client, args="off", pending_data=None, sources=None)
    assert handle_tools(ctx) is True
    assert mock_client.tools_enabled is False

    ctx = CommandContext(client=mock_client, args="on", pending_data=None, sources=None)
    assert handle_tools(ctx) is True
    assert mock_client.tools_enabled is True


def test_handle_debug_toggle(mock_client):
    mock_client.live_debug = False
    ctx = CommandContext(client=mock_client, args="", pending_data=None, sources=None)
    assert handle_debug(ctx) is True
    assert mock_client.live_debug is True

    assert handle_debug(ctx) is True
    assert mock_client.live_debug is False


def test_handle_clear(mock_client):
    ctx = CommandContext(client=mock_client, args="", pending_data=None, sources=None)
    assert handle_clear(ctx) is True
    mock_client.clear_history.assert_called_once()


def test_handle_reload(mock_client, mock_config):
    ctx = CommandContext(client=mock_client, args="", pending_data=None, sources=None)

    with (
        patch("llm_cli.clients.config.config_manager.load_config"),
        patch("llm_cli.clients.config.config_manager.get", return_value="new_key"),
        patch("llm_cli.security.policy.policy_engine.reinitialize"),
        patch("llm_cli.clients.command_impl.console.print"),
    ):
        assert handle_reload(ctx) is True
        assert mock_client.api_key == "new_key"
        mock_client.refresh_config.assert_called_once()
        mock_client._refresh_system_prompt.assert_called_once()
