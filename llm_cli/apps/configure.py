# llm_cli/apps/configure.py

import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List

import tomli_w

# Define the path for the configuration directory and file
CONFIG_DIR = Path.home() / ".config" / "llm_cli"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Default Model Constants
DEFAULTS = {
    "google": {
        "default": "gemini-3-flash-preview",
        "lite": "gemini-2.5-flash-lite",
        "flash": "gemini-3-flash-preview",
        "pro": "gemini-3-pro-preview",
        "image": "gemini-3-pro-image-preview",
    },
    "openai": {
        "default": "gpt-5.2",
        "nano": "gpt-5-nano",
        "mini": "gpt-5-mini",
    },
    "anthropic": {
        "default": "claude-opus-4-5-20250929",
        "haiku": "claude-haiku-4-5-20250929",
        "sonnet": "claude-sonnet-4-5-20250929",
        "opus": "claude-opus-4-5-20250929",
    },
    "xai": {
        "default": "grok-4-fast-reasoning",
        "non-reasoning": "grok-4-fast-non-reasoning",
        "reasoning": "grok-4-fast-reasoning",
    },
    "ollama": {
        "default": "gemma3:270m",
        "api_url": "http://localhost:11434/v1/chat/completions",
    },
}


def load_config() -> Dict[str, Any]:
    """Loads the configuration file and returns it as a dictionary."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        try:
            return tomllib.load(f)
        except Exception:
            print(
                f"Warning: Could not parse {CONFIG_FILE}. Starting with empty config."
            )
            return {}


def save_config(config: Dict[str, Any]):
    """Saves the configuration dictionary to the file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Ensure secure permissions
    CONFIG_FILE.touch(mode=0o600, exist_ok=True)
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(config, f)


def prompt_input(
    prompt_text: str, current_value: Any = None, secret: bool = False
) -> str:
    """Displays a prompt and returns user input or current value."""
    if current_value is not None:
        if secret and isinstance(current_value, str) and len(current_value) > 8:
            display_val = f"...{current_value[-4:]}"
        else:
            display_val = str(current_value)
        prompt = f"{prompt_text} [{display_val}]: "
    else:
        prompt = f"{prompt_text}: "

    value = input(prompt).strip()
    return value if value else (str(current_value) if current_value is not None else "")


def prompt_bool(prompt_text: str, current_value: bool = False) -> bool:
    """Prompts for a boolean value."""
    default_str = "Y/n" if current_value else "y/N"
    val = input(f"{prompt_text} ({default_str}): ").strip().lower()
    if not val:
        return current_value
    return val.startswith("y")


def prompt_list(prompt_text: str, current_value: List[str] = None) -> List[str]:
    """Prompts for a comma-separated list."""
    current_str = ", ".join(current_value) if current_value else ""
    val = prompt_input(prompt_text + " (comma-separated)", current_str)
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def configure_provider(config: Dict[str, Any], provider: str, name: str):
    """Interactively configures a specific LLM provider."""
    print(f"\n--- {name} Configuration ---")
    if not prompt_bool(f"Configure {name}?", provider in config):
        return

    p_config = config.setdefault(provider, {})

    if provider != "ollama":
        p_config["api_key"] = prompt_input(
            "API Key", p_config.get("api_key"), secret=True
        )
    else:
        p_config["api_url"] = prompt_input(
            "API URL", p_config.get("api_url", DEFAULTS["ollama"]["api_url"])
        )

    if provider == "google":
        p_config["cse_id"] = prompt_input(
            "Google Custom Search Engine ID (Optional)", p_config.get("cse_id")
        )

    p_config["system_prompt"] = prompt_input(
        "System Prompt (Optional)",
        p_config.get("system_prompt", "You are a helpful assistant."),
    )

    print(f"\nModel Aliases for {name}:")
    m_config = p_config.setdefault("models", {})

    # Configure default models and aliases
    provider_defaults = DEFAULTS.get(provider, {})
    for alias, def_model in provider_defaults.items():
        if alias == "api_url":
            continue
        m_config[alias] = prompt_input(
            f"Model for alias '{alias}'", m_config.get(alias, def_model)
        )


