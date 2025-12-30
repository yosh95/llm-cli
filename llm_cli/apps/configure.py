#!/usr/bin/env python3

import tomli_w
import tomllib

from pathlib import Path

# Define the path for the configuration directory and file
CONFIG_DIR = Path.home() / ".config" / "llm_cli"
CONFIG_FILE = CONFIG_DIR / "config.toml"

GEMINI_MODEL_DEFAULT = "gemini-3-flash-preview"
OPENAI_MODEL_DEFAULT = "gpt-5.2"
CLAUDE_MODEL_DEFAULT = "claude-opus-4-5-20251101"
GROK_MODEL_DEFAULT = "grok-4-1-fast-reasoning"


def load_config():
    """Loads the configuration file and returns it as a dictionary.
    Returns an empty dictionary if the file does not exist.
    """
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def save_config(config):
    """Saves the configuration dictionary to the file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.touch(mode=0o600, exist_ok=True)
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(config, f)


def prompt_for_setting(prompt_text, current_value=None):
    """Displays a prompt with the current value and asks for a new one."""
    if current_value:
        # Show only the last 4 characters of the key for security
        prompt = f"{prompt_text} [current: ...{current_value[-4:]}]: "
    else:
        prompt = f"{prompt_text} [current: None]: "

    value = input(prompt)
    # If the user just presses Enter, keep the current value
    return value if value else current_value


def prompt_for_general_setting(prompt_text, current_value=None):
    """Displays a prompt for a general setting (like a file path)."""
    if current_value:
        prompt = f"{prompt_text} [current: {current_value}]: "
    else:
        prompt = f"{prompt_text} [current: None]: "

    value = input(prompt)
    # If the user just presses Enter, keep the current value
    return value.strip() if value.strip() else current_value


def main():
    """Interactively configures settings for the application."""
    print("Configuring settings for llm_cli.")
    print(f"Configuration will be saved to: {CONFIG_FILE}\n")

    config = load_config()

    # Ensure top-level sections exist
    config.setdefault('google', {})
    config.setdefault('openai', {})
    config.setdefault('anthropic', {})
    config.setdefault('xai', {})
    config.setdefault('general', {})
    config['google'].setdefault('models', {})
    config['openai'].setdefault('models', {})
    config['anthropic'].setdefault('models', {})
    config['xai'].setdefault('models', {})

    # --- Google Services Configuration ---
    config['google']['api_key'] = prompt_for_setting(
        "Google API Key", config['google'].get('api_key', '')
    )
    config['google']['cse_id'] = prompt_for_setting(
        "Google Custom Search Engine ID", config['google'].get('cse_id')
    )

    # --- OpenAI Services Configuration ---
    config['openai']['api_key'] = prompt_for_setting(
        "OpenAI API Key", config['openai'].get('api_key', '')
    )

    # --- Anthropic Services Configuration ---
    print("\n--- Anthropic (Claude) Configuration ---")
    config['anthropic']['api_key'] = prompt_for_setting(
        "Anthropic API Key", config['anthropic'].get('api_key', '')
    )

    # --- xAI (Grok) Configuration ---
    print("\n--- xAI (Grok) Configuration ---")
    config['xai']['api_key'] = prompt_for_setting(
        "xAI API Key", config['xai'].get('api_key', '')
    )

    # --- General Settings ---
    print("\n--- Optional: General Settings ---")
    print("Specify paths for history and log files. "
          "Press Enter to keep the current value.")

    # Define default paths using XDG Base Directory specification
    home_dir = Path.home()
    default_history_path = str(
        home_dir / '.local' / 'state' / 'llm_cli' / 'history.txt')
    default_chat_log_path = str(
        home_dir / '.local' / 'share' / 'llm_cli' / 'chat.log')
    default_debug_log_path = str(home_dir / '.cache' / 'llm_cli' / 'debug.log')

    config['general']['LLM_PROMPT_HISTORY'] = prompt_for_general_setting(
        "Prompt history file path",
        config['general'].get('LLM_PROMPT_HISTORY',
                              default_history_path)
    )
    config['general']['LLM_CHAT_LOG'] = prompt_for_general_setting(
        "Chat log file path",
        config['general'].get('LLM_CHAT_LOG',
                              default_chat_log_path)
    )
    config['general']['LLM_REQUEST_DEBUG_LOG'] = prompt_for_general_setting(
        "Request debug log file path",
        config['general'].get('LLM_REQUEST_DEBUG_LOG',
                              default_debug_log_path)
    )

    print("\n--- Log Retention Settings ---")
    max_prompt_history = prompt_for_general_setting(
        "Max prompt history lines to keep (0 for unlimited)",
        str(config['general'].get('max_prompt_history_lines', 1000))
    )
    try:
        config['general']['max_prompt_history_lines'] = int(max_prompt_history)
    except (ValueError, TypeError):
        config['general']['max_prompt_history_lines'] = 1000

    max_chat_log = prompt_for_general_setting(
        "Max chat log lines to keep (0 for unlimited)",
        str(config['general'].get('max_chat_log_lines', 10000))
    )
    try:
        config['general']['max_chat_log_lines'] = int(max_chat_log)
    except (ValueError, TypeError):
        config['general']['max_chat_log_lines'] = 10000

    # --- Model Alias Configuration ---
    print("\n--- Optional: Default Model Aliases ---")
    print("You can set default models here. Press Enter to keep "
          "the current value.")

    # gemini
    current_gemini_default = config['google']['models'].get(
            'default', GEMINI_MODEL_DEFAULT)
    gemini_default_prompt = "Default Gemini Model [current: " + \
        f"{current_gemini_default}]: "
    gemini_default = input(gemini_default_prompt)
    config['google']['models']['default'] = gemini_default \
        if gemini_default else current_gemini_default

    # openai
    current_openai_default = config['openai']['models'].get(
        'default', OPENAI_MODEL_DEFAULT)
    openai_default_prompt = "Default OpenAI Model [current: " + \
        f"{current_openai_default}]: "
    openai_default = input(openai_default_prompt)
    config['openai']['models']['default'] = openai_default \
        if openai_default else current_openai_default

    # anthropic (claude)
    current_claude_default = config['anthropic']['models'].get(
        'default', CLAUDE_MODEL_DEFAULT)
    claude_default_prompt = "Default Claude Model [current: " + \
        f"{current_claude_default}]: "
    claude_default = input(claude_default_prompt)
    config['anthropic']['models']['default'] = claude_default \
        if claude_default else current_claude_default

    # xai (grok)
    current_grok_default = config['xai']['models'].get(
        'default', GROK_MODEL_DEFAULT)
    grok_default_prompt = "Default Grok Model [current: " + \
        f"{current_grok_default}]: "
    grok_default = input(grok_default_prompt)
    config['xai']['models']['default'] = grok_default \
        if grok_default else current_grok_default

    save_config(config)

    print(f"\nConfiguration saved successfully to {CONFIG_FILE}")


if __name__ == '__main__':
    main()
