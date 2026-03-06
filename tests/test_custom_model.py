import pytest

from llm_cli.apps.unified import UnifiedClient
from llm_cli.clients.base import BaseLlmClient


class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        self.available_models = {"default": "default-model"}

    def _send(self, _data):
        return "response", {}


def test_base_client_custom_model():
    client = MockClient(
        initial_model_alias="default",
        api_key_name="test_key",
        config_section="test",
        pdf_as_base64=False,
        stdout=False,
    )

    # Verify initial state
    assert client.model == "default-model"

    # Test setting a known model
    client.set_model("default")
    assert client.model == "default-model"

    # Test setting a custom model directly
    client.set_custom_model("custom-gpt-4")
    assert client.model == "custom-gpt-4"
    assert client.current_alias == "custom"

    # Verify _handle_command behavior via mock if needed,
    # but unit testing the method logic is sufficient here.
    # Simulating the command handling logic manually:
    success = client.set_model("non-existent")
    assert not success
    client.set_custom_model("non-existent")
    assert client.model == "non-existent"


def test_unified_client_custom_model():
    # Setup UnifiedClient with a mock provider
    with pytest.MonkeyPatch.context() as m:
        from llm_cli.clients.registry import client_registry

        m.setattr(
            "llm_cli.apps.unified.get_setting",
            lambda key, _section: (
                "provider" if key == "unified_default_provider" else "key"
            ),
        )

        # Mock the registry methods to use our MockClient
        m.setattr(client_registry, "get_client_class", lambda _alias: MockClient)
        m.setattr(client_registry, "get_config_section", lambda _alias: "mock_section")

        client = UnifiedClient(
            initial_provider="mock",
            initial_model_alias="default",
            api_key_name="test_key",
            config_section="test",
            pdf_as_base64=False,
            stdout=False,
        )

        # Verify initial state
        assert client.model == "default-model"
        assert client.active_client.model == "default-model"

        # Test custom model setting
        client.set_custom_model("unified-custom-model")

        # Verify it propagated to the active client
        assert client.model == "unified-custom-model"
        assert client.active_client.model == "unified-custom-model"
        assert client.current_alias == "custom"
        assert client.active_client.current_alias == "custom"
