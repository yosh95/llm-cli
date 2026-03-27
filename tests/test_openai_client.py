from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.openai import DEFAULT_API_URL, OpenAIClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def mock_config():
    with (
        patch(
            "llm_cli.clients.config.config_manager.get_model_aliases",
            return_value={"default": "gpt-4-turbo"},
        ),
        patch("llm_cli.clients.config.config_manager.get") as mock_get,
    ):

        def get_side_effect(section, key=None):
            if key == "api_key":
                return "sk-test"
            if key == "api_url":
                return None  # Use default URL
            if key == "system_prompt":
                return ""
            return None

        mock_get.side_effect = get_side_effect
        yield mock_get


@pytest.fixture
def client(mock_config):
    c = OpenAIClient(stdout=False)
    # Disable system prompt so message-building tests are not affected by the
    # auto-injected "Current date: ..." prefix from ProviderConfigManager.
    c.system_prompt_enabled = False
    return c


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_initialization(client):
    """Client initializes with correct model, key, and default URL."""
    assert client.model == "gpt-4-turbo"
    assert client.api_key == "sk-test"
    assert client.api_url == DEFAULT_API_URL
    assert client.pdf_as_base64 is True


def test_initialization_custom_url():
    """Client picks up a custom api_url from config."""
    with (
        patch(
            "llm_cli.clients.config.config_manager.get_model_aliases",
            return_value={"default": "gpt-4-turbo"},
        ),
        patch("llm_cli.clients.config.config_manager.get") as mock_get,
    ):

        def get_side_effect(section, key=None):
            if key == "api_url":
                return "https://custom.proxy/v1/chat/completions"
            if key == "api_key":
                return "sk-test"
            return None

        mock_get.side_effect = get_side_effect
        c = OpenAIClient(stdout=False)
        assert c.api_url == "https://custom.proxy/v1/chat/completions"


# ---------------------------------------------------------------------------
# _build_openai_compatible_messages – plain text / image / PDF
# ---------------------------------------------------------------------------


def test_build_messages_single_text(client):
    """Single text DataSource becomes a user message with string content."""
    data = [DataSource(content="Hello world", content_type="text/plain")]
    msgs = client._build_openai_compatible_messages(data)

    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    # Mixin wraps single items in a list; content is a list with one text part
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Hello world"


def test_build_messages_image(client):
    """Image DataSource becomes an image_url content part."""
    data = [DataSource(content="base64img", content_type="image/jpeg")]
    msgs = client._build_openai_compatible_messages(data)

    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/jpeg;base64,base64img"


def test_build_messages_pdf(client):
    """PDF DataSource is embedded as a file part when pdf_as_base64 is True."""
    data = [
        DataSource(
            content="pdfdata",
            content_type="application/pdf",
            metadata={"filename": "doc.pdf"},
        )
    ]
    msgs = client._build_openai_compatible_messages(data)

    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert isinstance(content, list)
    # OpenAI Chat Completions API requires the "file" content part format
    assert content[0]["type"] == "file"
    file_obj = content[0]["file"]
    assert file_obj["filename"] == "doc.pdf"
    assert file_obj["file_data"] == "data:application/pdf;base64,pdfdata"


def test_build_messages_pdf_in_history(client):
    """PDF in conversation history (inline_data) is embedded as a file part."""
    client.conversation = [
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
        ),
        Message(role=Role.MODEL, parts=[ContentPart(text="Got the PDF")]),
    ]
    data = [DataSource(content="What does it say?", content_type="text/plain")]
    msgs = client._build_openai_compatible_messages(data)

    # History user message should contain the file part
    user_hist = msgs[0]
    assert user_hist["role"] == "user"
    content = user_hist["content"]
    file_parts = [p for p in content if p.get("type") == "file"]
    assert len(file_parts) == 1
    file_obj = file_parts[0]["file"]
    assert file_obj["filename"] == "history.pdf"
    assert file_obj["file_data"] == "data:application/pdf;base64,historypdfdata"


def test_build_messages_mixed_text_and_image(client):
    """Text + image in same turn produces a multi-part user message."""
    data = [
        DataSource(content="Look at this", content_type="text/plain"),
        DataSource(content="imgdata", content_type="image/png"),
    ]
    msgs = client._build_openai_compatible_messages(data)

    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "Look at this"}
    assert content[1]["type"] == "image_url"


