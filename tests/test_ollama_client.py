from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.ollama import OllamaClient
from llm_cli.modules.models import DataSource


@pytest.fixture
def ollama_client():
    def mock_get(section, key, default=None):
        if section == "ollama" and key == "api_url":
            return "http://localhost:11434/v1/chat/completions"
        if section == "general" and key == "request_timeout":
            return "30"
        return default

    with patch("llm_cli.clients.config.config_manager.get", side_effect=mock_get):
        with patch(
            "llm_cli.clients.config.config_manager.get_model_aliases",
            return_value={"default": "llama3.2"},
        ):
            client = OllamaClient(initial_model_alias="default")
            return client


def test_initialization(ollama_client):
    assert ollama_client.api_url == "http://localhost:11434/v1/chat/completions"
    assert ollama_client.model == "llama3.2"


@patch("llm_cli.clients.base.BaseLlmClient._post")
def test_send_success(mock_post, ollama_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {"message": {"role": "assistant", "content": "Hello from Ollama!"}}
        ],
        "usage": {"total_tokens": 10},
    }
    mock_post.return_value = mock_response

    data = [DataSource(content_type="text/plain", content="Hi")]
    (content, thought), usage = ollama_client._send(data)

    assert content == "Hello from Ollama!"
    assert thought == ""
    assert usage["total_tokens"] == 10
    mock_post.assert_called_once()


@patch("llm_cli.clients.base.BaseLlmClient._post")
def test_send_with_reasoning(mock_post, ollama_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Final answer",
                    "reasoning_content": "Internal thought",
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    data = [DataSource(content_type="text/plain", content="Hi")]
    (content, thought), _ = ollama_client._send(data)

    assert content == "Final answer"
    assert thought == "Internal thought"


@patch("llm_cli.clients.base.BaseLlmClient._post")
def test_send_error(mock_post, ollama_client):
    mock_post.side_effect = Exception("API Error")

    data = [DataSource(content_type="text/plain", content="Hi")]
    (content, thought), usage = ollama_client._send(data)

    assert content is None
    assert thought is None
    assert usage is None


def test_build_messages_simple(ollama_client):
    ollama_client.system_prompt = "You are a helpful assistant"
    ollama_client.system_prompt_enabled = True

    data = [DataSource(content_type="text/plain", content="Hello")]
    messages = ollama_client._build_messages(data)

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "You are a helpful assistant"}
    assert messages[1] == {
        "role": "user",
        "content": [{"type": "text", "text": "Hello"}],
    }
