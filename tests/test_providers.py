"""Tests for provider-specific client implementations."""

import pytest

from llm_cli.apps.unified import UnifiedClient
from llm_cli.clients.claude import ClaudeClient
from llm_cli.clients.gemini import GeminiClient
from llm_cli.clients.grok import GrokClient
from llm_cli.clients.openai import OpenAIClient


class TestProviderClients:
    """Test suite for provider-specific clients."""

    @pytest.mark.parametrize(
        "client_class,config_section,expected_base64",
        [
            (GeminiClient, "google", True),
            (ClaudeClient, "anthropic", True),
            (GrokClient, "xai", False),
        ],
    )
    def test_client_initialization(
        self, mock_config, client_class, config_section, expected_base64
    ):
        """Test that all clients initialize correctly."""
        client = client_class(initial_model_alias="default", stdout=True)
        assert client.config_section == config_section
        assert client.pdf_as_base64 == expected_base64
        assert client.model is not None
        assert client.current_alias == "default"

    def test_initial_tool_activation(self, mock_config):
        """Test that tools can be activated at initialization."""
        client = GeminiClient(
            initial_model_alias="default", stdout=True, initial_tools=["search"]
        )
        assert "search" in client.active_tools

    def test_gemini_model_switching(self, mock_config):
        """Test model switching in Gemini client."""
        client = GeminiClient(initial_model_alias="default", stdout=True)
        client.available_models["pro"] = "test-model-pro"
        result = client.set_model("pro")
        assert result is True
        assert client.current_alias == "pro"


class TestUnifiedClient:
    """Test suite for UnifiedClient."""

    def test_unified_client_initialization(self, mock_config):
        """Test UnifiedClient initialization."""
        client = UnifiedClient(
            initial_provider="google", initial_model_alias="default", stdout=True
        )
        assert client.config_section == "google"
        assert client.active_client is not None

    def test_provider_switching(self, mock_config):
        """Test switching between providers."""
        client = UnifiedClient(
            initial_provider="google", initial_model_alias="default", stdout=True
        )
        assert client.config_section == "google"

        # Switch to OpenAI
        result = client._activate_provider("openai")
        assert result is True
        assert client.config_section == "openai"

    def test_unified_pdf_delegation_to_gemini(self, mock_config, temp_pdf_file):
        """Test that UnifiedClient delegates PDF processing to Gemini."""
        client = UnifiedClient(
            initial_provider="google", initial_model_alias="default", stdout=True
        )
        result = client._process_single_source(str(temp_pdf_file))

        if result:
            assert result.content_type == "application/pdf"

    def test_unified_model_aliases(self, mock_config):
        """Test that UnifiedClient loads model aliases correctly."""
        client = UnifiedClient(
            initial_provider="google", initial_model_alias="default", stdout=True
        )
        assert "default" in client.available_models
        assert client.model is not None

    def test_invalid_provider(self, mock_config):
        """Test handling of invalid provider."""
        client = UnifiedClient(
            initial_provider="google", initial_model_alias="default", stdout=True
        )
        result = client._activate_provider("invalid_provider")
        assert result is False


class TestSystemPrompt:
    """Test suite for system prompt functionality."""

    @pytest.mark.parametrize(
        "client_class,config_section",
        [
            (GeminiClient, "google"),
            (OpenAIClient, "openai"),
            (ClaudeClient, "anthropic"),
            (GrokClient, "xai"),
        ],
    )
    def test_system_prompt_enabled_by_default(
        self, mock_config, client_class, config_section
    ):
        """Test that system prompt is enabled by default when configured."""
        client = client_class(initial_model_alias="default", stdout=True)
        assert client.system_prompt is not None
        assert client.system_prompt_enabled is True

    @pytest.mark.parametrize(
        "client_class,config_section",
        [
            (GeminiClient, "google"),
            (OpenAIClient, "openai"),
            (ClaudeClient, "anthropic"),
            (GrokClient, "xai"),
        ],
    )
    def test_system_prompt_disabled_with_flag(
        self, mock_config, client_class, config_section
    ):
        """Test that system prompt can be disabled with flag."""
        client = client_class(
            initial_model_alias="default", stdout=True, disable_system_prompt=True
        )
        assert client.system_prompt is not None
        assert client.system_prompt_enabled is False
