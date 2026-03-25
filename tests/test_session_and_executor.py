from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.session import ChatSession
from llm_cli.clients.tool_executor import (
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

    def utility_send(self, _system_prompt, _user_prompt, _json_mode=False):
        return '{"safe": true, "reason": "mocked"}'


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
    """Test successful tool execution flow."""
    mock_tool_func = MagicMock(return_value="Success Result")

    def mock_verify(data, risk_level, **kwargs):
        if isinstance(data, dict) and "pqc_signature" in data:
            return data["result"]
        return data

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
            with patch("llm_cli.security.identity.IdentityManager._ensure_keys"):
                # Patch _verify_pqc_signature to avoid failure due to missing signature in mock tools
                with patch(
                    "llm_cli.clients.tool_executor._verify_pqc_signature",
                    side_effect=mock_verify,
                ):
                    res_part, injected = execute_tool_call(session, tool_call_part)

                    assert (
                        res_part.function_response["response"]["result"]
                        == "Success Result"
                    )
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
    mock_tool_func = MagicMock(
        return_value={"result": "OK", "__llm_cli_data__": injected_ds}
    )

    def mock_verify(data, risk_level, **kwargs):
        if isinstance(data, dict) and "pqc_signature" in data:
            return data["result"]
        return data

    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"test_tool": {"func": mock_tool_func, "skip_approval": True}},
    ):
        with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True):
            with patch("llm_cli.security.identity.IdentityManager._ensure_keys"):
                # Patch _verify_pqc_signature to avoid failure due to missing signature in mock tools
                with patch(
                    "llm_cli.clients.tool_executor._verify_pqc_signature",
                    side_effect=mock_verify,
                ):
                    res_part, injected = execute_tool_call(session, tool_call_part)

                    assert (
                        res_part.function_response["response"]["result"]
                        == "{'result': 'OK'}"
                    )
                    assert injected == injected_ds


def test_code_safety_check_blocks_unsafe_code(session):
    """Test that static analysis blocks dangerous Python code."""
    from llm_cli.clients.tool_executor import _run_code_safety_check

    part = ContentPart(
        function_call={
            "name": "execute_python",
            "args": {"code": "import os; os.system('rm -rf /')"},
        }
    )
    ctx = ToolExecutionContext(session, part)

    with patch(
        "llm_cli.clients.tool_executor.analyze_python_safety",
        return_value=(False, ["Dangerous import"]),
    ):
        # By default it should fail if analyze_python_safety returns False
        result = _run_code_safety_check(ctx)
        assert result is False
        assert "blocked" in ctx.error_message.lower()


def test_pqc_verification_post_process(session):
    """Test that _post_process_result verifies PQC signatures."""
    from llm_cli.clients.tool_executor import _post_process_result

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

    with patch(
        "llm_cli.security.identity.IdentityManager._get_pqc_public_key_content",
        return_value=b"pubkey",
    ):
        with patch("llm_cli.security.pqc.PQCProvider.verify", return_value=True):
            with patch("llm_cli.clients.tool_executor.report_success") as mock_success:
                success = _post_process_result(ctx)
                assert success is True
                assert ctx.result_data == "Secret Data"
                mock_success.assert_called_once()
