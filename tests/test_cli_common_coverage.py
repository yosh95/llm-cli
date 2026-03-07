from unittest.mock import Mock, patch

import pytest

from llm_cli.apps.cli_common import ClientConfig, run_client_cli
from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.exceptions import ProviderSwitchRequest


class MockClient(BaseLlmClient):
    def __init__(self, **kwargs):
        # BaseLlmClient.__init__ requires some arguments
        kwargs.setdefault("initial_model_alias", "default")
        kwargs.setdefault("api_key_name", "api_key")
        kwargs.setdefault("config_section", "mock")
        kwargs.setdefault("pdf_as_base64", False)

        # We need to make sure BaseLlmClient doesn't fail during init
        with (
            patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
            patch(
                "llm_cli.clients.config.get_model_aliases",
                return_value={"default": "gpt-4"},
            ),
        ):
            super().__init__(**kwargs)

        # We don't want the real methods to run in these tests
        self.load_session = Mock()
        self.process_sources = Mock()
        self.talk = Mock()

    def _send(self, _data):
        return (("response", None), {"tokens": 10})


def test_run_client_cli_extra_args():
    config = ClientConfig(
        client_class=MockClient,
        description="Test",
        extra_args=[("--extra", {"action": "store_true"})],
    )
    from llm_cli.apps.cli_common import create_standard_parser

    parser = create_standard_parser(config)
    args = parser.parse_args(["--extra"])
    assert args.extra is True


def test_run_client_cli_stdout_mcp_server_conflict(capsys):
    config = ClientConfig(client_class=MockClient, description="Test")
    with patch("sys.argv", ["script", "--stdout", "--mcp-server"]):
        with pytest.raises(SystemExit) as excinfo:
            run_client_cli(config)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "--stdout and --mcp-server cannot be used together" in captured.out


def test_run_client_cli_mcp_server_failure(capsys):
    config = ClientConfig(client_class=MockClient, description="Test")
    with patch("sys.argv", ["script", "--mcp-server"]):
        with patch("llm_cli.apps.mcp_server.main", side_effect=Exception("Boot error")):
            with pytest.raises(SystemExit) as excinfo:
                run_client_cli(config)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to start MCP server: Boot error" in captured.out


def test_run_client_cli_load_session():
    config = ClientConfig(client_class=MockClient, description="Test")
    mock_instance = MockClient()
    with (
        patch("sys.argv", ["script", "--session", "test.json"]),
        patch("sys.stdin.isatty", return_value=True),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(config, "client_class", return_value=mock_instance),
    ):
        run_client_cli(config)
        mock_instance.load_session.assert_called_once_with("test.json")


def test_run_client_cli_stdin_not_tty_no_sources():
    config = ClientConfig(client_class=MockClient, description="Test")
    mock_instance = MockClient()
    with (
        patch("sys.argv", ["script"]),
        patch("sys.stdin.isatty", return_value=False),
        patch("sys.stdin.read", return_value=""),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(config, "client_class", return_value=mock_instance),
    ):
        run_client_cli(config)
        mock_instance.talk.assert_called_once()


def test_run_client_cli_stdout_no_input_error(capsys):
    config = ClientConfig(client_class=MockClient, description="Test")
    with (
        patch("sys.argv", ["script", "--stdout"]),
        patch("sys.stdin.isatty", return_value=True),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
    ):
        with pytest.raises(SystemExit) as excinfo:
            run_client_cli(config)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "--stdout requires input" in captured.out


def test_run_client_cli_provider_switch_request(capsys):
    config = ClientConfig(client_class=MockClient, description="Test")
    mock_instance = MockClient()
    mock_instance.talk.side_effect = ProviderSwitchRequest("openai")
    with (
        patch("sys.argv", ["script"]),
        patch("sys.stdin.isatty", return_value=True),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(config, "client_class", return_value=mock_instance),
    ):
        with pytest.raises(SystemExit) as excinfo:
            run_client_cli(config)
        assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Switching to provider 'openai' is not supported here" in captured.out


def test_run_client_cli_stdout_mcp_conflict(capsys):
    # Lines 78-79: Error when --stdout and --mcp are used together
    config = ClientConfig(client_class=MockClient, description="Test")
    with patch("sys.argv", ["script", "--stdout", "--mcp"]):
        with pytest.raises(SystemExit) as excinfo:
            run_client_cli(config)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "--stdout and --mcp cannot be used together" in captured.out


def test_run_client_cli_mcp_server_success():
    # Line 97: sys.exit(0) after successful MCP server run
    config = ClientConfig(client_class=MockClient, description="Test")
    with patch("sys.argv", ["script", "--mcp-server"]):
        with patch("llm_cli.apps.mcp_server.main", return_value=None):
            with pytest.raises(SystemExit) as excinfo:
                run_client_cli(config)
    assert excinfo.value.code == 0


def test_run_client_cli_stdin_not_tty_with_sources():
    # Line 134: client.process_sources(all_sources)
    config = ClientConfig(client_class=MockClient, description="Test")
    mock_instance = MockClient()
    with (
        patch("sys.argv", ["script", "file.txt"]),
        patch("sys.stdin.isatty", return_value=False),
        patch("sys.stdin.read", return_value="stdin content"),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(config, "client_class", return_value=mock_instance),
    ):
        run_client_cli(config)
        mock_instance.process_sources.assert_called_once_with(
            ["stdin content", "file.txt"]
        )


def test_run_client_cli_tty_with_sources():
    # Line 138: client.process_sources(args.sources)
    config = ClientConfig(client_class=MockClient, description="Test")
    mock_instance = MockClient()
    with (
        patch("sys.argv", ["script", "arg1", "arg2"]),
        patch("sys.stdin.isatty", return_value=True),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(config, "client_class", return_value=mock_instance),
    ):
        run_client_cli(config)
        mock_instance.process_sources.assert_called_once_with(["arg1", "arg2"])


def test_run_client_cli_with_provider_selection():
    # Line 122: client_kwargs["initial_provider"] = args.provider
    config = ClientConfig(
        client_class=MockClient, description="Test", supports_provider_selection=True
    )
    mock_instance = MockClient()
    with (
        patch("sys.argv", ["script", "-p", "openai"]),
        patch("sys.stdin.isatty", return_value=True),
        patch("llm_cli.clients.config.get_setting", return_value="fake-key"),
        patch(
            "llm_cli.clients.config.get_model_aliases", return_value={"default": "m"}
        ),
        patch.object(
            config, "client_class", side_effect=lambda **_: mock_instance
        ) as mock_cls,
    ):
        run_client_cli(config)
        # Verify initial_provider was passed to constructor
        args, kwargs = mock_cls.call_args
        assert kwargs["initial_provider"] == "openai"


def test_run_client_cli_parser_with_choices():
    # Line 39: parser.add_argument("-p", choices=config.provider_choices ...)
    config = ClientConfig(
        client_class=MockClient,
        description="Test",
        supports_provider_selection=True,
        provider_choices=["choice1", "choice2"],
    )
    from llm_cli.apps.cli_common import create_standard_parser

    parser = create_standard_parser(config)
    # Check if choices are correct
    for action in parser._actions:
        if action.dest == "provider":
            assert action.choices == ["choice1", "choice2"]
