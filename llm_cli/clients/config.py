import os
import sys
import tomllib
from pathlib import Path
from typing import Any, cast

from llm_cli.clients.config_models import AppConfig
from llm_cli.consts import CONFIG_FILE_PATH, LLM_CLI_BASE_DIR


class ConfigManager:
    _instance: "ConfigManager | None" = None
    _config_cache: dict[str, Any] | None = None
    _app_config: AppConfig | None = None
    _env_loaded: bool = False

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_env_files(self) -> None:
        """Loads environment variables from .env files if they exist."""
        if self._env_loaded:
            return

        # Priority: Current directory .env -> ~/.llm_cli/.env
        dotenv_paths = [
            Path(".env"),
            LLM_CLI_BASE_DIR / ".env",
        ]
        for path in dotenv_paths:
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            if "=" in line:
                                key, val = line.split("=", 1)
                                key = key.strip()
                                # Simple stripping of quotes
                                val = val.strip().strip("'").strip('"')
                                if key and key not in os.environ:
                                    os.environ[key] = val
                except Exception:
                    pass
        self._env_loaded = True

    def load_config(self, reload: bool = False) -> dict[str, Any]:
        """Loads configuration from the TOML file and caches it."""
        self._load_env_files()
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
                        f"Error: Could not parse config file at {CONFIG_FILE_PATH}. "
                        "Please check its format.",
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
        self._load_env_files()
        # API keys MUST come from environment variables for security.
        # This also serves as the "active" flag for a provider.
        if key == "api_key":
            env_map = {
                "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                "openai": ["OPENAI_API_KEY"],
                "anthropic": ["ANTHROPIC_API_KEY"],
                "brave": ["BRAVE_API_KEY"],
                "ollama": ["OLLAMA_API_KEY"],
            }
            env_vars = env_map.get(section, [])
            for env_var in env_vars:
                val = os.environ.get(env_var)
                if val:
                    return val

            # Fallback to config file if not in environment
            config_dict = self.load_config()
            val = config_dict.get(section, {}).get("api_key")
            if val:
                return val

            # Special case for Ollama: Bypass API key requirement if hosted on localhost
            # and a model is explicitly configured.
            if section == "ollama":
                try:
                    config_dict = self.load_config()
                    ollama_cfg = config_dict.get("ollama", {})
                    base_url = str(ollama_cfg.get("base_url", ""))
                    models = ollama_cfg.get("models", {})

                    # Only bypass if localhost AND at least one model alias is defined
                    if (
                        "localhost" in base_url or "127.0.0.1" in base_url or not base_url
                    ) and models:
                        return "local_bypass"
                except Exception:
                    pass

            return None  # Provider is inactive if no env var is found

        config_dict = self.load_config()
        return config_dict.get(section, {}).get(key, default)

    def get_active_providers(self) -> list[str]:
        """Returns a list of providers that have an API key set in env vars."""
        active = []
        for provider in ["google", "openai", "anthropic", "ollama"]:
            if self.get(provider, "api_key"):
                active.append(provider)
        return active

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

    def set(self, section: str, key: str, value: Any) -> None:
        """Sets a configuration value in the cache (runtime override)."""
        if self._config_cache is None:
            self.load_config()

        if self._config_cache is not None:
            if section not in self._config_cache:
                self._config_cache[section] = {}
            self._config_cache[section][key] = value
            # Re-sync AppConfig
            self._app_config = AppConfig.from_dict(self._config_cache)

    @classmethod
    def reset(cls) -> None:
        """Resets the singleton state for testing."""
        cls._config_cache = None
        cls._app_config = None
        cls._env_loaded = False


# Global instance
config_manager = ConfigManager()
