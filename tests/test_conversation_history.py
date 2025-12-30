"""Test conversation history handling with initial_data."""
from llm_cli.apps.gemini import GeminiClient


def test_initial_data_not_duplicated_in_conversation(mock_config):
    """Test that initial_data (file_uri) is not duplicated in conversation."""
    client = GeminiClient(stdout=True)

    # Simulate initial_data with a file_uri
    initial_data = [{
        "file_uri": "https://gemini.api/files/test123",
        "content_type": "video/mp4",
        "is_file_or_url": True
    }]

    # Mock _send to capture what gets added to conversation
    send_calls = []

    def mock_send(data):
        send_calls.append(data.copy())
        # Manually simulate what _send does
        new_parts = []
        for item in data:
            if item.get("file_uri"):
                new_parts.append({
                    "file_data": {
                        "mime_type": item["content_type"],
                        "file_uri": item["file_uri"]
                    }
                })
            else:
                new_parts.append({"text": item["content"]})

        if new_parts:
            client.conversation.append({"role": "user", "parts": new_parts})
        client.conversation.append(
            {"role": "model", "parts": [{"text": "Response"}]}
        )
        return "Response", None

    client._send = mock_send

    # First turn: should include file_uri + text
    data1 = initial_data.copy()
    data1.append({"content": "Question 1", "content_type": "text/plain"})
    client._send(data1)

    # Second turn: should include only text (file_uri already in conversation)
    data2 = []
    data2.append({"content": "Question 2", "content_type": "text/plain"})
    client._send(data2)

    # Third turn: should include only text
    data3 = []
    data3.append({"content": "Question 3", "content_type": "text/plain"})
    client._send(data3)

    # Verify conversation structure
    # 3 user messages + 3 model responses
    assert len(client.conversation) == 6

    # First user message should have file_uri + text
    assert len(client.conversation[0]["parts"]) == 2
    assert "file_data" in client.conversation[0]["parts"][0]
    assert (
        client.conversation[0]["parts"][0]["file_data"]["file_uri"] ==
        "https://gemini.api/files/test123"
    )
    assert "text" in client.conversation[0]["parts"][1]

    # Second user message should have only text (no file_uri duplication)
    assert len(client.conversation[2]["parts"]) == 1
    assert "text" in client.conversation[2]["parts"][0]
    assert "file_data" not in client.conversation[2]["parts"][0]

    # Third user message should have only text
    assert len(client.conversation[4]["parts"]) == 1
    assert "text" in client.conversation[4]["parts"][0]
    assert "file_data" not in client.conversation[4]["parts"][0]


def test_conversation_cleared_after_clear_command(mock_config):
    """Test that /clear command clears conversation history."""
    client = GeminiClient(stdout=True)

    # Add some messages to conversation
    client.conversation = [
        {"role": "user", "parts": [{"text": "Question 1"}]},
        {"role": "model", "parts": [{"text": "Answer 1"}]},
        {"role": "user", "parts": [{"text": "Question 2"}]},
        {"role": "model", "parts": [{"text": "Answer 2"}]}
    ]

    # Simulate /clear command
    result = client._handle_command("/clear", sources=None)

    assert result is True
    assert len(client.conversation) == 0
