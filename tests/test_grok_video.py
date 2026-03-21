from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.grok import (
    VIDEO_GENERATION_URL,
    VIDEO_RESULT_URL_TEMPLATE,
    GrokClient,
)
from llm_cli.modules.models import DataSource, Role


class TestGrokVideoGeneration:
    @pytest.fixture
    def mock_grok_client(self):
        with (
            patch("llm_cli.clients.config.config_manager.get") as mock_get_setting,
            patch(
                "llm_cli.clients.config.config_manager.get_model_aliases"
            ) as mock_get_aliases,
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
                "video": "grok-imagine-video",
            }

            # Initialize client with required stdout arg via kwargs
            client = GrokClient(initial_model_alias="video", stdout=True)
            client.request_timeout = 10
            return client

    def test_is_video_model(self, mock_grok_client):
        """Test detection of video generation models."""
        mock_grok_client.model = "grok-imagine-video"
        assert mock_grok_client._is_video_model() is True
        assert mock_grok_client._is_image_model() is False

        mock_grok_client.model = "grok-2-image-preview"
        assert mock_grok_client._is_video_model() is False
        # The logic in GrokClient is: return "image" in m and "video" not in m
        assert mock_grok_client._is_image_model() is True

        mock_grok_client.model = "grok-beta"
        assert mock_grok_client._is_video_model() is False

    @patch("llm_cli.clients.grok.GrokClient._post")
    @patch("llm_cli.clients.grok.GrokClient._get")
    @patch("time.sleep", return_value=None)  # Skip sleep
    def test_send_video_generation_success(
        self, _mock_sleep, mock_get, mock_post, mock_grok_client
    ):
        """Test successful video generation workflow."""
        # Ensure model is set to video model
        mock_grok_client.model = "grok-imagine-video"

        # 1. Mock Start Generation Response
        mock_start_response = MagicMock()
        mock_start_response.json.return_value = {
            "request_id": "req-12345",
            "status": "pending",
        }
        mock_post.return_value = mock_start_response

        # 2. Mock Polling Responses
        # First call: pending
        # Second call: completed with URL
        mock_poll_pending = MagicMock()
        mock_poll_pending.status_code = 200
        mock_poll_pending.json.return_value = {"status": "pending"}

        mock_poll_completed = MagicMock()
        mock_poll_completed.status_code = 200
        mock_poll_completed.json.return_value = {
            "status": "completed",
            "url": "https://example.com/video.mp4",
        }

        mock_get.side_effect = [mock_poll_pending, mock_poll_completed]

        data = [DataSource(content="Make a video of a cat", content_type="text/plain")]

        # Capture stdout to avoid printing during test
        with patch("builtins.print"):
            response_text, _usage = mock_grok_client._send(data)

        # Verify Post call (Start Generation)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == VIDEO_GENERATION_URL
        assert kwargs["json_data"]["prompt"] == "Make a video of a cat"

        # Verify Get calls (Polling)
        assert mock_get.call_count == 2
        expected_poll_url = VIDEO_RESULT_URL_TEMPLATE.format("req-12345")
        mock_get.assert_called_with(
            expected_poll_url, headers=kwargs["headers"], timeout=10
        )

        # Verify Result
        assert "Successfully generated media" in response_text[0]
        assert "https://example.com/video.mp4" in response_text[0]

        # Verify history update
        last_msg = mock_grok_client.conversation[-1]
        assert last_msg.role == Role.MODEL
        assert "https://example.com/video.mp4" in last_msg.parts[0].text

    @patch("llm_cli.clients.grok.GrokClient._post")
    @patch("llm_cli.clients.grok.GrokClient._get")
    @patch("time.sleep", return_value=None)
    def test_send_video_generation_failure(
        self, _mock_sleep, mock_get, mock_post, mock_grok_client
    ):
        """Test video generation failure handling."""
        mock_grok_client.model = "grok-imagine-video"

        # 1. Mock Start
        mock_post.return_value.json.return_value = {"request_id": "req-fail"}

        # 2. Mock Poll Failure
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "failed",
            "error": "Content policy violation",
        }

        with patch("builtins.print"):
            response_text, _usage = mock_grok_client._send(
                [DataSource(content="Bad video", content_type="text/plain")]
            )

        assert "Video generation failed" in response_text[0]
        assert "Content policy violation" in response_text[0]
