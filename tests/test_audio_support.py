from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.gemini import GeminiClient
from llm_cli.modules.models import DataSource


@pytest.fixture
def mock_config_audio(mock_config):
    return mock_config


def test_gemini_audio_upload_called(mock_config_audio, tmp_path):
    # Create a dummy audio file
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"dummy audio data")

    with (
        patch("llm_cli.modules.media_utils.filetype.guess") as mock_guess,
        patch("llm_cli.clients.gemini_handlers.upload_file") as mock_upload,
    ):
        mock_kind = MagicMock()
        mock_kind.mime = "audio/wav"
        mock_guess.return_value = mock_kind

        # Mock upload result
        mock_upload.return_value = ("https://gemini.api/files/abc", "audio/wav")

        client = GeminiClient(initial_model_alias="default", stdout=True)
        result = client._process_single_source(str(audio_file))

        assert isinstance(result, DataSource)
        assert result.metadata["file_uri"] == "https://gemini.api/files/abc"
        assert result.content_type == "audio/wav"
        assert result.is_file_or_url is True
        mock_upload.assert_called_once_with(client, audio_file, mime_type="audio/wav")


def test_gemini_send_with_audio_file_uri(mock_config_audio):
    client = GeminiClient(initial_model_alias="default", stdout=True)
    # Use DataSource dataclass
    data = [
        DataSource(
            content="audio/wav",
            content_type="audio/wav",
            is_file_or_url=True,
            metadata={"file_uri": "https://gemini.api/files/abc"},
        )
    ]

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        # generateContent API response format
        mock_response.json.return_value = {
            "candidates": [{"content": {"role": "model", "parts": [{"text": "Heard audio"}]}}],
            "usageMetadata": {"totalTokenCount": 5},
        }
        mock_post.return_value = mock_response

        client._send(data)

        # Check payload
        args, kwargs = mock_post.call_args
        payload = kwargs.get("json") or args[1]

        # generateContent API uses 'contents' list
        assert "contents" in payload

        # The audio should appear as fileData inside the user turn
        found_audio = False
        for content_item in payload["contents"]:
            for part in content_item.get("parts", []):
                fd = part.get("fileData", {})
                if (
                    fd.get("fileUri") == "https://gemini.api/files/abc"
                    and fd.get("mimeType") == "audio/wav"
                ):
                    found_audio = True
                    break

        assert found_audio, f"Audio fileData not found in contents: {payload}"


def test_base_client_audio_as_base64(mock_config_audio, tmp_path):
    # Test that base client now treats audio as base64 instead of text
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"binary mp3 data")

    from llm_cli.clients.base import BaseLlmClient, ProviderSpec

    class ConcreteClient(BaseLlmClient):
        def _load_model_aliases(self):
            self.available_models = {"default": "test-model"}
            self.current_alias = "default"
            self.model = "test-model"

        def _send(self, _data):
            return ("res", ""), {}

        def utility_send(self, _system_prompt, _user_prompt, _json_mode=False):
            return "mocked response"

    with patch("llm_cli.modules.media_utils.filetype.guess") as mock_guess:
        mock_kind = MagicMock()
        mock_kind.mime = "audio/mpeg"
        mock_guess.return_value = mock_kind

        client = ConcreteClient("default", ProviderSpec("key", "google", True), stdout=True)
        result = client._process_single_source(str(audio_file))

        assert isinstance(result, DataSource)
        assert result.content_type == "audio/mpeg"
        assert result.is_file_or_url is True

        import base64

        assert result.content == base64.b64encode(b"binary mp3 data").decode("utf-8")
