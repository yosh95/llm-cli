from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.session import ChatSession
from llm_cli.clients.tool_executor import (
    execute_tool_call,
)
from llm_cli.modules.models import ContentPart, Message, Role


class MockLlmClient:
    """A minimal mock client for testing tool_executor integration."""

    def __init__(self):
        self.model = "test-model"
        self.conversation = [Message(role=Role.USER, parts=["Initial prompt"])]
        self.active_tools = ["test_tool"]
        self.tools_enabled = True

    def get_last_user_prompt(self):
        return "Initial prompt"


@pytest.fixture
def session():
    client = MockLlmClient()
    session = MagicMock(spec=ChatSession)
    session.client = client
    return session


@pytest.fixture
def tool_call_part():
    return ContentPart(
        function_call={
            "id": "call_123",
            "name": "test_tool",
            "args": {"arg1": "val1"},
        }
    )


def test_tool_executor_blocks_on_dual_llm_violation(session, tool_call_part):
    """Test that tool executor blocks execution when Dual LLM says it's unsafe."""
    mock_tool_func = MagicMock()

    # Configure CASS to require Dual LLM verification
    security_reqs = {
        "require_pqc_signature": True,
        "pqc_variant": "ML-DSA-87",
        "require_pqc_audit_encryption": True,
        "ast_strictness": "strict",
        "require_dual_llm_verification": True,
    }

    with (
        patch(
            "llm_cli.security.cass.cass_orchestrator.get_security_requirements",
            return_value=security_reqs,
        ),
        patch(
            "llm_cli.security.cass.cass_orchestrator.evaluate_risk",
            return_value=MagicMock(value="high"),
        ),
        patch(
            "llm_cli.security.dual_llm_verifier.verify_tool_call",
            return_value=(False, "Malicious activity detected."),
        ),
        patch("llm_cli.security.identity.IdentityManager._ensure_keys"),
        patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True),
    ):
        res_part, injected = execute_tool_call(session, tool_call_part)

        # It should return an error part and NOT execute the tool
        assert "Dual LLM Violation" in res_part.function_response["response"]["result"]
        assert (
            "Malicious activity detected."
            in res_part.function_response["response"]["result"]
        )
        mock_tool_func.assert_not_called()


def test_tool_executor_passes_on_dual_llm_success(session, tool_call_part):
    """Test that tool executor proceeds when Dual LLM says it's safe."""
    mock_tool_func = MagicMock(return_value="Tool output")

    security_reqs = {
        "require_dual_llm_verification": True,
        "require_pqc_signature": True,
        "pqc_variant": "ML-DSA-87",
        "require_pqc_audit_encryption": True,
        "ast_strictness": "strict",
    }

    with (
        patch(
            "llm_cli.security.cass.cass_orchestrator.get_security_requirements",
            return_value=security_reqs,
        ),
        patch(
            "llm_cli.security.cass.cass_orchestrator.evaluate_risk",
            return_value=MagicMock(value="high"),
        ),
        patch(
            "llm_cli.security.dual_llm_verifier.verify_tool_call",
            return_value=(True, "Matches intent."),
        ),
        patch("llm_cli.security.identity.IdentityManager._ensure_keys"),
        patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True),
        patch(
            "llm_cli.modules.tool_registry.registry.tools",
            {"test_tool": {"func": mock_tool_func, "skip_approval": True}},
        ),
        patch(
            "llm_cli.clients.tool_executor._verify_pqc_signature",
            side_effect=lambda data, _: data,
        ),
    ):
        res_part, injected = execute_tool_call(session, tool_call_part)

        assert res_part.function_response["response"]["result"] == "Tool output"
        mock_tool_func.assert_called_once()
