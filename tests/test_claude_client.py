from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.claude import ClaudeClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def mock_config():
    with (
        patch(
            "llm_cli.clients.config.get_model_aliases",
            return_value={"default": "claude-3-opus-20240229"},
        ),
        patch("llm_cli.clients.base.get_setting") as mock_get_setting,
    ):

        def get_setting_side_effect(key, section=None):
            if key == "api_key":
                return "test-key"
            if key == "system_prompt":
                return ""
            return None

        mock_get_setting.side_effect = get_setting_side_effect
        yield mock_get_setting


@pytest.fixture
def client(mock_config):
    return ClaudeClient(stdout=False)


def test_initialization(client):
    """Test that the client initializes correctly with default values."""
    assert client.model == "claude-3-opus-20240229"
    assert client.api_key == "test-key"
    assert client.pdf_as_base64 is True


def test_build_messages_simple_text(client):
    """Test converting simple text data to Claude message format."""
    data = [DataSource(content="Hello", content_type="text/plain")]
    messages = client._build_messages(data)

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["type"] == "text"
    assert messages[0]["content"][0]["text"] == "Hello"


def test_build_messages_with_history(client):
    """Test building messages with conversation history."""
    # Add history
    client.conversation.append(Message(role=Role.USER, parts=[ContentPart(text="Hi")]))
    client.conversation.append(
        Message(role=Role.MODEL, parts=[ContentPart(text="Hello there")])
    )

    data = [DataSource(content="How are you?", content_type="text/plain")]
    messages = client._build_messages(data)

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == "Hi"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["text"] == "Hello there"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["text"] == "How are you?"


def test_build_messages_with_image(client):
    """Test building messages with base64 image data."""
    data = [DataSource(content="base64data", content_type="image/png")]
    messages = client._build_messages(data)

    assert len(messages) == 1
    content = messages[0]["content"][0]
    assert content["type"] == "image"
    assert content["source"]["type"] == "base64"
    assert content["source"]["media_type"] == "image/png"
    assert content["source"]["data"] == "base64data"


def test_build_messages_with_pdf(client):
    """Test building messages with base64 PDF data."""
    data = [DataSource(content="pdf_base64", content_type="application/pdf")]
    messages = client._build_messages(data)

    assert len(messages) == 1
    content = messages[0]["content"][0]
    assert content["type"] == "document"
    assert content["source"]["type"] == "base64"
    assert content["source"]["media_type"] == "application/pdf"
    assert content["source"]["data"] == "pdf_base64"


def test_send_success_text_only(client):
    """Test successful text response from Claude API."""
    data = [DataSource(content="Hello", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "Hello! How can I help?"}],
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        (text, thought), usage = client._send(data)

        assert text == "Hello! How can I help?"
        assert thought == ""
        assert usage["input_tokens"] == 10

        # Verify call arguments
        args, kwargs = mock_post.call_args
        assert args[0] == client.API_URL
        assert kwargs["json_data"]["messages"][0]["content"][0]["text"] == "Hello"


def test_send_with_thinking(client):
    """Test response containing thinking blocks."""
    data = [DataSource(content="Solve this", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [
            {"type": "thinking", "thinking": "Let me think...", "signature": "sig123"},
            {"type": "text", "text": "Here is the answer."},
        ],
        "usage": {},
    }

    with patch.object(client, "_post", return_value=mock_response):
        (text, thought), _ = client._send(data)

        assert text == "Here is the answer."
        assert thought == "Let me think..."

        # Verify history was updated with thought
        last_msg = client.conversation[-1]
        assert last_msg.role == Role.MODEL
        assert last_msg.parts[0].thought == "Let me think..."
        assert last_msg.parts[0].thought_signature == "sig123"
        assert last_msg.parts[1].text == "Here is the answer."


def test_send_with_tool_use(client):
    """Test response containing tool use requests."""
    data = [DataSource(content="Check weather", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [
            {
                "type": "tool_use",
                "id": "tool_123",
                "name": "get_weather",
                "input": {"city": "Tokyo"},
            }
        ],
        "usage": {},
    }

    with patch.object(client, "_post", return_value=mock_response):
        client._send(data)

        last_msg = client.conversation[-1]
        assert last_msg.role == Role.MODEL
        assert last_msg.parts[0].function_call["id"] == "tool_123"
        assert last_msg.parts[0].function_call["name"] == "get_weather"
        assert last_msg.parts[0].function_call["args"] == {"city": "Tokyo"}


def test_build_messages_with_tool_results(client):
    """Test building messages that include tool results."""
    # 1. Model requests tool
    client.conversation.append(
        Message(
            role=Role.MODEL,
            parts=[
                ContentPart(
                    function_call={"id": "call_1", "name": "test_tool", "args": {}}
                )
            ],
        )
    )

    # 2. Tool responds (User role in generic model, but separate blocks in Claude)
    client.conversation.append(
        Message(
            role=Role.TOOL,
            parts=[
                ContentPart(
                    function_response={
                        "id": "call_1",
                        "name": "test_tool",
                        "response": {"result": "Success"},
                    }
                )
            ],
        )
    )

    data = [DataSource(content="Next", content_type="text/plain")]
    messages = client._build_messages(data)

    # Verify structure:
    # 1. Assistant message with tool_use
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"][0]["type"] == "tool_use"
    assert messages[0]["content"][0]["id"] == "call_1"

    # 2. User message with tool_result
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "tool_result"
    assert messages[1]["content"][0]["tool_use_id"] == "call_1"
    assert messages[1]["content"][0]["content"] == "Success"

    # 3. New user message
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["text"] == "Next"


def test_api_error_handling(client):
    """Test graceful handling of API errors."""
    data = [DataSource(content="Hi", content_type="text/plain")]

    with patch.object(client, "_post", side_effect=Exception("Network error")):
        (text, thought), usage = client._send(data)

        assert text is None
        assert thought is None
        assert usage is None


def test_system_prompt_inclusion(client):
    """Test that system prompt is included in payload."""
    client.system_prompt = "You are a helpful assistant."
    data = [DataSource(content="Hi", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": [], "usage": {}}

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        client._send(data)

        args, kwargs = mock_post.call_args
        system_payload = kwargs["json_data"]["system"]
        assert len(system_payload) == 1
        assert system_payload[0]["text"] == "You are a helpful assistant."
        assert "cache_control" not in system_payload[0]
