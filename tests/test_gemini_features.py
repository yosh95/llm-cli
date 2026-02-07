import os
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.gemini import GeminiClient
from llm_cli.modules.models import DataSource


@pytest.fixture
def mock_gemini_response_image():
    # A small 1x1 JPEG base64
    img_data = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
    # Gemini API format: thought: true flag indicates the text field contains thinking content
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": img_data}},
                        {"thought": True, "text": "This is a thought."},
                    ]
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 10},
    }


def test_gemini_saves_image_and_displays_thought(
    mock_config, mock_gemini_response_image, tmp_path
):
    # Mock requests.post
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_gemini_response_image
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)

        # Change to tmp_path so image is saved there
        from pathlib import Path

        orig_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            # Use DataSource list
            (full_text, thought_text), _ = client._send(
                [DataSource(content="Generate an image", content_type="text/plain")]
            )

            # Check if image file exists in the current directory
            # Note: mimetypes.guess_extension("image/jpeg") can return .jpg or .jpeg depending on OS
            files_jpeg = list(Path().glob("*.jp*g"))

            assert len(files_jpeg) == 1, f"Expected 1 jpeg file, found: {files_jpeg}"

            # Check if text contains thought and image path
            assert "Image generated and saved to:" in full_text
            assert "This is a thought." in thought_text
            assert files_jpeg[0].name in full_text

        finally:
            os.chdir(orig_cwd)
