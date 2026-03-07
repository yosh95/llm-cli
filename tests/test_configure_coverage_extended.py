import runpy
from unittest.mock import patch

import pytest

from llm_cli.apps.configure import (
    configure_mcp,
    configure_provider,
    configure_security,
    main,
    mask_secrets,
    prompt_bool,
    prompt_input,
    prompt_list,
)


def test_prompt_input_secret_masking():
    # Test line 62: masking current_value if secret and len > 8
    with patch("llm_cli.apps.configure.prompt") as mock_prompt:
        mock_prompt.return_value = ""
        prompt_input("Key", "1234567890", secret=True)
        args, kwargs = mock_prompt.call_args
        assert "[...7890]" in args[0]


def test_prompt_input_interrupt():
    with patch("llm_cli.apps.configure.prompt", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            prompt_input("Test")


def test_prompt_bool_logic():
    with patch("llm_cli.apps.configure.prompt") as mock_prompt:
        # Test current_value True
        mock_prompt.return_value = ""
        assert prompt_bool("Test", True) is True
        assert "(Y/n)" in mock_prompt.call_args[0][0]

        # Test current_value False
        mock_prompt.return_value = ""
        assert prompt_bool("Test", False) is False
        assert "(y/N)" in mock_prompt.call_args[0][0]

        # Test user input 'y'
        mock_prompt.return_value = "yes"
        assert prompt_bool("Test", False) is True

        # Test user input 'n'
        mock_prompt.return_value = "no"
        assert prompt_bool("Test", True) is False


def test_prompt_bool_interrupt():
    with patch("llm_cli.apps.configure.prompt", side_effect=EOFError):
        with pytest.raises(EOFError):
            prompt_bool("Test")


def test_prompt_list_empty():
    with patch("llm_cli.apps.configure.prompt", return_value=""):
        assert prompt_list("Test") == []


def test_configure_provider_no():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=False):
        configure_provider(config, "test", "Test Provider")
    assert "test" not in config


def test_configure_provider_ollama_vllm():
    config = {}
    # 1. Configure? Yes
    # 2. Disable date prompt? No
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            # 1. API Key, 2. API URL, 3. System Prompt, 4. Alias Default
            mock_input.side_effect = [
                "key",
                "http://localhost:11434",
                "sys",
                "alias-model",
            ]
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"ollama": {"models": {"default": "m"}}},
            ):
                configure_provider(config, "ollama", "Ollama")
    assert config["ollama"]["api_url"] == "http://localhost:11434"


def test_configure_provider_mamba():
    config = {}
    # 1. Configure? Yes
    # 2. Enable Mentor? Yes
    # 3. Disable date prompt? No
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            # 1. Teacher Provider, 2. Teacher Model, 3. Online LR, 4. System Prompt, 5. Alias Default
            mock_input.side_effect = ["vllm", "llama3", "0.001", "sys", "alias-model"]
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"mamba": {"models": {"default": "m"}}},
            ):
                configure_provider(config, "mamba", "Mamba")
    assert config["mamba"]["teacher_enabled"] is True
    assert config["mamba"]["teacher_provider"] == "vllm"
    assert config["mamba"]["online_lr"] == 0.001


def test_configure_provider_brave():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=True):
        with patch("llm_cli.apps.configure.prompt_input", return_value="brave-key"):
            configure_provider(config, "brave", "Brave")
    assert config["brave"]["api_key"] == "brave-key"


def test_configure_provider_ast_eval():
    config = {}
    # 1. Configure? Yes
    # 2. Disable date prompt? No
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            # 1. API key, 2. System prompt, 3. Model alias (as dict string)
            mock_input.side_effect = ["key", "sys", '{"model": "complex"}']
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"openai": {"models": {"default": "gpt-4"}}},
            ):
                configure_provider(config, "openai", "OpenAI")
    assert isinstance(config["openai"]["models"]["default"], dict)
    assert config["openai"]["models"]["default"]["model"] == "complex"


def test_configure_provider_ast_eval_fail():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            mock_input.side_effect = ["key", "sys", '{"invalid": }']
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"openai": {"models": {"default": "gpt-4"}}},
            ):
                configure_provider(config, "openai", "OpenAI")
    assert config["openai"]["models"]["default"] == '{"invalid": }'


