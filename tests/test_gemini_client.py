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
        mock_res.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello world"}]}}],
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


def test_to_provider_request_format_tts(gemini_client: GeminiClient) -> None:
    """Test payload construction for TTS model."""
    gemini_client.model = "tts-1"
    payload = gemini_client._to_provider_request_format([], start_index=0)

    assert "responseModalities" in payload["generationConfig"]
    assert "AUDIO" in payload["generationConfig"]["responseModalities"]
    assert "speechConfig" in payload["generationConfig"]


def test_to_provider_request_format_tools(gemini_client: GeminiClient) -> None:
    """Test payload construction with tools."""
    gemini_client.active_tools = ["test_tool"]

    with patch("llm_cli.modules.tool_registry.registry.get_gemini_spec") as mock_spec:
        mock_spec.return_value = [{"functionDeclarations": [...]}]

        payload = gemini_client._to_provider_request_format([], start_index=0)

        assert "tools" in payload
        mock_spec.assert_called_with(["test_tool"], provider="google")


def test_parse_response_with_thoughts(gemini_client: GeminiClient) -> None:
    """Test parsing response containing thinking blocks."""
    res_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "text": "Thinking..."},
                        {"text": "Answer"},
                    ]
                }
            }
        ]
    }

    msg = gemini_client._parse_response(res_json)
    assert len(msg.parts) == 2
    assert isinstance(msg.parts[0], ContentPart)
    assert msg.parts[0].thought == "Thinking..."
    assert isinstance(msg.parts[1], ContentPart)
    assert msg.parts[1].text == "Answer"


def test_send_video_generation_success(gemini_client: GeminiClient) -> None:
    """Test video generation flow."""
    gemini_client.model = "veo-2.0-generate-001"

    # 1. Start generation response
    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_post.return_value.json.return_value = {"name": "operations/123"}

        # 2. Poll response
        with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
            # Poll 1: Not done (simulated by side effect if needed, but let's go straight to done)
            # Poll 2: Done with video URI
            mock_poll_res = MagicMock()
            mock_poll_res.status_code = 200
            mock_poll_res.json.return_value = {
                "done": True,
                "response": {"result": {"video": {"uri": "http://video.url"}}},
            }

            # Download response
            mock_download_res = MagicMock()
            mock_download_res.status_code = 200
            mock_download_res.content = b"video data"
            mock_download_res.headers = {"Content-Type": "video/mp4"}

            mock_get.side_effect = [mock_poll_res, mock_download_res]

            # Mock saving
            with patch.object(
                gemini_client, "_save_inline_media_and_get_log_entry"
            ) as mock_save:
                mock_save.return_value = ("Saved video", Path("video.mp4"))

                (text, thought), _ = gemini_client._send(
                    [DataSource(content="Make video", content_type="text/plain")]
                )

                assert text is not None
                assert "Successfully generated video" in text
                assert "Saved video" in text
                assert "http://video.url" in text


def test_send_video_generation_failure(gemini_client: GeminiClient) -> None:
    """Test video generation failure during polling."""
    gemini_client.model = "veo-2.0-generate-001"

    with patch("llm_cli.clients.base.BaseLlmClient._post") as mock_post:
        mock_post.return_value.json.return_value = {"name": "operations/123"}

        with patch("llm_cli.clients.base.BaseLlmClient._get") as mock_get:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {
                "done": True,
                "error": {"message": "Generation failed"},
            }
            mock_get.return_value = mock_res

            (text, _), _ = gemini_client._send([])
            assert text is not None
            assert "Video generation failed: Generation failed" in text


def test_to_provider_request_format_system_prompt(gemini_client: GeminiClient) -> None:
    """Test system prompt inclusion."""
    gemini_client.model = "gemini-pro"
    gemini_client.system_prompt = "Sys Prompt"
    gemini_client.system_prompt_enabled = True

    payload = gemini_client._to_provider_request_format([])
    assert "system_instruction" in payload
    assert payload["system_instruction"]["parts"][0]["text"] == "Sys Prompt"


def test_to_provider_request_format_function_filtering(
    gemini_client: GeminiClient,
) -> None:
    """Test filtering of function calls without responses."""
    # History:
    # 1. User: Hi
    # 2. Model: Call tool (no response follows)
    # 3. User: Another msg

    # Message 2 should be filtered out or have parts removed because there is no matching response in 3
    gemini_client.conversation = [
        Message(Role.USER, ["Hi"]),
        Message(Role.MODEL, [ContentPart(function_call={"name": "tool", "args": {}})]),
        Message(Role.USER, ["Another msg"]),  # No function response here
    ]

    payload = gemini_client._to_provider_request_format([], start_index=0)
    contents = payload["contents"]

    # Expect: User "Hi", User "Another msg". Model message with only function call should be removed or skipped if empty.
    # The logic says: if message becomes empty, don't append it.

    # Check contents length.
    # 0: User Hi
    # 1: User Another msg
    assert len(contents) == 2
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "user"


def test_to_provider_request_format_function_pairing(
    gemini_client: GeminiClient,
) -> None:
    """Test successful pairing of function call and response."""
    gemini_client.conversation = [
        Message(Role.USER, ["Hi"]),
        Message(Role.MODEL, [ContentPart(function_call={"name": "tool", "args": {}})]),
        Message(
            Role.USER,
            [ContentPart(function_response={"name": "tool", "response": "ok"})],
        ),
    ]

    payload = gemini_client._to_provider_request_format([], start_index=0)
    contents = payload["contents"]

    assert len(contents) == 3
    assert "functionCall" in contents[1]["parts"][0]
    assert "functionResponse" in contents[2]["parts"][0]


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
