from unittest.mock import MagicMock, patch

from llm_cli.apps.unified import UnifiedClient


def test_unified_client_handles_video_via_gemini(mock_config, tmp_path):
    # Create a dummy video file
    video_file = tmp_path / "test.mp4"
    video_file.write_bytes(b"dummy video data")

    # Mock filetype to return video/mp4
    with (
        patch("llm_cli.modules.media_utils.filetype.guess") as mock_guess,
        patch(
            "llm_cli.clients.gemini.GeminiClient._upload_file"
        ) as mock_upload,
        patch("llm_cli.clients.gemini.GeminiClient._send") as mock_send,
        patch("llm_cli.clients.session.ChatSession.run") as mock_run,
    ):
        mock_kind = MagicMock()
        mock_kind.mime = "video/mp4"
        mock_guess.return_value = mock_kind

        # Mock upload result
        mock_upload.return_value = ("https://gemini.api/files/abc", "video/mp4")
        # Mock send result
        mock_send.return_value = ("Video processed", {"totalTokens": 100})

        client = UnifiedClient(initial_model_alias="gemini-flash", stdout=True)
        # Use process_sources instead of talk to trigger the upload logic
        # Combined video and text prompt
        client.process_sources([str(video_file), "What is in this video?"])

        # GeminiClient._upload_file should be called for the video
        mock_upload.assert_called_once()
        
        # UnifiedClient._send should be called via process_and_print
        mock_send.assert_called_once()
