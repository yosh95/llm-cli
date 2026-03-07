import os
import runpy
from unittest.mock import Mock, patch

import pytest

import llm_cli.apps.mcp_server as mcp_server
from llm_cli.security.identity import IdentityManager


@pytest.mark.asyncio
async def test_config_load_exception(caplog):
    # Test the exception block in config loading
    # Use runpy to execute the module and capture logs
    with patch(
        "llm_cli.apps.configure.load_config", side_effect=Exception("Config error")
    ):
        with caplog.at_level("WARNING"):
            # Use a different run_name to avoid side effects
            runpy.run_module("llm_cli.apps.mcp_server", run_name="test_config_err")
            assert "Failed to load user config: Config error" in caplog.text


@pytest.mark.asyncio
async def test_invalid_auth_token(monkeypatch):
    # Line 68-69: Invalid Auth Token provided.
    mock_policy_engine = Mock()
    monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)

    # Mock IdentityManager.verify_token to return None (invalid token)
    monkeypatch.setattr(IdentityManager, "verify_token", Mock(return_value=None))
    monkeypatch.setattr(os, "environ", {"MCP_AUTH_TOKEN": "invalid_token"}.copy())

    def test_func():
        return "should not reach here"

    wrapped = mcp_server.secure_tool_wrapper(test_func, "test_tool")
    result = await wrapped()
    assert "⛔ Authentication Failed: Invalid Token." in result


@pytest.mark.asyncio
async def test_tool_execution_exception(monkeypatch):
    # Lines 121-130: Exception during tool execution
    mock_policy_engine = Mock()
    mock_policy_engine.evaluate.return_value = True
    monkeypatch.setattr("llm_cli.apps.mcp_server.policy_engine", mock_policy_engine)

    mock_log_audit = Mock()
    monkeypatch.setattr("llm_cli.apps.mcp_server.log_audit", mock_log_audit)

    monkeypatch.setattr(
        "llm_cli.mcp_lib.get_current_trace_id", Mock(return_value="err-trace")
    )
    monkeypatch.setattr(os, "environ", {}.copy())

    async def failing_tool(*args, **kwargs):
        raise ValueError("Tool failure")

    wrapped = mcp_server.secure_tool_wrapper(failing_tool, "test_tool")

    with pytest.raises(ValueError, match="Tool failure"):
        await wrapped()

    # Verify audit log was called for failure
    mock_log_audit.assert_called_once()
    args, kwargs = mock_log_audit.call_args
    assert kwargs["error"] == "Tool failure"
    assert kwargs["_output"] is None


def test_main_execution_call():
    # Line 165: Testing if __name__ == "__main__": main()
    # Patch at the source because the module re-imports these
    with (
        patch("llm_cli.security.integrity.verify_installation"),
        patch("llm_cli.mcp_lib.FastMCP") as mock_mcp_cls,
    ):
        mock_mcp = Mock()
        mock_mcp_cls.return_value = mock_mcp
        mock_mcp.run = Mock()

        runpy.run_module("llm_cli.apps.mcp_server", run_name="__main__")

        # Verify that main() was called and it called mcp.run()
        mock_mcp.run.assert_called_once()
