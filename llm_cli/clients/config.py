import sys
import tomllib

from pathlib import Path
from typing import Dict, Optional, Any

CONFIG_FILE_PATH = Path.home() / ".config" / "llm_cli" / "config.toml"
_config_cache: Optional[Dict[str, Any]] = None


def _load_config_from_file() -> Dict[str, Any]:
    """Loads configuration from the TOML file and caches it."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if CONFIG_FILE_PATH.exists():
        with open(CONFIG_FILE_PATH, "rb") as f:
            try:
                _config_cache = tomllib.load(f)
                return _config_cache
            except tomllib.TOMLDecodeError as e:
                print(f"Error: Could not parse config file at "
                      f"{CONFIG_FILE_PATH}. Please check its format.",
                      file=sys.stderr)
                print(f"Details: {e}", file=sys.stderr)
                sys.exit(1)

    # If the config file does not exist, cache an empty dictionary
    _config_cache = {}
    return _config_cache


def get_setting(key: str, section: str) -> Optional[str]:
    """Gets a specific setting value from a section in the config file."""
    config = _load_config_from_file()
    return config.get(section, {}).get(key)


def get_model_aliases(section: str) -> Dict[str, str]:
    """Loads all model aliases from a specific section in the config file."""
    config = _load_config_from_file()
    return config.get(section, {}).get("models", {})


def get_all_model_aliases() -> Dict[str, Dict[str, str]]:
    """
    Loads model alias configurations for all supported providers.
    Returns a dictionary where keys are provider names (e.g., 'google').
    """
    config = _load_config_from_file()
    all_aliases = {}
    providers = ['google', 'openai', 'anthropic', 'xai']
    for provider in providers:
        all_aliases[provider] = config.get(provider, {}).get("models", {})
    return all_aliases


def get_provider_tools(section: str) -> Dict[str, str]:
    config = _load_config_from_file()
    return config.get(section, {}).get("tools", {})
