from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.openai import OpenAIClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def mock_config():
    with (
        patch(
            "llm_cli.clients.config.get_model_aliases",
            return_value={"default": "gpt-4-turbo"},
        ),
        patch("llm_cli.clients.base.get_setting") as mock_get_setting,
        patch("llm_cli.clients.openai.get_setting") as mock_openai_get_setting,
    ):

        def get_setting_side_effect(key, section=None):
            if key == "api_key":
                return "sk-test"
            if key == "api_url":
                return "https://custom.api/v1"
            if key == "system_prompt":
                return ""
            return None

        # We need to mock it in both places because OpenAIClient calls get_setting directly
        # for api_url in its __init__, and BaseLlmClient calls it for api_key.
        mock_get_setting.side_effect = get_setting_side_effect
        mock_openai_get_setting.side_effect = get_setting_side_effect

        yield mock_get_setting


@pytest.fixture
def client(mock_config):
    return OpenAIClient(stdout=False)


def test_initialization(client):
    """Test OpenAI client initialization."""
    assert client.model == "gpt-4-turbo"
    assert client.api_key == "sk-test"
    # Should use custom URL if provided in config
    assert client.api_url == "https://custom.api/v1"


def test_build_input_items_text(client):
    """Test building input items for Responses API."""
    data = [DataSource(content="Hello world", content_type="text/plain")]
    items = client._build_input_items(data)

    assert len(items) == 1
    assert items[0]["type"] == "message"
    assert items[0]["role"] == "user"
    assert items[0]["content"][0]["type"] == "input_text"
    assert items[0]["content"][0]["text"] == "Hello world"


def test_build_input_items_image(client):
    """Test building input items with base64 image."""
    data = [DataSource(content="base64img", content_type="image/jpeg")]
    items = client._build_input_items(data)

    assert len(items) == 1
    assert items[0]["content"][0]["type"] == "input_image"
    assert items[0]["content"][0]["image_url"] == "data:image/jpeg;base64,base64img"


def test_responses_api_parsing_text(client):
    """Test parsing text response from Responses API."""
    data = [DataSource(content="Hi", content_type="text/plain")]

    mock_resp_json = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello there!"}],
            }
        ],
        "usage": {"total_tokens": 50},
    }

    mock_response = MagicMock()
    mock_response.json.return_value = mock_resp_json

    with patch.object(client, "_post", return_value=mock_response):
        (text, thought), usage = client._send(data)

        assert text == "Hello there!"
        assert thought == ""
        assert usage["total_tokens"] == 50


def test_responses_api_parsing_reasoning(client):
    """Test parsing reasoning summary from Responses API."""
    data = [DataSource(content="Solve", content_type="text/plain")]

    mock_resp_json = {
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Thinking deeply..."}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Solution is 42"}],
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.json.return_value = mock_resp_json

    with patch.object(client, "_post", return_value=mock_response):
        (text, thought), _ = client._send(data)

        assert text == "Solution is 42"
        assert thought == "Thinking deeply..."


def test_responses_api_parsing_function_call(client):
    """Test parsing function calls from Responses API."""
    data = [DataSource(content="Do it", content_type="text/plain")]

    mock_resp_json = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_abc",
                "name": "my_tool",
                "arguments": '{"arg": "val"}',
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.json.return_value = mock_resp_json

    with patch.object(client, "_post", return_value=mock_response):
        (text, thought), _ = client._send(data)

        # Verify history update
        last_msg = client.conversation[-1]
        assert last_msg.role == Role.MODEL
        fc = last_msg.parts[0].function_call
        assert fc["id"] == "call_abc"
        assert fc["name"] == "my_tool"
        assert fc["args"] == {"arg": "val"}


def test_image_generation_routing(client):
    """Test that image models route to _send_image_generation."""
    client.model = "dall-e-3"
    assert client._is_image_model() is True

    with patch.object(client, "_send_image_generation") as mock_img_gen:
        mock_img_gen.return_value = (("Image generated", ""), None)
        client._send([])
        mock_img_gen.assert_called_once()


