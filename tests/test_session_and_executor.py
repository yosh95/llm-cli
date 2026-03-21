from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.session import ChatSession
from llm_cli.clients.tool_executor import (
    PostProcessHandler,
    ToolExecutionContext,
    execute_tool_call,
)
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class MockClient(BaseLlmClient):
    def __init__(self, initial_model_alias="default", api_key="api_key"):
        super().__init__(
            initial_model_alias,
            ProviderSpec(api_key, "google", True),
            stdout=False,
        )

    def _load_model_aliases(self):
        self.available_models = {"default": "test-model"}

    def _send(self, _data):
        if not hasattr(self, "_send_count"):
            self._send_count = 0
        self._send_count += 1

        if self._send_count == 1:
            part = ContentPart(function_call={"id": "c1", "name": "t1", "args": {}})
            self.conversation.append(Message(role=Role.MODEL, parts=[part]))
            return (("", "Thinking..."), {"tokens": 5})
        else:
            self.conversation.append(
                Message(role=Role.MODEL, parts=[ContentPart(text="Final Answer")])
            )
            return (("Final Answer", ""), {"tokens": 10})


@pytest.fixture
def session():
    client = MockClient("default", "api_key")
    session = ChatSession(client)
    return session


@pytest.fixture
def tool_call_part():
    return ContentPart(
        function_call={
            "id": "call_123",
            "name": "test_tool",
            "args": {"arg1": "val1", "explanation": "I need to test this."},
        }
    )


def test_execute_tool_call_success(session, tool_call_part):
    """Test successful tool execution pipeline."""
    mock_tool_func = MagicMock(return_value="Success Result")

    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {
            "test_tool": {
                "func": mock_tool_func,
                "skip_approval": True,
                "interactive": False,
            }
        },
    ):
        with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True):
            res_part, injected = execute_tool_call(session, tool_call_part)

            assert res_part.function_response["response"]["result"] == "Success Result"
            assert injected is None
            mock_tool_func.assert_called_once()


def test_execute_tool_call_user_rejection(session, tool_call_part):
    """Test tool execution rejected by user."""
    mock_tool_func = MagicMock()

    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"test_tool": {"func": mock_tool_func, "skip_approval": False}},
    ):
        with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True):
            with patch.object(session, "_get_input", return_value="n"):
                res_part, injected = execute_tool_call(session, tool_call_part)

                assert (
                    "Error: Operation denied."
                    in res_part.function_response["response"]["result"]
                )
                assert injected is None
                mock_tool_func.assert_not_called()


def test_execute_tool_call_policy_violation(session, tool_call_part):
    """Test tool execution denied by policy engine."""
    with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=False):
        res_part, injected = execute_tool_call(session, tool_call_part)

        assert "Policy Violation" in res_part.function_response["response"]["result"]
        assert injected is None


def test_execute_tool_call_with_injected_data(session, tool_call_part):
    """Test tool that returns injected data for the next turn."""
    injected_ds = DataSource(content="Injected", content_type="text/plain")
    # Result without pqc_signature will be returned as is (the dict)
    mock_tool_func = MagicMock(
        return_value={"result": "OK", "__llm_cli_data__": injected_ds}
    )

    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"test_tool": {"func": mock_tool_func, "skip_approval": True}},
    ):
        with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True):
            res_part, injected = execute_tool_call(session, tool_call_part)

            assert res_part.function_response["response"]["result"] == {"result": "OK"}
            assert injected == injected_ds


@pytest.mark.asyncio
async def test_session_process_and_print(session):
    """Test the main ReAct loop in ChatSession."""
    data = [DataSource(content="User prompt", content_type="text/plain")]

    # 1. Model responds with tool call
    tool_call = {"id": "c1", "name": "t1", "args": {}}
    model_res_1 = (("", "Thinking..."), {"tokens": 5})

    # 2. Tool execution result
    tool_resp_part = ContentPart(
        function_response={"id": "c1", "name": "t1", "response": {"result": "Done"}}
    )

    # 3. Model final response
    model_res_2 = (("Final Answer", ""), {"tokens": 10})

    with patch.object(session.client, "_send", side_effect=[model_res_1, model_res_2]):
        # _has_pending_tool_calls is called in _run_single_turn AND _process_tool_loop
        with patch.object(
            session.client,
            "_has_pending_tool_calls",
            side_effect=[True, True, False, False],
        ):
            with patch(
                "llm_cli.clients.tool_executor.execute_tool_call",
                return_value=(tool_resp_part, None),
            ):
                # Mock last message check
                session.client.conversation = [
                    Message(role=Role.USER, parts=["User prompt"]),
                    Message(
                        role=Role.MODEL, parts=[ContentPart(function_call=tool_call)]
                    ),
                ]

                session.process_and_print(data)

                # Check that conversation has grown
                assert len(session.client.conversation) > 2


def test_code_safety_handler_blocks_unsafe_code(session):
    """Test that CodeSafetyHandler blocks dangerous Python code."""
    from llm_cli.clients.tool_executor import CodeSafetyHandler

    part = ContentPart(
        function_call={
            "name": "execute_python",
            "args": {"code": "import os; os.system('rm -rf /')"},
        }
    )
    ctx = ToolExecutionContext(session, part)

    handler = CodeSafetyHandler()
    with patch(
        "llm_cli.clients.tool_executor.analyze_python_safety",
        return_value=(False, ["Dangerous import"]),
    ):
        handler.process(ctx)
        assert ctx.aborted is True
        assert "Blocked" in ctx.error_message


def test_pqc_verification_post_process(session):
    """Test that PostProcessHandler verifies PQC signatures."""

    # Result with valid-looking signature structure
    result_data = {
        "result": "Secret Data",
        "pqc_signature": "sig_b64",
        "verification_id": "v123",
        "algorithm": "ML-DSA-44",
    }

    part = ContentPart(function_call={"name": "read_file", "args": {}})
    ctx = ToolExecutionContext(session, part)
    ctx.result_data = result_data

    handler = PostProcessHandler()
    with patch(
        "llm_cli.security.identity.IdentityManager._get_pqc_public_key_content",
        return_value=b"pubkey",
    ):
        with patch("llm_cli.security.pqc.PQCProvider.verify", return_value=True):
            with patch("llm_cli.clients.tool_executor.report_success") as mock_success:
                handler.process(ctx)
                assert ctx.result_data == "Secret Data"
                mock_success.assert_called_once()
