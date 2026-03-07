import os
import tomllib
from unittest.mock import MagicMock, mock_open, patch

import pytest

from llm_cli.clients import config


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset the config cache before each test."""
    config._config_cache = None
    yield
    config._config_cache = None


def test_load_config_no_files():
    """Test loading config when no files exist."""
    with patch("llm_cli.clients.config.Path.exists", return_value=False):
        cfg = config._load_config_from_file()
        assert cfg == {}


def test_load_config_only_defaults():
    """Test loading config when only defaults file exists."""
    defaults_dict = {"google": {"api_key": "default_key"}}

    # 1. defaults_path.exists() -> True
    # 2. CONFIG_FILE_PATH.exists() -> False
    with patch("llm_cli.clients.config.Path.exists", side_effect=[True, False]):
        with patch("llm_cli.clients.config.Path.open", mock_open()):
            with patch(
                "llm_cli.clients.config.tomllib.load", return_value=defaults_dict
            ):
                cfg = config._load_config_from_file()
                assert cfg["google"]["api_key"] == "default_key"


def test_load_config_user_overwrites_defaults():
    """Test that user config overwrites and merges with defaults."""
    defaults_dict = {
        "google": {
            "api_key": "default_key",
            "other": "default_val",
            "models": {"m1": "model1", "m2": "model2"},
        }
    }
    user_dict = {
        "google": {
            "api_key": "user_key",
            "models": {"m2": "user_model2", "m3": "user_model3"},
        },
        "new_section": {"key": "val"},
    }

    # 1. defaults_path.exists() -> True
    # 2. CONFIG_FILE_PATH.exists() -> True
    with patch("llm_cli.clients.config.Path.exists", return_value=True):
        with patch("llm_cli.clients.config.Path.open", mock_open()):
            with patch("llm_cli.clients.config.tomllib.load") as mock_toml_load:
                mock_toml_load.side_effect = [defaults_dict, user_dict]

                cfg = config._load_config_from_file()

                # Merged section 'google'
                assert cfg["google"]["api_key"] == "user_key"
                assert cfg["google"]["other"] == "default_val"

                # Merged 'models' dict
                assert cfg["google"]["models"]["m1"] == "model1"
                assert cfg["google"]["models"]["m2"] == "user_model2"
                assert cfg["google"]["models"]["m3"] == "user_model3"

                # New section
                assert cfg["new_section"]["key"] == "val"


def test_load_config_malformed_user_config():
    """Test handling of malformed user TOML config."""
    # 1. defaults_path.exists() -> False
    # 2. CONFIG_FILE_PATH.exists() -> True
    with patch("llm_cli.clients.config.Path.exists", side_effect=[False, True]):
        with patch("llm_cli.clients.config.Path.open", mock_open()):
            with patch(
                "llm_cli.clients.config.tomllib.load",
                side_effect=tomllib.TOMLDecodeError("msg", "doc", 0),
            ):
                with patch("sys.exit") as mock_exit:
                    with patch("sys.stderr", new_callable=MagicMock) as mock_stderr:
                        config._load_config_from_file()
                        mock_exit.assert_called_with(1)
                        written = "".join(
                            call.args[0] for call in mock_stderr.write.call_args_list
                        )
                        assert "Error: Could not parse config file" in written


def test_reload_config():
    """Test that reload_config clears the cache and calls load."""
    with patch("llm_cli.clients.config._load_config_from_file") as mock_load:
        mock_load.return_value = {"new": "config"}
        config._config_cache = {"old": "config"}

        res = config.reload_config()

        assert res == {"new": "config"}
        mock_load.assert_called_once()
        assert config._config_cache is None


def test_get_setting_env_vars():
    """Test get_setting prioritizing environment variables."""
    # Google
    with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini_key"}, clear=True):
        assert config.get_setting("api_key", "google") == "gemini_key"

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "google_key"}, clear=True):
        assert config.get_setting("api_key", "google") == "google_key"

    # Priority test: GEMINI_API_KEY > GOOGLE_API_KEY
    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "gemini_priority", "GOOGLE_API_KEY": "google_fallback"},
        clear=True,
    ):
        assert config.get_setting("api_key", "google") == "gemini_priority"

    # Anthropic
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "anthropic_key"}, clear=True):
        assert config.get_setting("api_key", "anthropic") == "anthropic_key"

    # OpenAI
    with patch.dict(os.environ, {"OPENAI_API_KEY": "openai_key"}, clear=True):
        assert config.get_setting("api_key", "openai") == "openai_key"

    # xAI
    with patch.dict(os.environ, {"XAI_API_KEY": "xai_key"}, clear=True):
        assert config.get_setting("api_key", "xai") == "xai_key"

    # vLLM
    with patch.dict(os.environ, {"VLLM_API_KEY": "vllm_key"}, clear=True):
        assert config.get_setting("api_key", "vllm") == "vllm_key"

    # Generic provider
    with patch.dict(os.environ, {"MYPROV_API_KEY": "myprov_key"}, clear=True):
        assert config.get_setting("api_key", "myprov") == "myprov_key"


def test_get_setting_fallback_to_config():
    """Test get_setting fallback to config file when env var is missing."""
    with patch(
        "llm_cli.clients.config._load_config_from_file",
        return_value={"google": {"api_key": "cfg_key"}},
    ):
        with patch.dict(os.environ, {}, clear=True):
            assert config.get_setting("api_key", "google") == "cfg_key"


def test_get_bool_setting():
    """Test get_bool_setting with various values."""
    mock_cfg = {
        "s": {
            "b1": True,
            "b2": False,
            "s1": "true",
            "s2": "1",
            "s3": "yes",
            "s4": "on",
            "s5": "false",
            "i1": 1,
            "i0": 0,
        }
    }
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        assert config.get_bool_setting("b1", "s") is True
        assert config.get_bool_setting("b2", "s") is False
        assert config.get_bool_setting("s1", "s") is True
        assert config.get_bool_setting("s2", "s") is True
        assert config.get_bool_setting("s3", "s") is True
        assert config.get_bool_setting("s4", "s") is True
        assert config.get_bool_setting("s5", "s") is False
        assert config.get_bool_setting("i1", "s") is True
        assert config.get_bool_setting("i0", "s") is False
        assert config.get_bool_setting("missing", "s", default=True) is True


def test_get_model_aliases():
    """Test get_model_aliases with different formats."""
    mock_cfg = {
        "google": {
            "models": {
                "a1": "model-1",
                "a2": {"model": "model-2"},
                "a3": "{'model': 'model-3'}",
                "a4": "{not valid dict}",
                "a5": 123,
            }
        }
    }
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        aliases = config.get_model_aliases("google")
        assert aliases["a1"] == "model-1"
        assert aliases["a2"] == "model-2"
        assert aliases["a3"] == "model-3"
        assert aliases["a4"] == "{not valid dict}"
        assert aliases["a5"] == "123"


def test_get_model_config():
    """Test get_model_config merging."""
    mock_cfg = {
        "anthropic": {
            "thinking_key": "thought",
            "include_thoughts": True,
            "models": {
                "haiku": "claude-3-haiku",
                "sonnet": {"model": "claude-3.5-sonnet", "thinking_budget": 1024},
            },
        }
    }
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        # String entry
        haiku_cfg = config.get_model_config("anthropic", "haiku")
        assert haiku_cfg["model"] == "claude-3-haiku"
        assert haiku_cfg["thinking_key"] == "thought"

        # Dict entry
        sonnet_cfg = config.get_model_config("anthropic", "sonnet")
        assert sonnet_cfg["model"] == "claude-3.5-sonnet"
        assert sonnet_cfg["thinking_budget"] == 1024
        assert sonnet_cfg["include_thoughts"] is True


def test_get_all_model_aliases():
    """Test get_all_model_aliases."""
    mock_cfg = {
        "google": {"models": {"g1": "gemini"}},
        "openai": {"models": {"o1": "gpt"}},
    }
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        all_aliases = config.get_all_model_aliases()
        assert all_aliases["google"] == {"g1": "gemini"}
        assert all_aliases["openai"] == {"o1": "gpt"}
        assert all_aliases["anthropic"] == {}


def test_get_provider_tools():
    """Test get_provider_tools."""
    mock_cfg = {"google": {"tools": {"search": "enabled"}}}
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        assert config.get_provider_tools("google") == {"search": "enabled"}


def test_get_mcp_servers():
    """Test get_mcp_servers."""
    mock_cfg = {"mcp_servers": [{"name": "test-server"}]}
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        assert config.get_mcp_servers() == [{"name": "test-server"}]


def test_get_templates():
    """Test get_templates."""
    mock_cfg = {"templates": {"summary": "Summarize this: {{text}}"}}
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        assert config.get_templates() == {"summary": "Summarize this: {{text}}"}


def test_load_config_cache_hit():
    """Test cache hit in _load_config_from_file (Line 16)."""
    config._config_cache = {"cached": True}
    # Should return the cache without calling any Path methods
    with patch("llm_cli.clients.config.Path.exists") as mock_exists:
        assert config._load_config_from_file() == {"cached": True}
        mock_exists.assert_not_called()


def test_get_model_aliases_ast_not_dict():
    """Test get_model_aliases when ast.literal_eval returns a non-dict (Line 138)."""
    mock_cfg = {
        "google": {
            "models": {
                "a1": "{1, 2, 3}",  # Starts with '{' but evaluates to a set
            }
        }
    }
    with patch("llm_cli.clients.config._load_config_from_file", return_value=mock_cfg):
        aliases = config.get_model_aliases("google")
        assert aliases["a1"] == "{1, 2, 3}"


def test_load_config_exception_in_defaults():
    """Test that exceptions during default loading are caught and ignored."""
    # 1. defaults_path.exists() -> True
    with patch("llm_cli.clients.config.Path.exists", side_effect=[True, False]):
        with patch("llm_cli.clients.config.Path.open", mock_open()):
            with patch(
                "llm_cli.clients.config.tomllib.load", side_effect=Exception("error")
            ):
                cfg = config._load_config_from_file()
                assert cfg == {}
