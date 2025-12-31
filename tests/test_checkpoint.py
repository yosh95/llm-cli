import pytest
from unittest.mock import MagicMock, patch
from llm_cli.clients.session import ChatSession
from llm_cli.apps.gemini import GeminiClient


@pytest.fixture
def mock_gemini_client(mock_config):
    client = GeminiClient(stdout=True)
    client.conversation = [
        {"role": "user", "parts": [{"text": "First msg"}]},
        {"role": "model", "parts": [{"text": "Second msg"}]}
    ]
    return client


def test_checkpoint_tool_approval(mock_gemini_client):
    """Test that approving a checkpoint clears history and injects summary."""
    session = ChatSession(mock_gemini_client)

    # Mock prompt to return 'y' for the checkpoint approval
    with patch("llm_cli.clients.session.prompt", return_value="y"):
        call = {
            "name": "checkpoint_conversation",
            "args": {"summary": "This is a test summary of progress."}
        }
        result = session._execute_tool_call(call)

        # Verify result and state
        assert result == "CHECKPOINT_SUCCESS"
        assert len(mock_gemini_client.conversation) == 1
        text = mock_gemini_client.conversation[0]["parts"][0]["text"]
        assert "SYSTEM: History cleared" in text
        assert "This is a test summary" in text


def test_checkpoint_tool_denial(mock_gemini_client):
    """Test that denying a checkpoint preserves history."""
    session = ChatSession(mock_gemini_client)
    initial_history_len = len(mock_gemini_client.conversation)

    # Mock prompt to return 'n' for the checkpoint approval
    with patch("llm_cli.clients.session.prompt", return_value="n"):
        call = {
            "name": "checkpoint_conversation",
            "args": {"summary": "Summary should be ignored."}
        }
        result = session._execute_tool_call(call)

        # Verify result and state
        assert result is None
        assert len(mock_gemini_client.conversation) == initial_history_len
        text = mock_gemini_client.conversation[0]["parts"][0]["text"]
        assert "First msg" in text


def test_checkpoint_tool_loop_interruption(mock_gemini_client):
    """
    Test that session.process_and_print stops the tool loop
    after a successful checkpoint.
    """
    session = ChatSession(mock_gemini_client)

    # Simulate a tool call message from the model
    mock_gemini_client.conversation.append({
        "role": "model",
        "parts": [{
            "functionCall": {
                "name": "checkpoint_conversation",
                "args": {"summary": "Consolidated state."}
            }
        }]
    })

    # Mock _send to prevent actual API calls
    mock_gemini_client._send = MagicMock(return_value=("Done", {}))

    # Mock prompt to approve
    with patch("llm_cli.clients.session.prompt", return_value="y"):
        # We need to mock CustomMarkdown or just ignore console print
        with patch("llm_cli.clients.session.console.print"):
            session.process_and_print([])

    # Check that history was indeed replaced
    assert len(mock_gemini_client.conversation) == 1
    text = mock_gemini_client.conversation[0]["parts"][0]["text"]
    assert "Consolidated state" in text
    # Ensure _send was NOT called after the checkpoint
    assert mock_gemini_client._send.call_count == 1
