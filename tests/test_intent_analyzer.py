from unittest.mock import patch

import pytest

from llm_cli.security.intent_analyzer import IntentAnalyzer


@pytest.fixture
def mock_client():
    # Patch where the class is defined, not where it is imported inside a function
    with patch("llm_cli.clients.openai.OpenAIClient") as MockClient:
        client_instance = MockClient.return_value
        # Mock _send to return ((text, thought), usage)
        client_instance._send.return_value = (
            ('{"verdict": "SAFE", "reason": "Looks good"}', ""),
            {},
        )
        yield client_instance


def test_intent_analyzer_init(mock_client):
    analyzer = IntentAnalyzer("openai", "gpt-4")
    assert analyzer.provider == "openai"
    assert analyzer.model == "gpt-4"
    assert analyzer.client is not None


def test_intent_analyzer_verify_safe(mock_client):
    analyzer = IntentAnalyzer("openai", "gpt-4")
    mock_client._send.return_value = (('{"verdict": "SAFE", "reason": "Safe"}', ""), {})

    is_safe, reason = analyzer.verify_action(
        "read file", "read_file", {"path": "test.txt"}
    )
    assert is_safe is True
    assert reason == "Safe"


def test_intent_analyzer_verify_suspicious(mock_client):
    analyzer = IntentAnalyzer("openai", "gpt-4")
    mock_client._send.return_value = (
        ('{"verdict": "SUSPICIOUS", "reason": "Mismatch"}', ""),
        {},
    )

    is_safe, reason = analyzer.verify_action(
        "read file", "execute_command", {"command": "rm -rf /"}
    )
    assert is_safe is False
    assert reason == "Mismatch"


def test_intent_analyzer_invalid_json(mock_client):
    analyzer = IntentAnalyzer("openai", "gpt-4")
    # Return raw text that contains SUSPICIOUS but invalid JSON
    mock_client._send.return_value = (
        ("Thinking... I think this is SUSPICIOUS because...", ""),
        {},
    )

    is_safe, reason = analyzer.verify_action("prompt", "tool", {})
    assert is_safe is False
    assert "SUSPICIOUS" in reason


def test_intent_analyzer_safe_text_fallback(mock_client):
    analyzer = IntentAnalyzer("openai", "gpt-4")
    # Return raw text that contains SAFE but invalid JSON
    mock_client._send.return_value = (("This action seems SAFE to me.", ""), {})

    is_safe, reason = analyzer.verify_action("prompt", "tool", {})
    assert is_safe is True
    assert "SAFE" in reason