def test_video_generation_routing(client):
    """Test that video models route to _send_video_generation."""
    client.model = "sora-1.0"
    assert client._is_video_model() is True

    with patch.object(client, "_send_video_generation") as mock_vid_gen:
        mock_vid_gen.return_value = (("Video generated", ""), None)
        client._send([])
        mock_vid_gen.assert_called_once()


def test_send_image_generation_success(client):
    """Test successful image generation via DALL-E."""
    client.model = "dall-e-3"
    data = [DataSource(content="A cat", content_type="text/plain")]

    mock_response = MagicMock()
    # Mock response with b64_json
    mock_response.json.return_value = {
        "data": [{"b64_json": "fake_base64_data", "revised_prompt": "A cute cat"}]
    }

    with (
        patch.object(client, "_post", return_value=mock_response),
        patch.object(
            client,
            "_save_inline_media_and_get_log_entry",
            return_value=("Image saved", "path/to/img"),
        ),
    ):
        (text, _), _ = client._send(data)

        assert "Image saved" in text
        assert "Revised Prompt" in text
        assert "A cute cat" in text


def test_send_video_generation_polling(client):
    """Test video generation polling logic."""
    client.model = "sora"
    data = [DataSource(content="A movie", content_type="text/plain")]

    # Mock initial POST response (creation)
    mock_create_resp = MagicMock()
    mock_create_resp.json.return_value = {"id": "vid_123"}

    # Mock polling GET responses
    # 1. Processing
    mock_poll_processing = MagicMock()
    mock_poll_processing.status_code = 200
    mock_poll_processing.json.return_value = {"status": "processing"}

    # 2. Completed
    mock_poll_completed = MagicMock()
    mock_poll_completed.status_code = 200
    mock_poll_completed.json.return_value = {
        "status": "completed",
        "result_url": "https://example.com/video.mp4",
    }

    with (
        patch.object(client, "_post", return_value=mock_create_resp) as mock_post,
        patch.object(
            client, "_get", side_effect=[mock_poll_processing, mock_poll_completed]
        ) as mock_get,
        patch("time.sleep"),
        patch(
            "llm_cli.modules.media_utils.fetch_url_content",
            return_value=(b"video_bytes", "video/mp4"),
        ),
        patch.object(
            client,
            "_save_inline_media_and_get_log_entry",
            return_value=("Video saved", "path"),
        ),
    ):
        (text, _), _ = client._send(data)

        assert "Video saved" in text
        assert "https://example.com/video.mp4" in text

        # Verify mocked calls
        assert mock_post.called
        assert mock_get.call_count == 2


def test_send_with_tools(client):
    """Test _send with tools enabled."""
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

    mock_resp_json = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Tool used"}],
            }
        ],
        "usage": {"total_tokens": 10},
    }

    mock_response = MagicMock()
    mock_response.json.return_value = mock_resp_json

    with (
        patch(
            "llm_cli.clients.openai.registry.get_openai_spec",
            return_value=mock_tool_spec,
        ) as mock_registry,
        patch.object(client, "_post", return_value=mock_response) as mock_post,
    ):
        client._send(data)

        mock_registry.assert_called_once()
        # Verify payload contains tools
        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]
        assert "tools" in payload
        assert payload["tools"][0]["name"] == "test_tool"


def test_send_api_error(client):
    """Test error handling in _send."""
    data = [DataSource(content="Hello", content_type="text/plain")]

    with (
        patch.object(client, "_post", side_effect=Exception("API Error")),
        patch.object(client, "_report_error") as mock_report,
    ):
        (text, thought), _ = client._send(data)

        assert text is None
        assert thought is None
        mock_report.assert_called_once()


def test_send_image_generation_url_response(client):
    """Test image generation with URL response."""
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


