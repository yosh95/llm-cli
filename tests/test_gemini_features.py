import os
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.gemini import GeminiClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


@pytest.fixture
def mock_gemini_response_image():
    # A small 1x1 JPEG base64
    img_data = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
    # generateContent API response format
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": img_data}},
                        {"text": "This is a thought."},
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 10},
    }


def test_gemini_saves_image_and_displays_thought(mock_config, mock_gemini_response_image, tmp_path):
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

            # Check if text contains image path
            assert "Image generated and saved to:" in full_text
            assert "This is a thought." in full_text
            assert files_jpeg[0].name in full_text

        finally:
            os.chdir(orig_cwd)


def test_gemini_send_builds_correct_url(mock_config):
    """Verify _send calls the generateContent endpoint (not interactions)."""
    response_payload = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "Hello!"}]}}],
        "usageMetadata": {"totalTokenCount": 5},
    }

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_payload
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)
        client._send([DataSource(content="Hi", content_type="text/plain")])

        called_url = mock_post.call_args[0][0]
        assert ":generateContent" in called_url
        assert "interactions" not in called_url


def test_gemini_stateless_full_history_sent(mock_config):
    """Verify that the full conversation history is included in every request."""

    def turn_response(text: str) -> dict:
        return {
            "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}],
            "usageMetadata": {"totalTokenCount": 5},
        }

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)

        # First turn
        mock_response.json.return_value = turn_response("Reply 1")
        client._send([DataSource(content="Hello", content_type="text/plain")])

        # Second turn
        mock_response.json.return_value = turn_response("Reply 2")
        client._send([DataSource(content="How are you?", content_type="text/plain")])

        # The second request's payload must contain the first exchange in contents
        second_payload = mock_post.call_args_list[1][1]["json"]
        contents = second_payload["contents"]

        # contents should include: user(Hello), model(Reply 1), user(How are you?)
        assert len(contents) == 3
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"][0]["text"] == "Hello"
        assert contents[1]["role"] == "model"
        assert contents[1]["parts"][0]["text"] == "Reply 1"
        assert contents[2]["role"] == "user"
        assert contents[2]["parts"][0]["text"] == "How are you?"


def test_gemini_tool_call_round_trip(mock_config):
    """Verify functionCall / functionResponse serialisation through the history."""
    tool_call_response = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            # thoughtSignature is a part-level sibling of functionCall
                            "functionCall": {
                                "id": "call_1",
                                "name": "my_tool",
                                "args": {"x": 1},
                            },
                            "thoughtSignature": "sig_abc",
                        }
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 5},
    }
    final_response = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "Done"}]}}],
        "usageMetadata": {"totalTokenCount": 5},
    }

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)

        # First turn: model requests a tool call (with thoughtSignature)
        mock_response.json.return_value = tool_call_response
        client._send([DataSource(content="Call my tool", content_type="text/plain")])

        # Simulate tool result being appended to history
        client.conversation.append(
            Message(
                role=Role.TOOL,
                parts=[
                    ContentPart(
                        function_response={
                            "id": "call_1",
                            "name": "my_tool",
                            "response": {"result": "tool output"},
                        }
                    )
                ],
            )
        )

        # Second turn: submit tool result
        mock_response.json.return_value = final_response
        client._send([DataSource(content="Continue", content_type="text/plain")])

        second_payload = mock_post.call_args_list[1][1]["json"]
        contents = second_payload["contents"]

        # Expect: user(Call my tool), model(functionCall+sig), user(functionResponse), user(Continue)
        roles = [c["role"] for c in contents]
        assert roles.count("user") >= 2
        assert roles.count("model") >= 1

        # The functionResponse must be present
        has_func_response = any(
            "functionResponse" in p for c in contents for p in c.get("parts", [])
        )
        assert has_func_response

        # thoughtSignature must be echoed back as a part-level field on functionCall
        has_thought_sig = any(
            p.get("thoughtSignature") == "sig_abc"
            for c in contents
            for p in c.get("parts", [])
            if "functionCall" in p
        )
        assert has_thought_sig, "thoughtSignature must be echoed back as a sibling of functionCall"


def test_gemini_thought_signature_on_function_call(mock_config):
    """
    Gemini 3 thinking models return thoughtSignature as a part-level sibling
    of functionCall.  Verify that:
      1. The parser stores it in ContentPart.thought_signature.
      2. _build_contents re-emits it at the part level (not inside functionCall).
    """
    tool_call_response = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "fc_1",
                                "name": "search_web",
                                "args": {"query": "test"},
                            },
                            "thoughtSignature": "ENCRYPTED_SIG_XYZ",
                        }
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 5},
    }
    follow_up_response = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "Result"}]}}],
        "usageMetadata": {"totalTokenCount": 5},
    }

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)

        # Turn 1: model responds with a function call carrying a thoughtSignature
        mock_response.json.return_value = tool_call_response
        client._send([DataSource(content="Search something", content_type="text/plain")])

        # Verify parser stored the signature correctly
        last_model_msg = client.conversation[-1]
        assert last_model_msg.role == Role.MODEL
        fc_part = next(
            p for p in last_model_msg.parts if isinstance(p, ContentPart) and p.function_call
        )
        assert fc_part.thought_signature == "ENCRYPTED_SIG_XYZ", (
            "Parser must store thoughtSignature in ContentPart.thought_signature"
        )

        # Append tool result
        client.conversation.append(
            Message(
                role=Role.TOOL,
                parts=[
                    ContentPart(
                        function_response={
                            "id": "fc_1",
                            "name": "search_web",
                            "response": {"result": "some result"},
                        }
                    )
                ],
            )
        )

        # Turn 2: send follow-up — thoughtSignature must appear in the payload
        mock_response.json.return_value = follow_up_response
        client._send([DataSource(content="Summarise", content_type="text/plain")])

        payload = mock_post.call_args_list[1][1]["json"]
        contents = payload["contents"]

        # Find the model turn that contains the functionCall
        fc_content = next(
            c
            for c in contents
            if c["role"] == "model" and any("functionCall" in p for p in c["parts"])
        )

        fc_wire_part = next(p for p in fc_content["parts"] if "functionCall" in p)

        # thoughtSignature must be a sibling key at the part level
        assert fc_wire_part.get("thoughtSignature") == "ENCRYPTED_SIG_XYZ", (
            "thoughtSignature must be emitted as a part-level sibling of functionCall"
        )
        # It must NOT be nested inside functionCall itself
        assert "thoughtSignature" not in fc_wire_part["functionCall"], (
            "thoughtSignature must NOT be nested inside the functionCall dict"
        )


def test_gemini_thinking_response_parsed(mock_config):
    """Verify that thought parts are separated from response text."""
    response_payload = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "My reasoning here."},
                        {"text": "The answer is 42."},
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 10},
    }

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_payload
        mock_post.return_value = mock_response

        client = GeminiClient(stdout=True)
        (text, thought), _ = client._send(
            [DataSource(content="What is 6*7?", content_type="text/plain")]
        )

        assert thought == "My reasoning here."
        assert text == "The answer is 42."


def test_gemini_no_interaction_id_attribute(mock_config):
    """GeminiClient must not carry any interaction-ID state."""
    client = GeminiClient(stdout=True)
    assert not hasattr(client, "last_interaction_id"), (
        "GeminiClient should not have last_interaction_id after migration to generateContent API"
    )
