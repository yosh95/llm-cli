from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.claude import ClaudeClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def mock_config():
    with (
        patch(
            "llm_cli.clients.config.config_manager.get_model_aliases",
            return_value={"default": "claude-3-opus-20240229"},
        ),
        patch("llm_cli.clients.config.config_manager.get") as mock_get_setting,
    ):

        def get_setting_side_effect(section, key=None):
            if key == "api_key":
                return "test-key"
            if key == "system_prompt":
                return ""
            return None

        mock_get_setting.side_effect = get_setting_side_effect
        yield mock_get_setting


@pytest.fixture
def client(mock_config):
    c = ClaudeClient(stdout=False)
    # Disable system prompt so message-building tests are not affected by the
    # auto-injected "Current date: ..." prefix from ProviderConfigManager.
    c.system_prompt_enabled = False
    return c


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_initialization(client):
    """Client initialises with correct model, key, and pdf_as_base64 flag."""
    assert client.model == "claude-3-opus-20240229"
    assert client.api_key == "test-key"
    assert client.pdf_as_base64 is True


# ---------------------------------------------------------------------------
# _build_claude_messages – plain text / image / PDF
# (logic lives in ClaudeMessagesMixin)
# ---------------------------------------------------------------------------


def test_build_messages_simple_text(client):
    """Single text DataSource becomes a user message with a text content block."""
    data = [DataSource(content="Hello", content_type="text/plain")]
    messages = client._build_claude_messages(data)

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["type"] == "text"
    assert messages[0]["content"][0]["text"] == "Hello"


def test_build_messages_with_history(client):
    """Conversation history is serialised before the new user turn."""
    client.conversation.append(Message(role=Role.USER, parts=[ContentPart(text="Hi")]))
    client.conversation.append(
        Message(role=Role.MODEL, parts=[ContentPart(text="Hello there")])
    )

    data = [DataSource(content="How are you?", content_type="text/plain")]
    messages = client._build_claude_messages(data)

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == "Hi"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["text"] == "Hello there"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["text"] == "How are you?"


def test_build_messages_with_image(client):
    """Image DataSource becomes a Claude ``image`` content block."""
    data = [DataSource(content="base64data", content_type="image/png")]
    messages = client._build_claude_messages(data)

    assert len(messages) == 1
    content = messages[0]["content"][0]
    assert content["type"] == "image"
    assert content["source"]["type"] == "base64"
    assert content["source"]["media_type"] == "image/png"
    assert content["source"]["data"] == "base64data"


def test_build_messages_with_pdf(client):
    """PDF DataSource becomes a Claude ``document`` content block with base64 source."""
    data = [DataSource(content="pdf_base64", content_type="application/pdf")]
    messages = client._build_claude_messages(data)

    assert len(messages) == 1
    content = messages[0]["content"][0]
    assert content["type"] == "document"
    assert content["source"]["type"] == "base64"
    assert content["source"]["media_type"] == "application/pdf"
    assert content["source"]["data"] == "pdf_base64"


def test_build_messages_pdf_in_history(client):
    """PDF stored in conversation history is re-serialised as a document block."""
    client.conversation.append(
        Message(
            role=Role.USER,
            parts=[
                ContentPart(text="Here is a document"),
                ContentPart(
                    inline_data={
                        "mimeType": "application/pdf",
                        "data": "historypdfdata",
                        "filename": "history.pdf",
                    }
                ),
            ],
        )
    )
    client.conversation.append(
        Message(role=Role.MODEL, parts=[ContentPart(text="Got the PDF")])
    )

    data = [DataSource(content="What does it say?", content_type="text/plain")]
    messages = client._build_claude_messages(data)

    # History user message must contain the document block
    user_hist = messages[0]
    assert user_hist["role"] == "user"
    doc_parts = [p for p in user_hist["content"] if p.get("type") == "document"]
    assert len(doc_parts) == 1
    assert doc_parts[0]["source"]["type"] == "base64"
    assert doc_parts[0]["source"]["data"] == "historypdfdata"


# ---------------------------------------------------------------------------
# _build_claude_messages – tool round-trip
# ---------------------------------------------------------------------------


def test_build_messages_with_tool_results(client):
    """Tool call → tool result history round-trip serialises correctly."""
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
    messages = client._build_claude_messages(data)

    # 1. Assistant message with tool_use block
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"][0]["type"] == "tool_use"
    assert messages[0]["content"][0]["id"] == "call_1"

    # 2. User message with tool_result block
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "tool_result"
    assert messages[1]["content"][0]["tool_use_id"] == "call_1"
    assert messages[1]["content"][0]["content"] == "Success"

    # 3. New user message
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["text"] == "Next"


# ---------------------------------------------------------------------------
# _send – text / thinking / tool_use responses
# ---------------------------------------------------------------------------


def test_send_success_text_only(client):
    """Successful plain-text response is parsed and returned correctly."""
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

        args, kwargs = mock_post.call_args
        assert args[0] == client.API_URL
        assert kwargs["json_data"]["messages"][0]["content"][0]["text"] == "Hello"


def test_send_with_thinking(client):
    """Extended-thinking blocks are captured in the ``thought`` return value."""
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

        last_msg = client.conversation[-1]
        assert last_msg.role == Role.MODEL
        assert last_msg.parts[0].thought == "Let me think..."
        assert last_msg.parts[0].thought_signature == "sig123"
        assert last_msg.parts[1].text == "Here is the answer."


def test_send_with_tool_use(client):
    """tool_use response blocks are stored as function_call ContentParts."""
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


# ---------------------------------------------------------------------------
# _send – system prompt
# ---------------------------------------------------------------------------


def test_system_prompt_inclusion(client):
    """System prompt is passed as a top-level ``system`` field, not a message."""
    client.system_prompt = "You are a helpful assistant."
    client.system_prompt_enabled = True
    data = [DataSource(content="Hi", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": [], "usage": {}}

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        client._send(data)

        args, kwargs = mock_post.call_args
        system_payload = kwargs["json_data"]["system"]
        assert len(system_payload) == 1
        assert system_payload[0]["text"] == "You are a helpful assistant."
        assert system_payload[0]["cache_control"] == {"type": "ephemeral"}

        # System prompt must NOT appear inside the messages list
        for msg in kwargs["json_data"]["messages"]:
            assert msg["role"] != "system"


def test_no_system_prompt_when_disabled(client):
    """No ``system`` key is added when system_prompt_enabled is False."""
    client.system_prompt = "You are a helpful assistant."
    client.system_prompt_enabled = False
    data = [DataSource(content="Hi", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": [], "usage": {}}

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        client._send(data)

        _, kwargs = mock_post.call_args
        assert "system" not in kwargs["json_data"]


# ---------------------------------------------------------------------------
# _send – error handling
# ---------------------------------------------------------------------------


def test_api_error_handling(client):
    """Network / API errors return (None, None), None without raising."""
    data = [DataSource(content="Hi", content_type="text/plain")]

    with patch.object(client, "_post", side_effect=Exception("Network error")):
        (text, thought), usage = client._send(data)

        assert text is None
        assert thought is None
        assert usage is None