def test_send_image_generation_failure(client):
    """Test image generation failure (no data)."""
    client.model = "dall-e-3"
    data = [DataSource(content="A cat", content_type="text/plain")]

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{}]}  # Empty data

    with patch.object(client, "_post", return_value=mock_response):
        (text, _), _ = client._send(data)
        assert "Failed to retrieve image data" in text


def test_send_video_generation_failure_status(client):
    """Test video generation failure status polling."""
    client.model = "sora"
    data = [DataSource(content="A movie", content_type="text/plain")]

    mock_create_resp = MagicMock()
    mock_create_resp.json.return_value = {"id": "vid_fail"}

    mock_poll_fail = MagicMock()
    mock_poll_fail.status_code = 200
    mock_poll_fail.json.return_value = {
        "status": "failed",
        "error": {"message": "Generation failed"},
    }

    with (
        patch.object(client, "_post", return_value=mock_create_resp),
        patch.object(client, "_get", return_value=mock_poll_fail),
        patch("time.sleep"),
    ):
        (text, _), _ = client._send(data)
        assert "Video generation failed: Generation failed" in text


def test_send_video_generation_timeout(client):
    """Test video generation timeout."""
    client.model = "sora"
    data = [DataSource(content="A movie", content_type="text/plain")]

    mock_create_resp = MagicMock()
    mock_create_resp.json.return_value = {"id": "vid_timeout"}

    # Always return processing
    mock_poll = MagicMock()
    mock_poll.status_code = 200
    mock_poll.json.return_value = {"status": "processing"}

    # Mock time.time to simulate timeout
    # Initial call, then loop check (start), then loop check (timeout)
    with (
        patch.object(client, "_post", return_value=mock_create_resp),
        patch.object(client, "_get", return_value=mock_poll),
        patch("time.sleep"),
        patch("time.time", side_effect=[0, 10, 2000]),
    ):
        (text, _), _ = client._send(data)
        assert "Video generation timed out" in text


def test_build_input_items_with_history_and_tools(client):
    """Test building input items with complex history including tool calls."""
    # 1. User asks
    user_msg = Message(role=Role.USER, parts=[ContentPart(text="What's 2+2?")])
    client.conversation.append(user_msg)

    # 2. Model calls tool
    tool_call = {"id": "call_1", "name": "calc", "args": {"expr": "2+2"}}
    model_msg = Message(role=Role.MODEL, parts=[ContentPart(function_call=tool_call)])
    client.conversation.append(model_msg)

    # 3. Tool responds
    tool_resp = {"id": "call_1", "name": "calc", "response": {"result": "4"}}
    tool_msg = Message(role=Role.TOOL, parts=[ContentPart(function_response=tool_resp)])
    client.conversation.append(tool_msg)

    # 4. New user input
    data = [DataSource(content="Great", content_type="text/plain")]

    items = client._build_input_items(data)

    # Verify structure
    # Item 0: User message
    assert items[0]["role"] == "user"
    assert items[0]["content"][0]["text"] == "What's 2+2?"

    # Item 1: Function call (part of model message logic, but here it's added as a separate item type for this API?)
    # Wait, looking at the code:
    # Logic in _build_input_items:
    # - It iterates history.
    # - If TOOL role: adds "function_call_output" items.
    # - If MODEL role with function_call: adds "function_call" items IF the tool_id is in "responded_tool_ids".

    # Check the tool call output item (from step 3)
    # The code iterates chronologically.

    # Let's trace expected items:
    # 1. User message (from user_msg)
    # 2. Function call (from model_msg) -> "function_call" item
    # 3. Function output (from tool_msg) -> "function_call_output" item
    # 4. New user message (from data)

    # Find function call item
    fc_item = next((i for i in items if i.get("type") == "function_call"), None)
    assert fc_item is not None
    assert fc_item["call_id"] == "call_1"

    # Find function output item
    fo_item = next((i for i in items if i.get("type") == "function_call_output"), None)
    assert fo_item is not None
    assert fo_item["call_id"] == "call_1"
    assert fo_item["output"] == "4"
