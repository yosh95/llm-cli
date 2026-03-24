import os
from unittest.mock import Mock, patch

import pytest

from llm_cli.apps.mcp_server import (
    create_mcp_server,
    main,
    secure_tool_wrapper,
)
from llm_cli.modules.tool_registry import registry
from llm_cli.security.identity import IdentityManager


@pytest.fixture
def mock_policy_engine():
    engine = Mock()
    engine.evaluate.return_value = True
    return engine


@pytest.fixture
def mock_registry():
    original_tools = registry.tools.copy()
    registry.tools = {
        "test_tool": {
            "func": Mock(name="test_func"),
            "name": "test_tool",
            "description": "Mock tool for testing",
            "parameters": {},
        }
    }
    yield registry
    registry.tools = original_tools


class TestSecureToolWrapper:
    @pytest.mark.asyncio
    async def test_secure_wrapper_async_func_authenticated(
        self, mock_policy_engine, monkeypatch
    ):
        monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)
        monkeypatch.setattr("llm_cli.security.audit.log_audit", Mock())
        monkeypatch.setattr(
            "llm_cli.mcp_lib.get_current_trace_id", Mock(return_value="trace123")
        )

        # Mock IdentityManager
        valid_payload = {"roles": ["user"], "sub": "user123"}
        monkeypatch.setattr(
            IdentityManager, "verify_token", Mock(return_value=valid_payload)
        )
        monkeypatch.setattr(os, "environ", {"MCP_AUTH_TOKEN": "valid_token"}.copy())

        async def test_async_func(*args, **kwargs):
            return "async result"

        wrapped = secure_tool_wrapper(test_async_func, "test_tool")
        result = await wrapped(arg=1)
        assert isinstance(result, dict)
        assert result["result"] == "async result"
        assert "pqc_signature" in result
        mock_policy_engine.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_secure_wrapper_sync_func_no_token_guest_policy(
        self, monkeypatch, mock_policy_engine
    ):
        monkeypatch.setattr("llm_cli.apps.mcp_server.MISSING_TOKEN_POLICY", "guest")
        monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)
        monkeypatch.setattr("llm_cli.security.audit.log_audit", Mock())
        monkeypatch.setattr(
            "llm_cli.mcp_lib.get_current_trace_id", Mock(return_value="trace123")
        )

        def test_sync_func(*args, **kwargs):
            return "sync result"

        monkeypatch.setattr(IdentityManager, "verify_token", Mock(return_value=None))
        monkeypatch.setattr(os, "environ", {}.copy())

        wrapped = secure_tool_wrapper(test_sync_func, "test_tool")
        result = await wrapped(arg=1)
        assert isinstance(result, dict)
        assert result["result"] == "sync result"
        assert "pqc_signature" in result
        mock_policy_engine.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_secure_wrapper_policy_violation(
        self, monkeypatch, mock_policy_engine
    ):
        monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)
        mock_policy_engine.evaluate.return_value = False

        # Mock valid token to pass auth, fail on policy
        valid_payload = {"roles": ["user"], "sub": "user123"}
        monkeypatch.setattr(
            IdentityManager, "verify_token", Mock(return_value=valid_payload)
        )
        monkeypatch.setattr("llm_cli.security.audit.log_audit", Mock())
        monkeypatch.setattr(
            "llm_cli.mcp_lib.get_current_trace_id", Mock(return_value="trace123")
        )
        monkeypatch.setattr(os, "environ", {"MCP_AUTH_TOKEN": "valid_token"}.copy())

        def test_func(*args, **kwargs):
            return "result"

        wrapped = secure_tool_wrapper(test_func, "test_tool")
        result = await wrapped()
        assert "Security Policy Violation" in str(result)
        mock_policy_engine.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_secure_wrapper_deny_missing_token(self, monkeypatch):
        monkeypatch.setattr("llm_cli.apps.mcp_server.MISSING_TOKEN_POLICY", "deny")
        monkeypatch.setattr(os, "environ", {}.copy())

        def test_func():
            pass

        wrapped = secure_tool_wrapper(test_func, "test_tool")
        result = await wrapped()
        assert "Access Denied: Authentication required." in str(result)

    @pytest.mark.asyncio
    async def test_secure_wrapper_logs_model(self, monkeypatch, mock_policy_engine):
        monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)
        mock_log_audit = Mock()
        monkeypatch.setattr("llm_cli.apps.mcp_server.log_audit", mock_log_audit)
        monkeypatch.setattr(
            "llm_cli.mcp_lib.get_current_trace_id", Mock(return_value="trace123")
        )
        monkeypatch.setattr(os, "environ", {}.copy())

        def test_func(**kwargs):
            return "ok"

        wrapped = secure_tool_wrapper(test_func, "test_tool")
        await wrapped(__audit_model__="test-model")

        # Verify log_audit was called with context containing model
        args, kwargs = mock_log_audit.call_args
        assert kwargs["context"]["model"] == "test-model"


class TestCreateMcpServer:
    @pytest.mark.usefixtures("mock_registry")
    @patch("llm_cli.apps.mcp_server.verify_installation")
    def test_create_mcp_server(self, mock_verify, monkeypatch):
        mock_fastmcp_cls = Mock(return_value=Mock())
        monkeypatch.setattr("llm_cli.apps.mcp_server.FastMCP", mock_fastmcp_cls)
        mock_logger = Mock()
        monkeypatch.setattr("llm_cli.apps.mcp_server.logger", mock_logger)

        server = create_mcp_server()
        mock_verify.assert_called_once()
        assert mock_fastmcp_cls.called
        mock_fastmcp_cls.assert_called_with("llm-cli-remote")
        assert mock_logger.info.called
        assert len(server.tool.mock_calls) == 2


class TestMain:
    @pytest.mark.usefixtures("mock_registry")
    def test_main(self, monkeypatch):
        monkeypatch.setattr("llm_cli.apps.mcp_server.create_mcp_server", Mock())
        mock_mcp = Mock()
        monkeypatch.setattr(
            "llm_cli.apps.mcp_server.create_mcp_server", lambda: mock_mcp
        )
        monkeypatch.setattr(mock_mcp, "run", Mock())
        monkeypatch.setattr("llm_cli.apps.mcp_server.logger", Mock())

        main()
        mock_mcp.run.assert_called_once()


# Run pytest with coverage to verify improvement
