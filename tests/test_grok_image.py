from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.grok import IMAGE_API_URL, GrokClient
from llm_cli.modules.models import DataSource, Role


class TestGrokImageGeneration:
    @pytest.fixture
    def mock_grok_client(self):
        with (
            patch("llm_cli.clients.config.get_setting") as mock_get_setting,
            patch("llm_cli.clients.config.get_model_aliases") as mock_get_aliases,
        ):
            # Mock configuration
            def get_setting_side_effect(key, section):
                if key == "api_key" and section == "xai":
                    return "test_key"
                if key == "api_url" and section == "xai":
                    return "https://api.x.ai/v1/chat/completions"
                return None

            mock_get_setting.side_effect = get_setting_side_effect

            # Mock model aliases
            mock_get_aliases.return_value = {
                "default": "grok-beta",
                "image": "grok-2-image-preview",
            }

            # Initialize client with required stdout arg via kwargs
            client = GrokClient(initial_model_alias="image", stdout=True)
            client.request_timeout = 10
            return client

    def test_is_image_model(self, mock_grok_client):
        """Test detection of image generation models."""
        mock_grok_client.model = "grok-2-image-preview"
        assert mock_grok_client._is_image_model() is True

        mock_grok_client.model = "grok-beta"
        assert mock_grok_client._is_image_model() is False

    @patch("llm_cli.clients.grok.GrokClient._post_with_retry")
    def test_send_image_generation_success(self, mock_post, mock_grok_client):
        """Test successful image generation with b64_json response."""
        # Ensure model is set to image model
        mock_grok_client.model = "grok-2-image-preview"

        # Mock API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "created": 1700000000,
            "data": [
                {"b64_json": "base64_image_data_here", "revised_prompt": "A cute cat"}
            ],
        }
        mock_post.return_value = mock_response

        # Mock _save_inline_media_and_get_log_entry to avoid file I/O
        with patch.object(
            mock_grok_client, "_save_inline_media_and_get_log_entry"
        ) as mock_save:
            mock_save.return_value = ("Image saved at images/img.png", None)

            data = [DataSource(content="Draw a cat", content_type="text/plain")]
            response_text, usage = mock_grok_client._send(data)

            # Verify API was called with correct URL and payload
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == IMAGE_API_URL
            payload = kwargs["json_data"]
            assert payload["model"] == "grok-2-image-preview"
            assert payload["prompt"] == "Draw a cat"
            assert payload["n"] == 1
            assert "size" not in payload  # Verify size param is absent

            # Verify response handling
            assert "Image saved at images/img.png" in response_text[0]
            assert "Revised Prompt:** A cute cat" in response_text[0]

            # Verify history update
            last_msg = mock_grok_client.conversation[-1]
            assert last_msg.role == Role.MODEL
            assert last_msg.parts[1].inline_data["data"] == "base64_image_data_here"

    @patch("llm_cli.clients.grok.GrokClient._post_with_retry")
    def test_send_image_generation_url_response(self, mock_post, mock_grok_client):
        """Test successful image generation with URL response."""
        # Ensure model is set to image model
        mock_grok_client.model = "grok-2-image-preview"

        # Mock API response with URL
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "created": 1700000000,
            "data": [
                {"url": "https://example.com/image.png", "revised_prompt": "A dog"}
            ],
        }
        mock_post.return_value = mock_response

        # Mock fetch_url_content
        with patch("llm_cli.modules.media_utils.fetch_url_content") as mock_fetch:
            mock_fetch.return_value = ("fetched_base64_data", "image/png")

            # Mock _save_inline_media_and_get_log_entry
            with patch.object(
                mock_grok_client, "_save_inline_media_and_get_log_entry"
            ) as mock_save:
                mock_save.return_value = ("Image saved at images/dog.png", None)

                data = [DataSource(content="Draw a dog", content_type="text/plain")]
                response_text, usage = mock_grok_client._send(data)

                # Verify fetch was called
                mock_fetch.assert_called_with("https://example.com/image.png")

                # Verify history update uses fetched data
                last_msg = mock_grok_client.conversation[-1]
                assert last_msg.parts[1].inline_data["data"] == "fetched_base64_data"
