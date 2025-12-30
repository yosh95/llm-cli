import pytest
from unittest.mock import patch, MagicMock
from llm_cli.apps.gemini import GeminiClient


@pytest.fixture
def mock_config_audio(mock_config):
    return mock_config


def test_gemini_audio_upload_called(mock_config_audio, tmp_path):
    # Create a dummy audio file
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"dummy audio data")

    # In refactored version, Gemini uses media_utils and its own _upload_file logic
    with patch('llm_cli.modules.media_utils.filetype.guess') as mock_guess, \
         patch('llm_cli.apps.gemini.GeminiClient._upload_file') as mock_upload:

        # Mock filetype to return audio/wav
        mock_kind = MagicMock()
        mock_kind.mime = "audio/wav"
        mock_guess.return_value = mock_kind

        # Mock upload result
        mock_upload.return_value = ("https://gemini.api/files/abc", "audio/wav")

        client = GeminiClient(initial_model_alias="default", stdout=True)
        result = client._process_single_source(str(audio_file))

        assert result == {
            "file_uri": "https://gemini.api/files/abc",
            "content_type": "audio/wav",
            "is_file_or_url": True
        }
        mock_upload.assert_called_once_with(audio_file)


def test_gemini_send_with_audio_file_uri(mock_config_audio):
    client = GeminiClient(initial_model_alias="default", stdout=True)
    data = [{
        "file_uri": "https://gemini.api/files/abc",
        "content_type": "audio/wav",
        "is_file_or_url": True
    }]

    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Heard audio"}]}}],
            "usageMetadata": {"totalTokenCount": 5}
        }
        mock_post.return_value = mock_response

        client._send(data)

        # Check payload
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        user_parts = payload['contents'][-1]['parts']

        assert any(
            part.get('file_data', {}).get('file_uri') == "https://gemini.api/files/abc"
            for part in user_parts
        )
        assert any(
            part.get('file_data', {}).get('mime_type') == "audio/wav"
            for part in user_parts
        )


def test_base_client_audio_as_base64(mock_config_audio, tmp_path):
    # Test that base client now treats audio as base64 instead of text
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"binary mp3 data")

    from llm_cli.clients.base import BaseLlmClient

    # We need a concrete implementation of BaseLlmClient to test it
    class ConcreteClient(BaseLlmClient):
        def _load_model_aliases(self):
            self.available_models = {"default": "test-model"}
            self.current_alias = "default"
            self.model = "test-model"

        def _send(self, data): return "res", {}

    with patch('llm_cli.modules.media_utils.filetype.guess') as mock_guess:
        mock_kind = MagicMock()
        mock_kind.mime = "audio/mpeg"
        mock_guess.return_value = mock_kind

        client = ConcreteClient("default", "key", "google", True, True)
        result = client._process_single_source(str(audio_file))

        assert result["content_type"] == "audio/mpeg"
        assert result["is_file_or_url"] is True
        # Should be base64
        import base64
        assert result["content"] == base64.b64encode(b"binary mp3 data").decode('utf-8')
