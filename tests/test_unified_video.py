from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.unified import UnifiedClient


@pytest.fixture
def mock_gemini_video_response():
    return {
        "candidates": [{"content": {"parts": [{"text": "This is a video of a cat."}]}}],
        "usageMetadata": {"totalTokenCount": 50},
    }


def test_unified_client_handles_video_via_gemini(
    mock_config, mock_gemini_video_response, tmp_path
):
    # Mocking Gemini's file upload and API response
    with patch("llm_cli.apps.gemini.GeminiClient._upload_file") as mock_upload, patch(
        "requests.post"
    ) as mock_post:

        # 1. Mock file upload result
        mock_upload.return_value = ("https://file-uri.com/video.mp4", "video/mp4")

        # 2. Mock Gemini API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_gemini_video_response
        mock_post.return_value = mock_response

        # Initialize UnifiedClient with gemini
        client = UnifiedClient(initial_provider="gemini", stdout=True)

        # Create a real dummy video file in tmp_path
        dummy_video = tmp_path / "test_video.mp4"
        dummy_video.write_bytes(b"dummy video content")

        with patch("filetype.guess") as mock_guess:
            mock_guess.return_value.mime = "video/mp4"

            # Process the "file"
            client.process_sources([str(dummy_video)])

            # Verify that GeminiClient._upload_file was called
            mock_upload.assert_called_once()

            # Verify that requests.post was called with file_data
            args, kwargs = mock_post.call_args
            payload = kwargs["json"]

            # Check if file_data is in the payload
            last_msg_parts = payload["contents"][-1]["parts"]
            has_file_data = any("file_data" in part for part in last_msg_parts)
            assert has_file_data, "Payload should contain file_data for video"

            file_part = next(part for part in last_msg_parts if "file_data" in part)
            assert (
                file_part["file_data"]["file_uri"] == "https://file-uri.com/video.mp4"
            )
            assert file_part["file_data"]["mime_type"] == "video/mp4"


if __name__ == "__main__":
    pytest.main([__file__])
