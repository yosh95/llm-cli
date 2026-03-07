import sys
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.unified import UnifiedClient, main


def test_unified_help(capsys):
    with patch.object(sys, "argv", ["llm", "--help"]):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0
    captured = capsys.readouterr()
    assert "Unified LLM CLI" in captured.out


@patch("llm_cli.apps.unified.UnifiedClient")
def test_unified_interactive_call(mock_client_class, capsys):
    mock_client = mock_client_class.return_value
    with patch.object(sys, "argv", ["llm"]):
        with patch("sys.stdin.isatty", return_value=True):
            main()
    mock_client.talk.assert_called_once()


@patch("llm_cli.apps.unified.UnifiedClient")
def test_unified_direct_prompt(mock_client_class):
    mock_client = mock_client_class.return_value
    with patch.object(sys, "argv", ["llm", "Hello", "world"]):
        with patch("sys.stdin.isatty", return_value=True):
            main()
    mock_client.process_sources.assert_called_once()
    args, _ = mock_client.process_sources.call_args
    assert "Hello" in args[0]
    assert "world" in args[0]


@patch("llm_cli.apps.unified.UnifiedClient")
def test_unified_with_options(mock_client_class):
    with patch.object(sys, "argv", ["llm", "-p", "openai", "-m", "gpt-4", "Hi"]):
        with patch("sys.stdin.isatty", return_value=True):
            main()
    mock_client_class.assert_called()
    called_kwargs = mock_client_class.call_args.kwargs
    assert called_kwargs["initial_provider"] == "openai"
    assert called_kwargs["initial_model_alias"] == "gpt-4"


def test_unified_piped_input():
    with patch("llm_cli.apps.unified.UnifiedClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        with patch.object(sys, "argv", ["llm"]):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("sys.stdin.read", return_value="Piped input"):
                    main()
        mock_client.process_sources.assert_called_once_with(["Piped input"])


@patch("llm_cli.apps.unified.UnifiedClient")
def test_unified_mcp_server_branch(mock_client_class):
    with patch.object(sys, "argv", ["llm", "--mcp-server"]):
        with patch("llm_cli.apps.mcp_server.main") as mock_mcp_main:
            with pytest.raises(SystemExit) as e:
                main()
            assert e.value.code == 0
            mock_mcp_main.assert_called_once()


def test_unified_stdout_mcp_conflict(capsys):
    with patch.object(sys, "argv", ["llm", "--stdout", "--mcp"]):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error: --stdout and --mcp cannot be used together" in captured.out


def test_unified_client_init_and_switch():
    from llm_cli.clients.config import reload_config

    with patch("llm_cli.apps.unified.get_setting", return_value="google"):
        with patch(
            "llm_cli.clients.config._load_config_from_file",
            return_value={"general": {"unified_default_provider": "google"}},
        ):
            reload_config()
            mock_client_class = MagicMock()
            mock_client = mock_client_class.return_value
            mock_client.config_section = "openai"
            mock_client.pdf_as_base64 = False

            with patch(
                "llm_cli.apps.unified.client_registry.get_client_class",
                return_value=mock_client_class,
            ):
                with patch(
                    "llm_cli.apps.unified.client_registry.get_config_section",
                    return_value="openai",
                ):
                    client = UnifiedClient(initial_provider="openai")
                    assert client.current_provider_name == "openai"

                    # Switch provider
                    with patch.object(
                        client, "_activate_provider", return_value=True
                    ) as mock_activate:
                        client._handle_command("/provider google", None)
                        mock_activate.assert_called_with("google")


def test_unified_client_delegation():
    from llm_cli.clients.openai import OpenAIClient

    with patch("llm_cli.clients.config.get_setting", return_value="test_key"):
        with patch(
            "llm_cli.clients.config.get_model_aliases",
            return_value={"default": "gpt-4"},
        ):
            with patch("llm_cli.apps.unified.get_setting", return_value="google"):
                with patch(
                    "llm_cli.apps.unified.client_registry.get_client_class",
                    return_value=OpenAIClient,
                ):
                    with patch(
                        "llm_cli.apps.unified.client_registry.get_config_section",
                        return_value="google",
                    ):
                        client = UnifiedClient(initial_provider="google")

                        assert client.model == "gpt-4"
                        client.model = "new-model"
                        assert client.active_client.model == "new-model"

                        assert client.current_alias == "default"
                        client.current_alias = "pro"
                        assert client.active_client.current_alias == "pro"


def test_unified_client_handle_command_provider_list(capsys):
    from llm_cli.clients.openai import OpenAIClient

    with patch("llm_cli.clients.config.get_setting", return_value="test_key"):
        with patch(
            "llm_cli.clients.config.get_model_aliases",
            return_value={"default": "gpt-4"},
        ):
            with patch("llm_cli.apps.unified.get_setting", return_value="google"):
                with patch(
                    "llm_cli.apps.unified.client_registry.get_client_class",
                    return_value=OpenAIClient,
                ):
                    with patch(
                        "llm_cli.apps.unified.client_registry.get_config_section",
                        return_value="google",
                    ):
                        with patch(
                            "llm_cli.apps.unified.client_registry.get_provider_info",
                            return_value={"gemini": "google", "gpt": "openai"},
                        ):
                            client = UnifiedClient(initial_provider="google")
                            client._handle_command("/p", None)
                            captured = capsys.readouterr()
                            assert "Available Providers" in captured.out
                            assert "gemini" in captured.out
                            assert "gpt" in captured.out
