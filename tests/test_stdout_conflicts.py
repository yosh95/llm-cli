"""Tests for conflict resolution and tool disabling when using --stdout."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient


class RealMockClient(BaseLlmClient):
    def __init__(self, **kwargs):
        pass  # Override init to do nothing

    def _load_model_aliases(self):
        pass

    def _send(self, _data):
        return "", {}

    def process_sources(self, sources):
        pass

    def talk(self):
        pass

    def load_session(self, path):
        pass


def test_stdout_mcp_conflict():
    config = ClientConfig(client_class=RealMockClient, description="Test")
    with patch("sys.argv", ["llm-cli", "--stdout", "--mcp"]):
        with patch("sys.stdin", new=StringIO("")):
            with patch("llm_cli.apps.cli_common.sys.stdin.isatty", return_value=True):
                with pytest.raises(SystemExit) as excinfo:
                    run_client_cli(config)
                assert excinfo.value.code == 1


def test_stdout_mcp_server_conflict():
    config = ClientConfig(client_class=RealMockClient, description="Test")
    with patch("sys.argv", ["llm-cli", "--stdout", "--mcp-server"]):
        with pytest.raises(SystemExit) as excinfo:
            run_client_cli(config)
        assert excinfo.value.code == 1


def test_stdout_disable_mcp():
    mock_cls = MagicMock()
    config = ClientConfig(client_class=mock_cls, description="Test")

    with patch("llm_cli.apps.cli_common.sys.stdin.isatty", return_value=True):
        with patch("sys.argv", ["llm-cli", "--stdout", "prompt"]):
            run_client_cli(config)

    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["stdout"] is True
    assert call_kwargs["enable_mcp"] is False
    assert call_kwargs["initial_tools"] == []


def test_stdout_requires_input():
    mock_cls = MagicMock()
    config = ClientConfig(client_class=mock_cls, description="Test")

    # Mock stdin as tty (no input)
    with patch("llm_cli.apps.cli_common.sys.stdin.isatty", return_value=True):
        # Provide no sources
        with patch("sys.argv", ["llm-cli", "--stdout"]):
            with pytest.raises(SystemExit) as excinfo:
                run_client_cli(config)
            assert excinfo.value.code == 1