# ---------------------------------------------------------------------------
# _build_openai_compatible_messages – conversation history
# ---------------------------------------------------------------------------


def test_build_messages_with_history(client):
    """History is serialised before the new user turn."""
    client.conversation = [
        Message(role=Role.USER, parts=[ContentPart(text="First question")]),
        Message(role=Role.MODEL, parts=[ContentPart(text="First answer")]),
    ]
    data = [DataSource(content="Second question", content_type="text/plain")]
    msgs = client._build_openai_compatible_messages(data)

    # system prompt is empty in fixture, so no system message
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"][0]["text"] == "First answer"
    assert msgs[2]["role"] == "user"


def test_build_messages_tool_round_trip(client):
    """Tool call → tool result history is serialised correctly."""
    tool_call = {"id": "call_1", "name": "calc", "args": {"expr": "2+2"}}
    tool_resp = {"id": "call_1", "name": "calc", "response": {"result": "4"}}

    client.conversation = [
        Message(role=Role.USER, parts=[ContentPart(text="What's 2+2?")]),
        Message(role=Role.MODEL, parts=[ContentPart(function_call=tool_call)]),
        Message(role=Role.TOOL, parts=[ContentPart(function_response=tool_resp)]),
    ]
    data = [DataSource(content="Thanks", content_type="text/plain")]
    msgs = client._build_openai_compatible_messages(data)

    # user | assistant (with tool_calls) | tool | user
    assert msgs[0]["role"] == "user"

    assistant_msg = msgs[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["id"] == "call_1"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"

    tool_msg = msgs[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "4"

    assert msgs[3]["role"] == "user"


# ---------------------------------------------------------------------------
# _send – text response
# ---------------------------------------------------------------------------


def _make_chat_response(content: str, tool_calls=None, usage=None):
    """Build a minimal Chat Completions API response dict."""
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_send_text_response(client):
    """_send parses a plain text Chat Completions response correctly."""
    data = [DataSource(content="Hi", content_type="text/plain")]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_chat_response("Hello there!")

    with patch.object(client, "_post", return_value=mock_resp):
        (text, thought), usage = client._send(data)

    assert text == "Hello there!"
    assert thought == ""
    assert usage["total_tokens"] == 15


def test_send_updates_conversation_history(client):
    """After _send the MODEL reply is appended to conversation."""
    data = [DataSource(content="Ping", content_type="text/plain")]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_chat_response("Pong")

    with patch.object(client, "_post", return_value=mock_resp):
        client._send(data)

    last = client.conversation[-1]
    assert last.role == Role.MODEL
    assert last.parts[0].text == "Pong"


def test_send_includes_system_prompt(client):
    """When system_prompt is set it is prepended to history."""
    client.system_prompt = "You are helpful."
    client.system_prompt_enabled = True
    data = [DataSource(content="Hello", content_type="text/plain")]
    mock_resp = MagicMock()
    # Handle both potential response formats
    mock_resp.json.return_value = _make_chat_response("Hi!")

    with patch.object(client, "_post", return_value=mock_resp) as mock_post:
        client._send(data)

    payload = mock_post.call_args[1]["json_data"]
    if "input" in payload:
        # Responses API format
        assert payload["input"][0]["role"] == "system"
        content = payload["input"][0]["content"]
        assert any(
            p.get("text") == "You are helpful." for p in content if p.get("type") == "input_text"
        )
    else:
        # Standard Chat Completions format
        assert payload["messages"][0] == {
            "role": "system",
            "content": "You are helpful.",
        }


def test_send_no_system_prompt_when_disabled(client):
    """When system_prompt_enabled is False no system message is injected."""
    client.system_prompt = "You are helpful."
    client.system_prompt_enabled = False
    data = [DataSource(content="Hello", content_type="text/plain")]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_chat_response("Hi!")

    with patch.object(client, "_post", return_value=mock_resp) as mock_post:
        client._send(data)

    payload = mock_post.call_args[1]["json_data"]
    messages = payload.get("input", payload.get("messages", []))
    assert all(m.get("role") != "system" for m in messages)


# ---------------------------------------------------------------------------
# _send – tool calls
# ---------------------------------------------------------------------------


def test_send_parses_tool_call(client):
    """_send stores a function_call ContentPart when the model requests a tool."""
    data = [DataSource(content="Do it", content_type="text/plain")]
    tc = [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "my_tool", "arguments": '{"arg": "val"}'},
        }
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_chat_response("", tool_calls=tc)

    with patch.object(client, "_post", return_value=mock_resp):
        client._send(data)

    last = client.conversation[-1]
    assert last.role == Role.MODEL
    fc = last.parts[0].function_call
    assert fc["id"] == "call_abc"
    assert fc["name"] == "my_tool"
    assert fc["args"] == {"arg": "val"}


def test_send_with_tools_payload(client):
    """When tools are enabled the payload contains the tools array."""
    client.tools_enabled = True
    client.active_tools = ["test_tool"]
    data = [DataSource(content="Use the tool", content_type="text/plain")]

    mock_tool_spec = [
        {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {"type": "object"},
            },
        }
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_chat_response("Tool used")

    with (
        patch(
            "llm_cli.clients.openai.registry.get_openai_spec",
            return_value=mock_tool_spec,
        ),
        patch.object(client, "_post", return_value=mock_resp) as mock_post,
    ):
        client._send(data)

    payload = mock_post.call_args[1]["json_data"]
    assert "tools" in payload
    if "messages" in payload:
        assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "test_tool"


# ---------------------------------------------------------------------------
# _send – error handling
# ---------------------------------------------------------------------------


def test_send_api_error(client):
    """Network/API errors return (None, None), None without raising."""
    data = [DataSource(content="Hello", content_type="text/plain")]

    with (
        patch.object(client, "_post", side_effect=Exception("API Error")),
        patch.object(client, "_report_error") as mock_report,
    ):
        (text, thought), usage = client._send(data)

    assert text is None
    assert thought is None
    assert usage is None
    mock_report.assert_called_once()


# ---------------------------------------------------------------------------
# Image generation routing
# ---------------------------------------------------------------------------


def test_image_model_detection(client):
    """_is_image_model returns True for dall-e and image model names."""
    client.model = "dall-e-3"
    assert client._is_image_model() is True

    client.model = "gpt-image-1"
    assert client._is_image_model() is True

    client.model = "gpt-4o"
    assert client._is_image_model() is False


def test_image_generation_routing(client):
    """_send delegates to _send_image_generation for image models."""
    client.model = "dall-e-3"

    with patch.object(
        client, "_send_image_generation", return_value=(("ok", ""), None)
    ) as mock_img:
        client._send([])
        mock_img.assert_called_once()


def test_send_image_generation_success(client):
    """Image generation returns a display message and updates history."""
    client.model = "dall-e-3"
    data = [DataSource(content="A cat", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"b64_json": "fake_b64", "revised_prompt": "A cute cat"}]
    }

    with (
        patch.object(client, "_post", return_value=mock_response),
        patch.object(
            client,
            "_save_inline_media_and_get_log_entry",
            return_value=("Image saved", "path/to/img"),
        ),
    ):
        (text, thought), usage = client._send(data)

    assert "Image saved" in text
    assert "Revised Prompt" in text
    assert "A cute cat" in text
    assert thought == ""
    assert usage is None


def test_send_image_generation_url_response(client):
    """Image generation also works when the API returns a URL instead of b64."""
    client.model = "dall-e-3"
    data = [DataSource(content="A cat", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"url": "http://example.com/img.png"}]}

    with (
        patch.object(client, "_post", return_value=mock_response),
        patch(
            "llm_cli.modules.media_utils.fetch_url_content",
            return_value=(b"img_data", "image/png"),
        ),
        patch.object(
            client,
            "_save_inline_media_and_get_log_entry",
            return_value=("Image saved", "path"),
        ),
    ):
        (text, _), _ = client._send(data)

    assert "Image saved" in text


def test_send_image_generation_no_data(client):
    """Image generation with empty data item returns failure message."""
    client.model = "dall-e-3"
    data = [DataSource(content="A cat", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{}]}

    with patch.object(client, "_post", return_value=mock_response):
        (text, _), _ = client._send(data)

    assert "Failed to retrieve image data" in text
