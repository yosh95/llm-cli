import sys
import tomllib
from pathlib import Path
from typing import Any, cast

from llm_cli.consts import CONFIG_FILE_PATH

_config_cache: dict[str, Any] | None = None


def _load_config_from_file() -> dict[str, Any]:
    """Loads configuration from the TOML file and caches it."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # 1. Load defaults from the package
    defaults_path = Path(__file__).parent.parent / "apps" / "defaults.toml"
    defaults = {}
    if defaults_path.exists():
        with defaults_path.open("rb") as f:
            try:
                defaults = tomllib.load(f)
            except Exception:
                pass

    # 2. Load user config
    user_config = {}
    if CONFIG_FILE_PATH.exists():
        with CONFIG_FILE_PATH.open("rb") as f:
            try:
                user_config = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                print(
                    f"Error: Could not parse config file at "
                    f"{CONFIG_FILE_PATH}. Please check its format.",
                    file=sys.stderr,
                )
                print(f"Details: {e}", file=sys.stderr)
                sys.exit(1)

    # 3. Merge user_config into defaults
    final_config = defaults.copy()
    for section, settings in user_config.items():
        if (
            section in final_config
            and isinstance(final_config[section], dict)
            and isinstance(settings, dict)
        ):
            merged_section = final_config[section].copy()
            for k, v in settings.items():
                if k == "models" and isinstance(v, dict):
                    existing_models = merged_section.get("models", {}).copy()
                    # Ensure entries in user config overwrite defaults
                    existing_models.update(v)
                    merged_section["models"] = existing_models
                else:
                    merged_section[k] = v
            final_config[section] = merged_section
        else:
            final_config[section] = settings

    _config_cache = final_config
    return _config_cache


def get_setting(key: str, section: str) -> Any | None:
    """Gets a specific setting value from a section in the config file."""
    config = _load_config_from_file()
    return config.get(section, {}).get(key)


def get_bool_setting(key: str, section: str, default: bool = False) -> bool:
    """Gets a boolean setting value from a section in the config file."""
    val = get_setting(key, section)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return bool(val)


def get_model_aliases(section: str) -> dict[str, str]:
    """
    Loads all model aliases from a specific section in the config file.
    Returns a mapping of alias -> model name (string).
    """
    config = _load_config_from_file()
    models = config.get(section, {}).get("models", {})

    # Normalize: ensure all values are strings (the model name)
    normalized = {}
    for alias, entry in models.items():
        if isinstance(entry, dict):
            # Extract only the model name string from the dictionary
            normalized[alias] = entry.get("model", "")
        elif isinstance(entry, str) and entry.startswith("{"):
            # Handle cases where it might still be a string-representation of a dict
            try:
                import ast

                parsed = ast.literal_eval(entry)
                if isinstance(parsed, dict):
                    normalized[alias] = parsed.get("model", "")
                else:
                    normalized[alias] = entry
            except (ValueError, SyntaxError):
                normalized[alias] = entry
        else:
            normalized[alias] = str(entry)
    return normalized


def get_model_config(section: str, alias: str) -> dict[str, Any]:
    """
    Retrieves the full configuration for a specific model alias.
    Merges provider-level defaults with model-specific overrides.
    """
    config = _load_config_from_file()
    provider_cfg = config.get(section, {})

    # 1. Start with provider-level settings (e.g. thinking_key, include_thoughts)
    result = {k: v for k, v in provider_cfg.items() if k != "models"}

    # 2. Get model-specific settings
    models = provider_cfg.get("models", {})
    model_entry = models.get(alias)

    if isinstance(model_entry, dict):
        # If it's a dict (e.g. {model="...", thinking_budget=1024}), merge it
        result.update(model_entry)
    elif isinstance(model_entry, str):
        # If it's just a string (the model name), set the 'model' key
        result["model"] = model_entry

    return result


def get_all_model_aliases() -> dict[str, dict[str, str]]:
    """
    Loads model alias configurations for all supported providers.
    Returns a dictionary where keys are provider names (e.g., 'google').
    """
    config = _load_config_from_file()
    all_aliases = {}
    providers = ["google", "openai", "anthropic", "xai", "ollama", "vllm"]
    for provider in providers:
        all_aliases[provider] = config.get(provider, {}).get("models", {})
    return all_aliases


def get_provider_tools(section: str) -> dict[str, str]:
    config = _load_config_from_file()
    return cast(dict[str, str], config.get(section, {}).get("tools", {}))


def get_mcp_servers() -> list[dict[str, Any]]:
    """Loads MCP server configurations from the config file."""
    config = _load_config_from_file()
    return cast(list[dict[str, Any]], config.get("mcp_servers", []))


def get_templates() -> dict[str, str]:
    """Loads prompt templates from the [templates] section of the config file."""
    config = _load_config_from_file()
    return cast(dict[str, str], config.get("templates", {}))
