import glob
import os
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.gemini import GeminiClient


@pytest.fixture
def mock_gemini_response_image():
    # A small 1x1 JPEG base64
    img_data = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": img_data}},
                        {"thought": "This is a thought."},
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
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            full_text, _ = client._send(
                [{"content": "Generate an image", "content_type": "text/plain"}]
            )

            # Check if image file exists
            # In base.py: ext_parts = mime_type.split('/'); extension = "bin"
            # if len(ext_parts) != 2 else ext_parts[1]
            # mimeType is "image/jpeg", so extension should be "jpeg".
            files_jpeg = glob.glob("generated_*.jpeg")

            assert len(files_jpeg) == 1, f"Expected 1 jpeg file, found: {files_jpeg}"

            # Check if text contains thought and image path
            assert "**output image:" in full_text
            assert "**Reasoning:** This is a thought." in full_text
            assert files_jpeg[0] in full_text

        finally:
            os.chdir(orig_cwd)