def configure_general(config: Dict[str, Any]):
    """Configures general application settings."""
    print("\n--- General Settings ---")
    g_config = config.setdefault("general", {})

    providers = ["google", "openai", "anthropic", "xai", "ollama"]
    current_p = g_config.get("unified_default_provider", "google")
    print(f"Available providers: {', '.join(providers)}")
    g_config["unified_default_provider"] = prompt_input("Default Provider", current_p)

    g_config["LLM_PROMPT_HISTORY"] = prompt_input(
        "Prompt History Path",
        g_config.get("LLM_PROMPT_HISTORY", "~/.config/llm_cli/history.log"),
    )
    g_config["LLM_CHAT_LOG"] = prompt_input(
        "Chat Log Path", g_config.get("LLM_CHAT_LOG", "~/.config/llm_cli/chat.log")
    )
    g_config["LLM_AUDIT_LOG"] = prompt_input(
        "Audit Log Path (for tools)",
        g_config.get("LLM_AUDIT_LOG", "~/.local/state/llm_cli/audit.log"),
    )

    try:
        g_config["max_chat_log_lines"] = int(
            prompt_input(
                "Max Chat Log Lines", g_config.get("max_chat_log_lines", 10000)
            )
        )
        g_config["max_audit_log_lines"] = int(
            prompt_input(
                "Max Audit Log Lines", g_config.get("max_audit_log_lines", 5000)
            )
        )
    except ValueError:
        print("Invalid number, keeping defaults.")


def configure_security(config: Dict[str, Any]):
    """Configures security guardrails for AI agents."""
    print("\n--- Security Settings (AI Agent Guardrails) ---")
    if not prompt_bool("Configure security settings?", "security" in config):
        return

    s_config = config.setdefault("security", {})

    print(
        "\nNote: Many basic commands (ls, cat, grep, etc.) are whitelisted by default."
    )
    s_config["allowed_commands"] = prompt_list(
        "Additional allowed shell commands", s_config.get("allowed_commands", [])
    )
    s_config["allowed_mcp_commands"] = prompt_list(
        "Additional allowed MCP commands", s_config.get("allowed_mcp_commands", [])
    )

    print(
        "\nWARNING: allow_dangerous_patterns enables shell pipes (|), "
        "redirects (>), etc."
    )
    s_config["allow_dangerous_patterns"] = prompt_bool(
        "Allow dangerous shell patterns?",
        s_config.get("allow_dangerous_patterns", False),
    )


def configure_mcp(config: Dict[str, Any]):
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

        choice = input("\nOptions: [a]dd server, [r]emove server, [d]one: ").lower()
        if choice == "a":
            name = input("Server Name: ").strip()
            cmd = input("Command (e.g. ssh, docker, npx): ").strip()
            args_str = input("Arguments (space separated): ").strip()
            args = shlex.split(args_str)
            mcp_servers.append({"name": name, "command": cmd, "args": args})
        elif choice == "r" and mcp_servers:
            idx = int(input("Server number to remove: ")) - 1
            if 0 <= idx < len(mcp_servers):
                mcp_servers.pop(idx)
        elif choice == "d" or not choice:
            break

    config["mcp_servers"] = mcp_servers


def main():
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

        # General and Security
        configure_general(config)
        configure_security(config)
        configure_mcp(config)

        print("\nSummary of changes:")
        # Masking secrets for summary
        display_config = {}
        for k, v in config.items():
            if isinstance(v, dict):
                display_config[k] = v.copy()
                if "api_key" in display_config[k]:
                    key = display_config[k]["api_key"]
                    display_config[k]["api_key"] = (
                        f"...{key[-4:]}" if len(key) > 8 else "***"
                    )
            else:
                display_config[k] = v

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
