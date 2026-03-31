from unittest.mock import patch

import pytest

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.modules.models import DataSource


class MockClient(BaseLlmClient):
    """Minimal concrete implementation of BaseLlmClient for testing."""

    def _send(self, _data: list[DataSource]):
        return (("test response", None), None)

    def utility_send(self, _system_prompt: str, _user_prompt: str, _json_mode: bool = False) -> str:
        return "test"


@pytest.fixture
def mock_config():
    """Mocks config_manager to return specific model configurations."""
    with patch("llm_cli.clients.base.config_manager") as mock:
        # Define some dummy model aliases for the 'test_provider'
        mock.get_model_aliases.return_value = {
            "default": "gpt-4",
            "image": "dall-e-3",
            "lite": "gpt-3.5-turbo",
        }

        # Define behavior for get_model_config
        def side_effect(section, alias):
            if alias == "image":
                return {"model": "dall-e-3", "tools": False}
            if alias == "lite":
                return {"model": "gpt-3.5-turbo", "tools": True}
            return {"model": "gpt-4"}  # tools is missing (defaults to True)

        mock.get_model_config.side_effect = side_effect
        yield mock


def test_model_switch_updates_tools_enabled(mock_config):
    spec = ProviderSpec(api_key_name="api_key", config_section="test_provider", pdf_as_base64=True)

    # 1. Initialize with default (tools should be True by default)
    client = MockClient(initial_model_alias="default", spec=spec)
    assert client.current_alias == "default"
    assert client.tools_enabled is True

    # 2. Switch to 'image' model which has tools = false
    client.set_model("image")
    assert client.current_alias == "image"
    assert client.tools_enabled is False

    # 3. Switch back to 'lite' model which has tools = true
    client.set_model("lite")
    assert client.current_alias == "lite"
    assert client.tools_enabled is True


def test_initial_model_with_tools_disabled(mock_config):
    spec = ProviderSpec(api_key_name="api_key", config_section="test_provider", pdf_as_base64=True)

    # Initialize directly with 'image' model
    client = MockClient(initial_model_alias="image", spec=spec)
    assert client.current_alias == "image"
    assert client.tools_enabled is False


def test_set_custom_model_enables_tools(mock_config):
    spec = ProviderSpec(api_key_name="api_key", config_section="test_provider", pdf_as_base64=True)
    client = MockClient(initial_model_alias="image", spec=spec)
    assert client.tools_enabled is False

    # Switching to a custom model should reset tools to True (default behavior)
    client.set_custom_model("some-random-model")
    assert client.current_alias == "custom"
    assert client.tools_enabled is True


def test_manual_override_persists_until_model_switch(mock_config):
    spec = ProviderSpec(api_key_name="api_key", config_section="test_provider", pdf_as_base64=True)
    client = MockClient(initial_model_alias="default", spec=spec)
    assert client.tools_enabled is True

    # Manually disable tools (simulating /tools off)
    client.tools_enabled = False
    assert client.tools_enabled is False

    # Switching to the SAME model should re-apply the config
    client.set_model("default")
    assert client.tools_enabled is True
