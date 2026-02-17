"""Tests for GeminiClient functionality."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.gemini import GeminiClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def gemini_client(mock_config: object) -> GeminiClient:
    """Fixture for GeminiClient."""
    return GeminiClient(stdout=False)


def test_initialization(gemini_client: GeminiClient) -> None:
    """Test client initialization."""
    # Matches the mock_config default
    assert gemini_client.api_key == "test_api_key_1234567890"
    assert gemini_client.config_section == "google"
    assert gemini_client.pdf_as_base64 is True


def test_process_single_source_fallback(gemini_client: GeminiClient) -> None:
    """Test fallback to super()._process_single_source."""
    with patch(
        "llm_cli.clients.base.BaseLlmClient._process_single_source"
    ) as mock_super:
        mock_super.return_value = DataSource(content="text", content_type="text/plain")

        # Pass a simple text string, not a path
        source = gemini_client._process_single_source("some text")

        assert source is not None
        assert source.content == "text"
        mock_super.assert_called_with("some text")


def test_handle_command(gemini_client: GeminiClient) -> None:
    """Test command handling delegation."""
    with patch("llm_cli.clients.base.BaseLlmClient._handle_command") as mock_super:
        mock_super.return_value = True
        assert gemini_client._handle_command("/help", None) is True
        mock_super.assert_called()

    with patch("llm_cli.clients.base.BaseLlmClient._handle_command") as mock_super:
        mock_super.return_value = False
        assert gemini_client._handle_command("not a command", None) is False


def test_load_model_aliases_warning(gemini_client: GeminiClient) -> None:
    """Test warning when no models configured."""
    with patch("llm_cli.clients.config.get_model_aliases") as mock_get:
        mock_get.return_value = {}
        with patch("llm_cli.clients.gemini.console.print") as mock_print:
            gemini_client._load_model_aliases()
            mock_print.assert_called()
            assert "Warning: No models configured" in mock_print.call_args[0][0]


def test_send_normal_success(gemini_client: GeminiClient) -> None:
    """Test normal text generation."""
    gemini_client.model = "gemini-pro"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        # Updated to match Interactions API format
        mock_res.json.return_value = {
            "outputs": [{"type": "text", "text": "Hello world"}],
            "usageMetadata": {"totalTokenCount": 10},
        }
        mock_post.return_value = mock_res

        (text, thought), usage = gemini_client._send(
            [DataSource(content="Hi", content_type="text/plain")]
        )

        assert text == "Hello world"
        assert usage is not None
        assert usage["totalTokenCount"] == 10
        assert len(gemini_client.conversation) == 2  # User + Model


def test_send_with_usage_key_fallback(gemini_client: GeminiClient) -> None:
    """Test fallback to 'usage' key when 'usageMetadata' is missing."""
    gemini_client.model = "gemini-pro"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        # Mock response with 'usage' key (snake_case) as observed in bug report
        mock_res.json.return_value = {
            "outputs": [{"type": "text", "text": "Hello world"}],
            "usage": {"total_tokens": 1870},
        }
        mock_post.return_value = mock_res

        (text, thought), usage = gemini_client._send(
            [DataSource(content="Hi", content_type="text/plain")]
        )

        assert text == "Hello world"
        assert usage is not None
        assert usage["total_tokens"] == 1870


def test_send_api_error(gemini_client: GeminiClient) -> None:
    """Test API error handling in _send."""
    gemini_client.model = "gemini-pro"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_post.side_effect = Exception("API Error")
        with patch.object(gemini_client, "_report_error") as mock_report:
            (text, thought), usage = gemini_client._send(
                [DataSource(content="Hi", content_type="text/plain")]
            )

            assert text is None
            assert usage is None
            mock_report.assert_called()


def test_process_single_source_file_uri(gemini_client: GeminiClient) -> None:
    """Test processing a Gemini File API URI."""
    uri = "https://generativelanguage.googleapis.com/v1beta/files/abc"
    source = gemini_client._process_single_source(uri)
    assert source is not None
    assert source.is_file_or_url is True
    assert source.metadata["file_uri"] == uri


def test_process_single_source_large_file(
    gemini_client: GeminiClient, tmp_path: Path
) -> None:
    """Test processing a large file triggering upload."""
    large_file = tmp_path / "large.pdf"
    large_file.write_bytes(b"0" * (10 * 1024 * 1024 + 1))  # > 10MB

    with patch.object(gemini_client, "_upload_file") as mock_upload:
        mock_upload.return_value = ("file-uri", "application/pdf")

        source = gemini_client._process_single_source(str(large_file))

        assert source is not None
        assert source.metadata["file_uri"] == "file-uri"
        assert source.content_type == "application/pdf"
        mock_upload.assert_called_once()


def test_process_single_source_video(
    gemini_client: GeminiClient, tmp_path: Path
) -> None:
    """Test processing a video file triggering upload."""
    video_file = tmp_path / "video.mp4"
    video_file.touch()

    with patch("filetype.guess") as mock_guess:
        mock_guess.return_value = MagicMock(mime="video/mp4")
        with patch.object(gemini_client, "_upload_file") as mock_upload:
            mock_upload.return_value = ("video-uri", "video/mp4")

            source = gemini_client._process_single_source(str(video_file))

            assert source is not None
            assert source.metadata["file_uri"] == "video-uri"
            assert source.content_type == "video/mp4"


def test_upload_file_success(gemini_client: GeminiClient, tmp_path: Path) -> None:
    """Test successful file upload."""
    f = tmp_path / "test.txt"
    f.write_text("content")

    with patch("llm_cli.clients.gemini.requests.post") as mock_post:
        # Start upload response
        mock_start_res = MagicMock()
        mock_start_res.headers = {"X-Goog-Upload-URL": "http://upload.url"}

        # Upload content response
        mock_upload_res = MagicMock()
        mock_upload_res.json.return_value = {
            "file": {"name": "files/abc", "uri": "file-uri"}
        }

        mock_post.side_effect = [mock_start_res, mock_upload_res]

        with patch.object(gemini_client, "_wait_for_file_active", return_value=True):
            res = gemini_client._upload_file(f)
            assert res is not None
            uri, mime = res
            assert uri == "file-uri"
            assert mime == "text/plain"


def test_wait_for_file_active_success(gemini_client: GeminiClient) -> None:
    """Test polling for file active status."""
    with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
        mock_res = MagicMock()
        mock_res.json.side_effect = [{"state": "PROCESSING"}, {"state": "ACTIVE"}]
        mock_get.return_value = mock_res

        assert gemini_client._wait_for_file_active("files/abc") is True
        assert mock_get.call_count == 2


def test_wait_for_file_active_failed(gemini_client: GeminiClient) -> None:
    """Test polling where file status becomes FAILED."""
    with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
        mock_res = MagicMock()
        mock_res.json.return_value = {"state": "FAILED"}
        mock_get.return_value = mock_res

        assert gemini_client._wait_for_file_active("files/abc") is False


def test_send_with_tts_config(gemini_client: GeminiClient) -> None:
    """Test payload construction for TTS model."""
    gemini_client.model = "tts-1-preview"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"outputs": [{"type": "text", "text": "Audio"}]}
        mock_post.return_value = mock_res

        gemini_client._send([DataSource(content="Speak", content_type="text/plain")])

        call_args = mock_post.call_args
        assert call_args is not None
        payload = call_args[1]["json_data"]

        assert "generation_config" in payload
        assert "response_modalities" in payload["generation_config"]
        assert "AUDIO" in payload["generation_config"]["response_modalities"]
        assert "speech_config" in payload["generation_config"]


def test_send_with_tools(gemini_client: GeminiClient) -> None:
    """Test payload construction with tools."""
    gemini_client.active_tools = ["test_tool"]
    gemini_client.model = "gemini-pro"

    with patch(
        "llm_cli.modules.tool_registry.registry.get_gemini_interactions_spec"
    ) as mock_spec:
        mock_spec.return_value = [{"function_declarations": [...]}]

        with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {"outputs": [{"type": "text", "text": "OK"}]}
            mock_post.return_value = mock_res

            gemini_client._send(
                [DataSource(content="Use tool", content_type="text/plain")]
            )

            mock_spec.assert_called_with(["test_tool"], provider="google")

            call_args = mock_post.call_args
            payload = call_args[1]["json_data"]
            assert "tools" in payload


def test_send_parses_response(gemini_client: GeminiClient) -> None:
    """Test parsing response from Interactions API."""
    gemini_client.model = "gemini-pro"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        # Interactions API response format
        mock_res.json.return_value = {
            "outputs": [
                {"type": "text", "text": "Answer"},
                {"type": "image", "data": "base64...", "mime_type": "image/png"},
            ]
        }
        mock_post.return_value = mock_res

        # Mock saving inline image
        with patch.object(
            gemini_client, "_save_inline_media_and_get_log_entry"
        ) as mock_save:
            mock_save.return_value = ("[Image saved]", Path("img.png"))

            (text, thought), _ = gemini_client._send(
                [DataSource(content="Hi", content_type="text/plain")]
            )

            assert text is not None
            assert "Answer" in text
            assert "[Image saved]" in text
            assert thought == ""


def test_send_with_system_prompt(gemini_client: GeminiClient) -> None:
    """Test system prompt inclusion in the first turn."""
    gemini_client.model = "gemini-pro"
    gemini_client.system_prompt = "Sys Prompt"
    gemini_client.system_prompt_enabled = True
    gemini_client.last_interaction_id = None  # Ensure first turn

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"outputs": [{"type": "text", "text": "OK"}]}
        mock_post.return_value = mock_res

        gemini_client._send([DataSource(content="Hi", content_type="text/plain")])

        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]

        # System prompt should be prepended to inputs
        assert len(payload["input"]) >= 2
        assert payload["input"][0]["text"] == "System: Sys Prompt"


def test_send_with_tool_result(gemini_client: GeminiClient) -> None:
    """Test that tool results are included in the request."""
    gemini_client.model = "gemini-pro"

    # Simulate history where the last message was a tool execution
    tool_msg = Message(
        Role.TOOL,
        [
            ContentPart(
                function_response={
                    "name": "my_tool",
                    "id": "call_123",
                    "response": {"result": "success"},
                }
            )
        ],
    )
    gemini_client.conversation = [tool_msg]

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"outputs": [{"type": "text", "text": "OK"}]}
        mock_post.return_value = mock_res

        # User sends follow-up or just continues
        gemini_client._send([])

        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]

        # Check if function_result is in input
        assert any(item.get("type") == "function_result" for item in payload["input"])
        item = next(
            item for item in payload["input"] if item.get("type") == "function_result"
        )
        assert item["name"] == "my_tool"
        assert item["call_id"] == "call_123"
        assert item["result"] == "success"


def test_send_video_generation_patterns(gemini_client: GeminiClient) -> None:
    """Test different video generation response patterns."""
    gemini_client.model = "veo-2.0-generate-001"

    patterns: list[dict[str, Any]] = [
        # Pattern 1: Vertex AI
        {"predictions": [{"video": {"uri": "http://v1"}}]},
        # Pattern 2: Direct result
        {"result": {"video": {"uri": "http://v2"}}},
        # Pattern 3: generateVideoResponse
        {
            "generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "http://v3"}}]
            }
        },
    ]

    for pat in patterns:
        with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
            mock_post.return_value.json.return_value = {"name": "op"}
            with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
                mock_poll = MagicMock()
                mock_poll.status_code = 200
                mock_poll.json.return_value = {"done": True, "response": pat}

                # Mock download failure to avoid saving logic complexity here
                mock_dl = MagicMock()
                mock_dl.status_code = 404

                mock_get.side_effect = [mock_poll, mock_dl]

                (text, _), _ = gemini_client._send([])
                assert text is not None

                # Check that correct URI was found (even if download failed)
                expected_uri = list(pat.values())[0]
                if "predictions" in pat:
                    expected_uri = "http://v1"
                elif "result" in pat:
                    expected_uri = "http://v2"
                elif "generateVideoResponse" in pat:
                    expected_uri = "http://v3"

                assert expected_uri in text


def test_send_video_generation_download_fail(gemini_client: GeminiClient) -> None:
    """Test video download failure."""
    gemini_client.model = "veo-2.0-generate-001"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_post.return_value.json.return_value = {"name": "op"}
        with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
            mock_poll = MagicMock()
            mock_poll.status_code = 200
            mock_poll.json.return_value = {
                "done": True,
                "response": {"result": {"video": {"uri": "http://v"}}},
            }

            mock_dl = MagicMock()
            mock_dl.status_code = 500  # Fail

            mock_get.side_effect = [mock_poll, mock_dl]

            with patch("llm_cli.clients.gemini.console.print") as mock_print:
                gemini_client._send([])
                assert "Failed to download video" in mock_print.call_args_list[-1][0][0]


def test_wait_for_file_active_timeout(gemini_client: GeminiClient) -> None:
    """Test polling timeout."""
    with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
        mock_get.return_value.json.return_value = {"state": "PROCESSING"}
        # Make range small to exit loop quickly
        with patch("llm_cli.clients.gemini.range", return_value=[0]):
            assert gemini_client._wait_for_file_active("f") is False


def test_upload_file_fail_mime(gemini_client: GeminiClient, tmp_path: Path) -> None:
    """Test upload failure when mime type cannot be guessed."""
    f = tmp_path / "unknown"
    f.touch()

    with patch("mimetypes.guess_type", return_value=(None, None)):
        assert gemini_client._upload_file(f) is None


def test_upload_file_exception(gemini_client: GeminiClient, tmp_path: Path) -> None:
    """Test upload exception handling."""
    f = tmp_path / "test.txt"
    f.touch()

    with patch(
        "llm_cli.clients.gemini.requests.post", side_effect=Exception("Upload Error")
    ):
        with patch.object(gemini_client, "_report_error") as mock_report:
            assert gemini_client._upload_file(f) is None
            mock_report.assert_called()
