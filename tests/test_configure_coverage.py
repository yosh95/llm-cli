from unittest.mock import patch

from llm_cli.apps.configure import (
    configure_general,
    configure_mcp,
    configure_provider,
    configure_security,
    load_config,
    main,
    mask_secrets,
    save_config,
)


def test_load_config_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "llm_cli.apps.configure.CONFIG_FILE", tmp_path / "no_config.toml"
    )
    assert load_config() == {}


def test_load_config_invalid(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "invalid.toml"
    config_file.write_text("invalid = [")
    monkeypatch.setattr("llm_cli.apps.configure.CONFIG_FILE", config_file)
    assert load_config() == {}
    assert "Warning: Could not parse" in capsys.readouterr().out


def test_save_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("llm_cli.apps.configure.CONFIG_FILE", config_file)
    monkeypatch.setattr("llm_cli.apps.configure.CONFIG_DIR", tmp_path)

    config = {"test": "data"}
    save_config(config)
    assert config_file.exists()
    assert config_file.read_text() == 'test = "data"\n'


def test_mask_secrets():
    data = {
        "api_key": "1234567890abcdef",
        "nested": {"api_key": "short"},
        "list": [{"api_key": "long_secret_key"}],
        "other": "value",
        "github": "github_pat_1234567890abcdefg",
    }
    masked = mask_secrets(data)
    assert masked["api_key"] == "...cdef"
    assert masked["nested"]["api_key"] == "***"
    assert masked["list"][0]["api_key"] == "..._key"
    assert masked["other"] == "value"
    assert masked["github"] == "github_pat_...defg"


@patch("llm_cli.apps.configure.prompt")
@patch("llm_cli.apps.configure.prompt_bool")
def test_configure_provider(mock_prompt_bool, mock_prompt):
    # 1. prompt_bool("Configure OpenAI?") -> True
    # 2. prompt_bool("Disable automatic date prompt?") -> True
    mock_prompt_bool.side_effect = [True, True]

    # 1. prompt_input("API Key") -> "sk-test"
    # 2. prompt_input("System Prompt") -> "Custom prompt"
    # 3. prompt_input("Model for alias 'default'") -> "my-model"
    mock_prompt.side_effect = ["sk-test", "Custom prompt", "my-model"]

    config = {}
    with patch(
        "llm_cli.apps.configure.DEFAULTS", {"openai": {"models": {"default": "gpt-4"}}}
    ):
        configure_provider(config, "openai", "OpenAI")

    assert config["openai"]["api_key"] == "sk-test"
    assert config["openai"]["system_prompt"] == "Custom prompt"
    assert config["openai"]["models"]["default"] == "my-model"


@patch("llm_cli.apps.configure.prompt")
def test_configure_general(mock_prompt):
    mock_prompt.side_effect = ["anthropic", "10", "20", "512", "1000"]
    config = {}
    configure_general(config)
    assert config["general"]["unified_default_provider"] == "anthropic"
    assert config["general"]["request_timeout"] == 10
    assert config["general"]["command_timeout"] == 20


@patch("llm_cli.apps.configure.prompt")
@patch("llm_cli.apps.configure.prompt_bool")
@patch("llm_cli.apps.configure.prompt_list")
def test_configure_security(mock_prompt_list, mock_prompt_bool, mock_prompt):
    mock_prompt_bool.side_effect = [True, True, False, True, True, True]
    mock_prompt_list.side_effect = [["ls", "grep"], ["PATH"], ["/tmp"], ["/etc"]]
    mock_prompt.side_effect = ["deny", "google", "gemini-pro"]

    config = {}
    configure_security(config)

    assert config["security"]["allowed_commands"] == ["ls", "grep"]
    assert config["security"]["missing_token_policy"] == "deny"
    assert config["security"]["intent_analyzer_enabled"] is True
    assert config["security"]["intent_analyzer_provider"] == "google"


@patch("llm_cli.apps.configure.prompt")
@patch("llm_cli.apps.configure.prompt_bool")
def test_configure_mcp(mock_prompt_bool, mock_prompt):
    mock_prompt.side_effect = ["a", "test-srv", "npx", "-y some-tool", "d"]
    mock_prompt_bool.side_effect = [True, True]

    config = {}
    configure_mcp(config)
    assert len(config["mcp_servers"]) == 1
    assert config["mcp_servers"][0]["name"] == "test-srv"
    assert config["mcp_servers"][0]["zero_trust"] is True


@patch("llm_cli.apps.configure.load_config")
@patch("llm_cli.apps.configure.save_config")
@patch("llm_cli.apps.configure.prompt_bool")
def test_main_configure(mock_prompt_bool, mock_save, mock_load):
    mock_load.return_value = {}
    mock_prompt_bool.return_value = False

    with patch("llm_cli.apps.configure.configure_provider"):
        with patch("llm_cli.apps.configure.configure_general"):
            with patch("llm_cli.apps.configure.configure_security"):
                with patch("llm_cli.apps.configure.configure_mcp"):
                    with patch(
                        "llm_cli.apps.configure.prompt_bool", return_value=True
                    ):  # For "Save configuration?"
                        main()

    mock_save.assert_called_once()
