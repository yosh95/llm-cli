# llm_cli/apps/configure.py

import json
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.shortcuts import CompleteStyle

from llm_cli.consts import CONFIG_DIR, CONFIG_FILE_PATH

# Define the path for the configuration directory and file
CONFIG_FILE = CONFIG_FILE_PATH

# Load default values from external TOML
DEFAULTS_FILE = Path(__file__).parent / "defaults.toml"
if DEFAULTS_FILE.exists():
    with DEFAULTS_FILE.open("rb") as f:
        DEFAULTS = tomllib.load(f)
else:
    DEFAULTS = {}


def load_config() -> dict[str, Any]:
    """Loads the configuration file and returns it as a dictionary."""
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("rb") as f:
        try:
            return tomllib.load(f)
        except Exception:
            print(
                f"Warning: Could not parse {CONFIG_FILE}. Starting with empty config."
            )
            return {}


def save_config(config: dict[str, Any]) -> None:
    """Saves the configuration dictionary to the file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Ensure secure permissions
    CONFIG_FILE.touch(mode=0o600, exist_ok=True)
    with CONFIG_FILE.open("wb") as f:
        tomli_w.dump(config, f)


def prompt_input(
    prompt_text: str,
    current_value: Any = None,
    secret: bool = False,
    completer: Any = None,
) -> str:
    """Displays a prompt and returns user input or current value."""
    if current_value is not None:
        if secret and isinstance(current_value, str) and len(current_value) > 8:
            display_val = f"...{current_value[-4:]}"
        else:
            display_val = str(current_value)
        prompt_str = f"{prompt_text} [{display_val}]: "
    else:
        prompt_str = f"{prompt_text}: "

    try:
        value = prompt(
            prompt_str,
            completer=completer,
            complete_style=CompleteStyle.READLINE_LIKE,
            is_password=secret,
        ).strip()
    except (KeyboardInterrupt, EOFError):
        # We handle this in main() but for smaller prompts we might just return current
        return str(current_value) if current_value is not None else ""

    return value if value else (str(current_value) if current_value is not None else "")


def prompt_bool(prompt_text: str, current_value: bool = False) -> bool:
    """Prompts for a boolean value."""
    default_str = "Y/n" if current_value else "y/N"
    try:
        val = (
            prompt(
                f"{prompt_text} ({default_str}): ",
                complete_style=CompleteStyle.READLINE_LIKE,
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        return current_value

    if not val:
        return current_value
    return val.startswith("y")


def prompt_list(prompt_text: str, current_value: list[str] | None = None) -> list[str]:
    """Prompts for a comma-separated list."""
    current_str = ", ".join(current_value) if current_value else ""
    val = prompt_input(prompt_text + " (comma-separated)", current_str)
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def configure_provider(config: dict[str, Any], provider: str, name: str) -> None:
    """Interactively configures a specific LLM provider."""
    print(f"\n--- {name} Configuration ---")
    if not prompt_bool(f"Configure {name}?", provider in config):
        return

    p_config = config.setdefault(provider, {})

    if provider == "ollama":
        default_url = DEFAULTS.get("ollama", {}).get("api_url")
        p_config["api_url"] = prompt_input(
            "API URL", p_config.get("api_url", default_url)
        )
    elif provider == "vllm":
        p_config["api_key"] = prompt_input(
            "API Key (Optional)", p_config.get("api_key"), secret=True
        )
        default_url = DEFAULTS.get("vllm", {}).get("api_url")
        p_config["api_url"] = prompt_input(
            "API URL", p_config.get("api_url", default_url)
        )
    else:
        p_config["api_key"] = prompt_input(
            "API Key", p_config.get("api_key"), secret=True
        )

    if provider == "google":
        p_config["cse_id"] = prompt_input(
            "Google Custom Search Engine ID (Optional)", p_config.get("cse_id")
        )

    p_config["system_prompt"] = prompt_input(
        "System Prompt (Optional)", p_config.get("system_prompt")
    )
    p_config["disable_date_prompt"] = prompt_bool(
        "Disable automatic date prompt?", p_config.get("disable_date_prompt", False)
    )

    print(f"\nModel Aliases for {name} (Press Enter to keep default):")
    m_config = p_config.setdefault("models", {})

    # Configure default models and aliases
    provider_defaults = DEFAULTS.get(provider, {}).get("models", {})
    for alias, def_model in provider_defaults.items():
        current_val = m_config.get(alias, def_model)
        user_input = prompt_input(f"Model for alias '{alias}'", current_val)

        # If the input looks like a dictionary string (common when defaults have dicts),
        # try to convert it back to a real dictionary so tomli_w saves it correctly.
        if isinstance(user_input, str) and user_input.startswith("{"):
            try:
                import ast

                parsed = ast.literal_eval(user_input)
                if isinstance(parsed, dict):
                    m_config[alias] = parsed
                else:
                    m_config[alias] = user_input
            except (ValueError, SyntaxError):
                m_config[alias] = user_input
        else:
            m_config[alias] = user_input


def configure_general(config: dict[str, Any]) -> None:
    """Configures general application settings, including data paths."""
    print("\n--- General Settings ---")
    g_config = config.setdefault("general", {})

    providers = ["google", "openai", "anthropic", "xai", "ollama", "vllm"]
    current_p = g_config.get("unified_default_provider", "google")
    print(f"Available providers: {', '.join(providers)}")
    g_config["unified_default_provider"] = prompt_input("Default Provider", current_p)

    print("\nData Storage Paths (Press Enter to keep default):")

    from llm_cli.consts import AUDIT_LOG_PATH, CHAT_LOG_PATH, HISTORY_LOG_PATH

    path_completer = PathCompleter(expanduser=True)
    g_config["LLM_PROMPT_HISTORY"] = prompt_input(
        "Prompt History Path",
        g_config.get("LLM_PROMPT_HISTORY", str(HISTORY_LOG_PATH)),
        completer=path_completer,
    )
    g_config["LLM_CHAT_LOG"] = prompt_input(
        "Chat Log Path",
        g_config.get("LLM_CHAT_LOG", str(CHAT_LOG_PATH)),
        completer=path_completer,
    )
    g_config["LLM_AUDIT_LOG"] = prompt_input(
        "Audit Log Path (Tool usage)",
        g_config.get("LLM_AUDIT_LOG", str(AUDIT_LOG_PATH)),
        completer=path_completer,
    )

    print("\nBehavior Settings:")
    g_config["request_timeout"] = int(
        prompt_input("Request Timeout (seconds)", g_config.get("request_timeout", 1800))
    )


def configure_security(config: dict[str, Any]) -> None:
    """Configures security settings, including allowed commands."""
    print("\n--- Security Settings ---")
    s_config = config.setdefault("security", {})

    # Configure Allowed Commands
    current_allowed = s_config.get("allowed_commands", [])
    print(f"Current allowed commands: {current_allowed}")

    if prompt_bool("Modify allowed commands?", False):
        new_allowed = prompt_list("Allowed Commands", current_allowed)
        s_config["allowed_commands"] = new_allowed

    # Configure Missing Token Policy
    s_config["missing_token_policy"] = prompt_input(
        "Missing Token Policy (guest/deny)",
        s_config.get("missing_token_policy", "guest"),
    )

    # Configure Intent Analyzer (New!)
    print("\n--- Intent Analyzer (Dual-Model Guardrails) ---")
    current_ia_enabled = s_config.get("intent_analyzer_enabled", False)
    if prompt_bool("Enable Intent Analyzer?", current_ia_enabled):
        s_config["intent_analyzer_enabled"] = True

        current_ia_provider = s_config.get("intent_analyzer_provider", "google")
        s_config["intent_analyzer_provider"] = prompt_input(
            "Verifier Provider (e.g., google, ollama)", current_ia_provider
        )

        current_ia_model = s_config.get(
            "intent_analyzer_model", "gemini-flash-lite-latest"
        )
        s_config["intent_analyzer_model"] = prompt_input(
            "Verifier Model Name", current_ia_model
        )
    else:
        s_config["intent_analyzer_enabled"] = False


def configure_mcp(config: dict[str, Any]) -> None:
    """Configures MCP servers."""
    print("\n--- MCP (Model Context Protocol) Servers ---")
    if not prompt_bool("Configure MCP servers?", "mcp_servers" in config):
        return

    mcp_servers = config.get("mcp_servers", [])

    while True:
        if mcp_servers:
            print("\nCurrent MCP Servers:")
            for i, srv in enumerate(mcp_servers):
                print(f"{i + 1}. {srv.get('name')} ({srv.get('command')})")

        try:
            choice = prompt(
                "\nOptions: [a]dd server, [r]emove server, [d]one: ",
                complete_style=CompleteStyle.READLINE_LIKE,
            ).lower()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "a":
            name = prompt(
                "Server Name: ", complete_style=CompleteStyle.READLINE_LIKE
            ).strip()
            cmd = prompt(
                "Command (e.g. ssh, docker, npx): ",
                complete_style=CompleteStyle.READLINE_LIKE,
                completer=PathCompleter(expanduser=True),
            ).strip()
            args_str = prompt(
                "Arguments (space separated): ",
                complete_style=CompleteStyle.READLINE_LIKE,
            ).strip()
            args = shlex.split(args_str)
            mcp_servers.append({"name": name, "command": cmd, "args": args})
        elif choice == "r" and mcp_servers:
            try:
                idx_str = prompt(
                    "Server number to remove: ",
                    complete_style=CompleteStyle.READLINE_LIKE,
                )
                idx = int(idx_str) - 1
                if 0 <= idx < len(mcp_servers):
                    mcp_servers.pop(idx)
            except (ValueError, KeyboardInterrupt, EOFError):
                pass
        elif choice == "d" or not choice:
            break

    config["mcp_servers"] = mcp_servers


def mask_secrets(data: Any) -> Any:
    """Recursively mask sensitive information in configuration data."""
    if isinstance(data, dict):
        return {
            k: mask_secrets(v)
            if k != "api_key"
            else (f"...{v[-4:]}" if isinstance(v, str) and len(v) > 8 else "***")
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [mask_secrets(item) for item in data]
    if isinstance(data, str):
        # Match github_pat_ followed by at least 10 alphanumeric characters
        return re.sub(
            r"github_pat_[a-zA-Z0-9_]{10,}",
            lambda m: f"{m.group(0)[:11]}...{m.group(0)[-4:]}",
            data,
        )
    return data


def main() -> None:
    try:
        print("========================================")
        print("   llm-cli Interactive Configuration    ")
        print("========================================")
        print(f"Config file: {CONFIG_FILE}\n")

        config = load_config()

        # Provider configurations
        configure_provider(config, "google", "Google Gemini")
        configure_provider(config, "openai", "OpenAI")
        configure_provider(config, "anthropic", "Anthropic Claude")
        configure_provider(config, "xai", "xAI Grok")
        configure_provider(config, "ollama", "Ollama (Local)")
        configure_provider(config, "vllm", "vLLM")

        # General and Security
        configure_general(config)
        configure_security(config)
        configure_mcp(config)

        print("\nSummary of changes:")
        display_config = mask_secrets(config)

        print(json.dumps(display_config, indent=2, ensure_ascii=False))

        # Check if user wants to save
        if prompt_bool("Save configuration?", True):
            save_config(config)
            print(f"\nConfiguration saved to {CONFIG_FILE}")
        else:
            print("\nConfiguration NOT saved.")
    except KeyboardInterrupt:
        print("\n\nConfiguration cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
