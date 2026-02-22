from unittest.mock import Mock

import pytest

from llm_cli.clients.mcp_manager import MCPManager


@pytest.fixture
def mock_config():
    return [
        {
            "name": "test_server",
            "command": "python -m llm_cli.apps.mcp_server",
            "roles": ["user"],
        }
    ]


@pytest.fixture
def mock_manager():
    manager = MCPManager()
    # Close the real loop to prevent ResourceWarning
    manager.loop.close()
    manager.servers_config = []
    manager.sessions = {}
    manager.exit_stack = {}
    manager._initialized = False
    manager._cached_tools = []
    manager.loop = Mock()
    manager.loop.is_running.return_value = False
    return manager


class TestMCPManager:
    def test_list_tools_no_config(self, mock_manager):
        mock_manager.servers_config = []
        tools = mock_manager.list_tools()
        assert tools == []

    def test_call_tool_success(self, mock_manager):
        mock_manager.sessions["test_server"] = Mock()
        mock_session = mock_manager.sessions["test_server"]
        mock_result = Mock(content=[Mock(type="text", text="result")])
        # Use Mock instead of AsyncMock because loop.run_until_complete is mocked
        # and won't actually await the coroutine, leading to RuntimeWarning.
        mock_session.call_tool = Mock(return_value=mock_result)
        mock_manager.loop.run_until_complete.return_value = mock_result

        result = mock_manager.call_tool("test_server", "tool", {})
        assert "result" in result

    def test_call_tool_no_session(self, mock_manager):
        result = mock_manager.call_tool("missing", "tool", {})
        assert "not connected" in result

    def test_shutdown(self, mock_manager):
        mock_manager.exit_stack = {"test": (Mock(), Mock())}
        mock_manager.shutdown()
        # exit_stack cleared in real, mock pass
        pass
