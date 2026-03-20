from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.openai import IMAGE_API_URL, OpenAIClient
from llm_cli.modules.models import DataSource, Role


class TestOpenAIImageGeneration:
    @pytest.fixture
    def mock_openai_client(self):
        with (
            patch("llm_cli.clients.config.config_manager.get") as mock_get_setting,
            patch(
                "llm_cli.clients.config.config_manager.get_model_aliases"
            ) as mock_get_aliases,
        ):
            # Mock configuration
            def get_setting_side_effect(key, section):
                if key == "api_key" and section == "openai":
                    return "test_key"
                if key == "api_url" and section == "openai":
                    return "https://api.openai.com/v1/responses"
                return None

            mock_get_setting.side_effect = get_setting_side_effect

            # Mock model aliases
            mock_get_aliases.return_value = {
                "default": "gpt-4o",
                "image": "dall-e-3",
            }

            # Initialize client with required stdout arg via kwargs
            client = OpenAIClient(initial_model_alias="image", stdout=True)
            client.request_timeout = 10
            return client

    def test_is_image_model(self, mock_openai_client):
        """Test detection of image generation models."""
        mock_openai_client.model = "dall-e-3"
        assert mock_openai_client._is_image_model() is True

        mock_openai_client.model = "gpt-4o"
        assert mock_openai_client._is_image_model() is False

    @patch("llm_cli.clients.openai.OpenAIClient._post")
    def test_send_image_generation_success(self, mock_post, mock_openai_client):
        """Test successful image generation with b64_json response and return value structure."""
        # Ensure model is set to image model
        mock_openai_client.model = "dall-e-3"

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
            mock_openai_client, "_save_inline_media_and_get_log_entry"
        ) as mock_save:
            mock_save.return_value = ("Image saved at images/img.png", None)

            data = [DataSource(content="Draw a cat", content_type="text/plain")]

            # Execute _send, which delegates to _send_image_generation
            response_tuple, usage = mock_openai_client._send(data)

            # --- Check return value structure (The Fix Verification) ---
            # response_tuple should be (text, thought)
            assert isinstance(response_tuple, tuple)
            assert len(response_tuple) == 2
            text_content, thought_content = response_tuple

            # Text content should contain the success message
            assert "Image saved at images/img.png" in text_content
            assert "Revised Prompt:** A cute cat" in text_content

            # Thought content should be empty string for image generation
            assert thought_content == ""

            # Usage should be None for image generation currently
            assert usage is None

            # Verify API was called with correct URL and payload
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == IMAGE_API_URL
            payload = kwargs["json_data"]
            assert payload["model"] == "dall-e-3"
            assert payload["prompt"] == "Draw a cat"
            assert payload["n"] == 1
            assert payload["size"] == "1024x1024"

            # Verify history update
            last_msg = mock_openai_client.conversation[-1]
            assert last_msg.role == Role.MODEL
            assert last_msg.parts[1].inline_data["data"] == "base64_image_data_here"

    @patch("llm_cli.clients.openai.OpenAIClient._post")
    def test_send_image_generation_failure(self, mock_post, mock_openai_client):
        """Test image generation failure handling."""
        mock_openai_client.model = "dall-e-3"

        # Mock API exception
        mock_post.side_effect = Exception("API Error")

        data = [DataSource(content="Draw a cat", content_type="text/plain")]

        with patch.object(mock_openai_client, "_report_error") as mock_report:
            response_tuple, usage = mock_openai_client._send(data)

            # Verify structure even on failure
            assert isinstance(response_tuple, tuple)
            assert len(response_tuple) == 2
            assert response_tuple[0] is None
            assert response_tuple[1] is None
            assert usage is None

            mock_report.assert_called_once()
