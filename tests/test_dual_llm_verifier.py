from unittest.mock import MagicMock, patch

import pytest
import requests

from llm_cli.security.dual_llm_verifier import verify_tool_call


@pytest.fixture
def mock_client_class():
    with patch("llm_cli.clients.registry.client_registry.get_client_class") as mock_get:
        mock_client = MagicMock()
        mock_client.return_value.api_key = "test_api_key"
        mock_client.return_value.model = "test-model"
        mock_client.return_value.config_section = "google"
        mock_get.return_value = mock_client
        yield mock_client


def test_verify_tool_call_safe(mock_client_class):
    """Test Dual LLM verifier when it returns a safe response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"safe": true, "reason": "Action is consistent with intent."}'
                        }
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        is_safe, reason = verify_tool_call(
            "List files", "list_files", {"directory": "."}
        )

        assert is_safe is True
        assert "consistent" in reason


def test_verify_tool_call_unsafe(mock_client_class):
    """Test Dual LLM verifier when it returns an unsafe response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"safe": false, "reason": "Attempting to delete system files."}'
                        }
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        is_safe, reason = verify_tool_call(
            "Read notes",
            "execute_python",
            {"code": "import os; os.remove('/etc/passwd')"},
        )

        assert is_safe is False
        assert "delete system files" in reason


def test_verify_tool_call_openai_format(mock_client_class):
    """Test Dual LLM verifier with OpenAI response format."""
    mock_client_class.return_value.config_section = "openai"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"safe": true, "reason": "OpenAI says it is safe."}'
                }
            }
        ]
    }

    with (
        patch("llm_cli.clients.config.config_manager.get", return_value="openai"),
        patch("requests.post", return_value=mock_response),
    ):
        is_safe, reason = verify_tool_call("Hello", "test_tool", {})

        assert is_safe is True
        assert "OpenAI" in reason


def test_verify_tool_call_api_error(mock_client_class):
    """Test Dual LLM verifier when API call fails (should fail-safe to True)."""
    with patch(
        "requests.post", side_effect=requests.exceptions.RequestException("Timeout")
    ):
        is_safe, reason = verify_tool_call("Hello", "test_tool", {})

        # Fail-safe logic: return True but with error reason
        assert is_safe is True
        assert "Verification process failed" in reason


def test_verify_tool_call_malformed_json(mock_client_class):
    """Test Dual LLM verifier when LLM returns non-JSON text."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "This is not JSON"}}]
    }

    with (
        patch("llm_cli.clients.config.config_manager.get", return_value="openai"),
        patch("requests.post", return_value=mock_response),
    ):
        is_safe, reason = verify_tool_call("Hello", "test_tool", {})

        # Fail-safe: if json.loads fails, it should catch the exception and return True
        assert is_safe is True
        assert "Verification process failed" in reason
