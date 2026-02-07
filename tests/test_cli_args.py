"""Tests for CLI argument parsing."""

import pytest

from llm_cli.apps.cli_common import ClientConfig, create_standard_parser
from llm_cli.clients.base import BaseLlmClient


class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        pass

    def _send(self, _data):
        return "", {}


@pytest.fixture
def parser():
    config = ClientConfig(
        client_class=MockClient,
        description="Test CLI",
        supports_provider_selection=True,
    )
    return create_standard_parser(config)


def test_session_argument(parser):
    """Test that the --session argument is accepted."""
    args = parser.parse_args(["--session", "my_session.json"])
    assert args.session == "my_session.json"


def test_removed_tools_argument(parser):
    """Test that the -t/--tools argument is removed and raises an error."""
    with pytest.raises(SystemExit):
        parser.parse_args(["-t", "search"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--tools", "search"])


def test_removed_no_system_prompt_argument(parser):
    """Test that the --no-system-prompt argument is removed and raises an error."""
    with pytest.raises(SystemExit):
        parser.parse_args(["--no-system-prompt"])


def test_removed_debug_argument(parser):
    """Test that the -d/--debug argument is removed and raises an error."""
    with pytest.raises(SystemExit):
        parser.parse_args(["-d"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--debug"])
