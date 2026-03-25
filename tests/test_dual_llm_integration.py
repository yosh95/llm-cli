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


def test_tool_executor_soft_fail_on_api_key_missing(session, tool_call_part):
    """
    When the Dual LLM secondary provider has no API key set, verify_tool_call
    returns (False, "API key missing").  This must NOT be treated as a hard
    security block — instead the executor must fall back to the human-in-the-loop
    prompt.  Specifically:
      - report_warning is called (not report_error)
      - _get_input is called asking the user to approve manually
      - if user approves (y), execution proceeds (returns True from the verifier phase)
    """
    security_reqs = {
        "require_dual_llm_verification": True,
        "require_pqc_signature": True,
        "pqc_variant": "ML-DSA-87",
        "require_pqc_audit_encryption": True,
        "ast_strictness": "strict",
    }
    # Simulate "user presses y" at the manual-approval prompt
    session._get_input = MagicMock(return_value="y")

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
            return_value=(False, "API key missing"),
        ),
        patch("llm_cli.security.identity.IdentityManager._ensure_keys"),
        patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True),
        patch("llm_cli.ui.report_warning") as mock_warn,
    ):
        # _run_dual_llm_verification should return True (user approved manually)
        from llm_cli.clients.tool_executor import (
            ToolExecutionContext,
            _run_dual_llm_verification,
        )
        from llm_cli.modules.models import ContentPart

        part = ContentPart(function_call={"id": "c1", "name": "test_tool", "args": {}})
        ctx = ToolExecutionContext(session=session, part=part)
        ctx.security_requirements = security_reqs  # type: ignore[assignment]

        result = _run_dual_llm_verification(ctx)

        assert result is True, "User-approved manual fallback must return True"
        mock_warn.assert_called_once()
        warn_msg = mock_warn.call_args[0][0]
        assert "API key missing" in warn_msg
        assert "Falling back to manual approval" in warn_msg


def test_tool_executor_soft_fail_on_api_key_missing_user_rejects(
    session, tool_call_part
):
    """
    Same scenario as above but user answers 'n'.  The executor must block and
    set an error message, NOT silently allow execution.
    """
    security_reqs = {
        "require_dual_llm_verification": True,
        "require_pqc_signature": True,
        "pqc_variant": "ML-DSA-87",
        "require_pqc_audit_encryption": True,
        "ast_strictness": "strict",
    }
    # Simulate "user presses n"
    session._get_input = MagicMock(return_value="n")

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
            return_value=(False, "API key missing"),
        ),
        patch("llm_cli.security.identity.IdentityManager._ensure_keys"),
        patch("llm_cli.security.policy.policy_engine.evaluate", return_value=True),
        patch("llm_cli.ui.report_warning"),
    ):
        from llm_cli.clients.tool_executor import (
            ToolExecutionContext,
            _run_dual_llm_verification,
        )
        from llm_cli.modules.models import ContentPart

        part = ContentPart(function_call={"id": "c1", "name": "test_tool", "args": {}})
        ctx = ToolExecutionContext(session=session, part=part)
        ctx.security_requirements = security_reqs  # type: ignore[assignment]

        result = _run_dual_llm_verification(ctx)

        assert result is False, "User rejection must block the tool call"
        assert ctx.error_message is not None
        assert "Dual LLM Unavailable" in ctx.error_message


@pytest.mark.parametrize(
    "reason",
    [
        "API key missing",
        "Provider not found",
        "Initialization error: connection refused",
        "Verification process failed: timeout",
    ],
)
def test_soft_fail_reasons_all_trigger_human_fallback(session, tool_call_part, reason):
    """
    All four 'soft failure' reasons must trigger the human fallback path,
    NOT a hard block with a 'Dual LLM Violation' error message.
    """
    security_reqs = {
        "require_dual_llm_verification": True,
        "require_pqc_signature": False,
        "pqc_variant": "ML-DSA-44",
        "require_pqc_audit_encryption": False,
        "ast_strictness": "basic",
    }
    # User approves
    session._get_input = MagicMock(return_value="y")

    with (
        patch(
            "llm_cli.security.dual_llm_verifier.verify_tool_call",
            return_value=(False, reason),
        ),
        patch("llm_cli.ui.report_warning"),
    ):
        from llm_cli.clients.tool_executor import (
            ToolExecutionContext,
            _run_dual_llm_verification,
        )
        from llm_cli.modules.models import ContentPart

        part = ContentPart(function_call={"id": "c1", "name": "test_tool", "args": {}})
        ctx = ToolExecutionContext.__new__(ToolExecutionContext)
        ctx.session = session
        ctx.part = part
        ctx.name = "test_tool"
        ctx.args = {}
        ctx.error_message = None
        ctx.security_requirements = security_reqs  # type: ignore[assignment]

        result = _run_dual_llm_verification(ctx)

        assert result is True  # Human approved
        assert ctx.error_message is None  # No hard error set


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
            side_effect=lambda data, *_, **__: (
                data.get("result") if isinstance(data, dict) else data
            ),
        ),
    ):
        res_part, injected = execute_tool_call(session, tool_call_part)

        assert res_part.function_response["response"]["result"] == "Tool output"
        mock_tool_func.assert_called_once()
