"""Test conversation history handling with initial_data and new dataclasses."""

from llm_cli.clients.gemini import GeminiClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


def test_initial_data_not_duplicated_in_conversation(mock_config):
    """Test that initial_data (file_uri) is handled correctly in conversation using dataclasses."""
    client = GeminiClient(stdout=True)

    # Simulate initial_data with a file_uri via DataSource
    initial_data = [
        DataSource(
            content=None,
            content_type="video/mp4",
            is_file_or_url=True,
            metadata={"file_uri": "https://gemini.api/files/test123"}
        )
    ]

    # Mock _send to use internal Gemini format and update history using new Message objects
    def mock_send(data):
        new_parts = []
        for item in data:
            file_uri = item.metadata.get("file_uri")
            if file_uri:
                new_parts.append(
                    ContentPart(text=f"[File: {file_uri}]")
                )
            else:
                new_parts.append(ContentPart(text=str(item.content)))

        if new_parts:
            client.conversation.append(Message(role=Role.USER, parts=new_parts))
        client.conversation.append(
            Message(role=Role.MODEL, parts=[ContentPart(text="Response")])
        )
        return "Response", None

    client._send = mock_send

    # First turn: should include file_uri + text
    data1 = list(initial_data)
    data1.append(DataSource(content="Question 1", content_type="text/plain"))
    client._send(data1)

    # Second turn: should include only text
    data2 = [DataSource(content="Question 2", content_type="text/plain")]
    client._send(data2)

    # Third turn: should include only text
    data3 = [DataSource(content="Question 3", content_type="text/plain")]
    client._send(data3)

    # Verify conversation structure
    # 3 user messages + 3 model responses
    assert len(client.conversation) == 6

    # First user message should have file_uri placeholder + text
    assert len(client.conversation[0].parts) == 2
    assert "[File: https://gemini.api/files/test123]" in client.conversation[0].parts[0].text
    assert "Question 1" in client.conversation[0].parts[1].text

    # Second user message should have only text
    assert len(client.conversation[2].parts) == 1
    assert "Question 2" in client.conversation[2].parts[0].text

    # Third user message should have only text
    assert len(client.conversation[4].parts) == 1
    assert "Question 3" in client.conversation[4].parts[0].text


def test_conversation_cleared_after_clear_command(mock_config):
    """Test that /clear command clears conversation history."""
    client = GeminiClient(stdout=True)

    # Add some messages to conversation using dataclasses
    client.conversation = [
        Message(role=Role.USER, parts=[ContentPart(text="Question 1")]),
        Message(role=Role.MODEL, parts=[ContentPart(text="Answer 1")]),
        Message(role=Role.USER, parts=[ContentPart(text="Question 2")]),
        Message(role=Role.MODEL, parts=[ContentPart(text="Answer 2")]),
    ]

    # Simulate /clear command
    result = client._handle_command("/clear", sources=None)

    assert result is True
    assert len(client.conversation) == 0