def test_configure_mcp_remove_and_interrupt():
    config = {"mcp_servers": [{"name": "srv1", "command": "cmd1", "args": []}]}
    # Configure? Yes
    with patch("llm_cli.apps.configure.prompt_bool", return_value=True):
        with patch("llm_cli.apps.configure.prompt") as mock_prompt:
            # Options: [r]emove server -> 1 -> [d]one
            mock_prompt.side_effect = ["r", "1", "d"]
            configure_mcp(config)
    assert len(config["mcp_servers"]) == 0

    # Test remove index error
    config = {"mcp_servers": [{"name": "srv1", "command": "cmd1", "args": []}]}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=True):
        with patch("llm_cli.apps.configure.prompt") as mock_prompt:
            mock_prompt.side_effect = ["r", "invalid", "d"]
            configure_mcp(config)
    assert len(config["mcp_servers"]) == 1

    # Test remove interrupt
    config = {"mcp_servers": [{"name": "srv1", "command": "cmd1", "args": []}]}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=True):
        with patch("llm_cli.apps.configure.prompt") as mock_prompt:
            mock_prompt.side_effect = ["r", KeyboardInterrupt]
            with pytest.raises(KeyboardInterrupt):
                configure_mcp(config)


def test_mask_secrets_other_types():
    assert mask_secrets(123) == 123
    assert mask_secrets(None) is None


def test_main_cancel():
    with patch("llm_cli.apps.configure.load_config", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 0


def test_module_main():
    with patch("sys.argv", ["llm-cli-config"]):
        with patch("llm_cli.apps.configure.main"):
            # We don't even need to use runpy if we just want to test the if block
            # but runpy is the standard way.
            # To avoid real execution if the patch fails, we can catch it.
            try:
                runpy.run_module("llm_cli.apps.configure", run_name="__main__")
            except (SystemExit, EOFError):
                pass
    # Coverage is the main goal here.


def test_prompt_list_with_values():
    with patch("llm_cli.apps.configure.prompt", return_value="item1, item2"):
        assert prompt_list("Test") == ["item1", "item2"]


def test_configure_provider_vllm():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            mock_input.side_effect = [
                "key",
                "http://localhost:8000",
                "sys",
                "alias-model",
            ]
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"vllm": {"models": {"default": "m"}}},
            ):
                configure_provider(config, "vllm", "vLLM")
    assert config["vllm"]["api_url"] == "http://localhost:8000"


def test_configure_provider_ast_eval_not_dict():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", side_effect=[True, False]):
        with patch("llm_cli.apps.configure.prompt_input") as mock_input:
            # Literal eval works but it's a set, not a dict
            mock_input.side_effect = ["key", "sys", "{1, 2, 3}"]
            with patch(
                "llm_cli.apps.configure.DEFAULTS",
                {"openai": {"models": {"default": "gpt-4"}}},
            ):
                configure_provider(config, "openai", "OpenAI")
    assert config["openai"]["models"]["default"] == "{1, 2, 3}"


def test_configure_security_intent_analyzer_disabled():
    config = {}
    # 1. Modify allowed commands? No
    # 2. Modify allowed env vars? No
    # 3. Allow dangerous patterns? No
    # 4. Modify allowed paths? No
    # 5. Modify blocked paths? No
    # 6. Enable Intent Analyzer? No
    with patch(
        "llm_cli.apps.configure.prompt_bool",
        side_effect=[False, False, False, False, False, False],
    ):
        with patch("llm_cli.apps.configure.prompt_input", return_value="guest"):
            configure_security(config)
    assert config["security"]["intent_analyzer_enabled"] is False


def test_configure_mcp_early_exit():
    config = {}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=False):
        configure_mcp(config)
    assert "mcp_servers" not in config


def test_configure_mcp_keyboard_interrupt():
    config = {"mcp_servers": []}
    with patch("llm_cli.apps.configure.prompt_bool", return_value=True):
        with patch("llm_cli.apps.configure.prompt", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                configure_mcp(config)


def test_main_not_saved():
    with patch("llm_cli.apps.configure.load_config", return_value={}):
        with patch("llm_cli.apps.configure.configure_provider"):
            with patch("llm_cli.apps.configure.configure_general"):
                with patch("llm_cli.apps.configure.configure_security"):
                    with patch("llm_cli.apps.configure.configure_mcp"):
                        with patch(
                            "llm_cli.apps.configure.prompt_bool", return_value=False
                        ):  # For "Save configuration?"
                            main()
                            # Should print "Configuration NOT saved."


def test_defaults_missing_case(monkeypatch):
    # This tests line 27 when DEFAULTS_FILE doesn't exist.
    # Since it's module level, we need to reload or run the logic.
    import importlib

    import llm_cli.apps.configure

    with patch("pathlib.Path.exists", return_value=False):
        importlib.reload(llm_cli.apps.configure)
        assert llm_cli.apps.configure.DEFAULTS == {}

    # Reload again to restore defaults for other tests
    importlib.reload(llm_cli.apps.configure)
