import base64
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.session import ChatSession
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import tool


# Define a mock tool for testing
@tool("exec_mock_tool", description="A test tool")
def exec_mock_tool(explanation: str, input_str: str):
    # The security policy requires ALL tool responses to be signed.
    # We must return a dict with pqc_signature.
    res_text = f"Processed: {input_str}"
    return {
        "result": res_text,
        "pqc_signature": base64.urlsafe_b64encode(b"fake_sig").decode(),
        "verification_id": "call_123",
        "algorithm": "ML-DSA-65",
    }


class MockClient(BaseLlmClient):
    """Minimal client for E2E testing."""

    def __init__(self):
        spec = ProviderSpec(api_key_name="MOCK_KEY", config_section="google", pdf_as_base64=True)
        super().__init__("default", spec)
        self.api_key = "dummy"
        self._send_mock = MagicMock()

    def _send(self, data: list[DataSource]):
        return self._send_mock(data)

    def utility_send(self, _system_prompt, _user_prompt, _json_mode=False):
        return '{"safe": true, "reason": "mocked"}'


@pytest.fixture
def mock_session(tmp_path):
    # Setup paths and environment
    with patch(
        "llm_cli.clients.config.config_manager.load_config",
        return_value={"security": {}},
    ):
        client = MockClient()
        session = ChatSession(client)
        # Mock UI confirmation to always auto-approve tools
        session.ui.confirm = MagicMock(return_value=True)
        session.ui.get_input = MagicMock(return_value="y")
        yield session


def test_react_tool_loop(mock_session):
    """
    Verifies that ChatSession correctly orchestrates a full tool-calling loop.
    """
    client = mock_session.client

    # 1. First turn: LLM decides to call a tool
    def side_effect_turn1(data):
        tool_call = {
            "id": "call_123",
            "name": "exec_mock_tool",
            "args": {"explanation": "Testing", "input_str": "hello"},
        }
        msg = Message(
            role=Role.MODEL,
            parts=[
                ContentPart(text="I will call the test tool.", thought_signature="thought_1"),
                ContentPart(function_call=tool_call, thought_signature="thought_1"),
            ],
        )
        client.conversation.append(msg)
        return (
            ("I will call the test tool.", "I need to process some data."),
            {"prompt_tokens": 10, "candidates_tokens": 20},
        )

    # 2. Second turn: LLM provides final answer after seeing tool result
    def side_effect_turn2(data):
        msg = Message(
            role=Role.MODEL,
            parts=[ContentPart(text="The tool returned the processed result.")],
        )
        client.conversation.append(msg)
        return (
            ("The tool returned the processed result.", None),
            {"prompt_tokens": 50, "candidates_tokens": 10},
        )

    # Sequence of side effects to execute
    effects = [side_effect_turn1, side_effect_turn2]

    def orchestrator(data):
        if not effects:
            return (None, None), None
        func = effects.pop(0)
        return func(data)

    client._send_mock.side_effect = orchestrator

    # Run the loop
    user_data = [DataSource(content="Please run the test tool.", content_type="text/plain")]

    # Manually add USER message to simulate ChatSession.run() behavior before process_and_print
    client.conversation.append(
        Message(role=Role.USER, parts=[ContentPart(text="Please run the test tool.")])
    )

    # Mock signature verification to always pass (since we use fake_sig)
    with (
        patch.object(mock_session, "_sign_response"),
        patch("llm_cli.security.pqc.PQCProvider.verify", return_value=True),
    ):
        mock_session.process_and_print(user_data)

    # Assertions
    assert client._send_mock.call_count == 2

    history = client.conversation
    # Chain: USER -> MODEL(call) -> TOOL(res) -> MODEL(final)
    assert len(history) == 4
    assert history[0].role == Role.USER
    assert history[1].role == Role.MODEL
    assert history[1].parts[1].function_call["name"] == "exec_mock_tool"
    assert history[2].role == Role.TOOL
    assert "Processed: hello" in str(history[2].parts[0])
    assert history[3].role == Role.MODEL
    assert "The tool returned" in history[3].parts[0].text
