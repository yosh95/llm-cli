from unittest.mock import MagicMock, patch

from llm_cli.clients.gemini import GeminiClient


def test_process_single_source_detects_gemini_uri():
    client = GeminiClient(initial_model_alias="default", stdout=True)
    uri = "https://generativelanguage.googleapis.com/v1beta/files/abc"
    result = client._process_single_source(uri)
    assert result == {"file_uri": uri, "content_type": "image/jpeg", "is_file_or_url": True}


def test_process_single_source_with_gemini_uri_fetches_url():
    client = GeminiClient(initial_model_alias="default", stdout=True)
    # Use a URI that doesn't start with the Gemini prefix to test the fallback to super()._process_single_source
    uri = "https://example.com/video.mp4"

    with patch(
        "llm_cli.clients.gemini.GeminiClient._wait_for_file_active", return_value=True
    ):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"Content-Type": "video/mp4"}
            mock_response.content = b"fake video content"
            mock_get.return_value = mock_response

            # Mock fetch_url_content to return what we expect
            with patch("llm_cli.clients.base.fetch_url_content") as mock_fetch:
                mock_fetch.return_value = (b"fake video content", "video/mp4")
                result = client._process_single_source(uri)
                assert result == {
                    "content": b"fake video content",
                    "content_type": "video/mp4",
                    "is_file_or_url": True,
                }
