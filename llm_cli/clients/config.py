import os
import sys
import tomllib
from pathlib import Path
from typing import Any, cast

from llm_cli.clients.config_models import AppConfig
from llm_cli.consts import CONFIG_FILE_PATH


class ConfigManager:
    _instance: "ConfigManager | None" = None
    _config_cache: dict[str, Any] | None = None
    _app_config: AppConfig | None = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_config(self, reload: bool = False) -> dict[str, Any]:
        """Loads configuration from the TOML file and caches it."""
        if self._config_cache is not None and not reload:
            return self._config_cache

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
                        existing_models.update(v)
                        merged_section["models"] = existing_models
                    else:
                        merged_section[k] = v
                final_config[section] = merged_section
            else:
                final_config[section] = settings

        self._config_cache = final_config
        self._app_config = AppConfig.from_dict(final_config)
        return self._config_cache

    @property
    def config(self) -> AppConfig:
        """Returns the structured AppConfig model."""
        if self._app_config is None:
            self.load_config()
        return cast(AppConfig, self._app_config)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Gets a setting value using (section, key) order."""
        # Prioritize environment variables for API keys
        if key == "api_key":
            env_vars = []
            if section == "google":
                env_vars = ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
            elif section == "anthropic":
                env_vars = ["ANTHROPIC_API_KEY"]
            elif section == "openai":
                env_vars = ["OPENAI_API_KEY"]
            elif section == "xai":
                env_vars = ["XAI_API_KEY"]
            else:
                env_vars = [f"{section.upper()}_API_KEY"]

            for env_var in env_vars:
                val = os.environ.get(env_var)
                if val:
                    return val

        config_dict = self.load_config()
        return config_dict.get(section, {}).get(key, default)

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """Gets a boolean setting value using (section, key) order."""
        val = self.get(section, key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    def get_model_config(self, section: str, alias: str) -> dict[str, Any]:
        """Retrieves the full configuration for a specific model alias."""
        config_dict = self.load_config()
        provider_cfg = config_dict.get(section, {})
        result = {k: v for k, v in provider_cfg.items() if k != "models"}
        models = provider_cfg.get("models", {})
        model_entry = models.get(alias)

        if isinstance(model_entry, dict):
            result.update(model_entry)
        elif isinstance(model_entry, str):
            result["model"] = model_entry
        return result

    def get_model_aliases(self, section: str) -> dict[str, str]:
        """Loads all model aliases from a specific section."""
        config_dict = self.load_config()
        models = config_dict.get(section, {}).get("models", {})
        normalized = {}
        for alias, entry in models.items():
            if isinstance(entry, dict):
                normalized[alias] = entry.get("model", "")
            else:
                normalized[alias] = str(entry)
        return normalized

    def get_mcp_servers(self) -> list[dict[str, Any]]:
        config_dict = self.load_config()
        return cast(list[dict[str, Any]], config_dict.get("mcp_servers", []))

    def get_templates(self) -> dict[str, str]:
        config_dict = self.load_config()
        return cast(dict[str, str], config_dict.get("templates", {}))


# Global instance
config_manager = ConfigManager()
