"""Utility for initializing the configuration file."""

import pathlib
import sys

from llm_cli.consts import (
    CONFIG_DIR,
    CONFIG_FILE_PATH,
)

DEFAULTS_FILE = pathlib.Path(__file__).parent / "defaults.toml"


def init_config() -> None:
    """Initializes config.toml by copying defaults with commented values."""
    if CONFIG_FILE_PATH.exists():
        return

    if not DEFAULTS_FILE.exists():
        print(
            f"Error: Default configuration file not found at {DEFAULTS_FILE}",
            file=sys.stderr,
        )
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

    with DEFAULTS_FILE.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    commented_lines = []
    commented_lines.append("# llm-cli Configuration\n")
    sep = "# " + "=" * 77 + "\n"
    commented_lines.append(sep)
    commented_lines.append("# IMPORTANT: API Keys are NOT stored in this file.\n")
    commented_lines.append("# Set API Keys as env vars (e.g., in ~/.bashrc or .env):\n")
    commented_lines.append("#   export OPENAI_API_KEY='your-key-here'\n")
    commented_lines.append("#   export GEMINI_API_KEY='your-key-here'\n")
    commented_lines.append("#   export ANTHROPIC_API_KEY='your-key-here'\n")
    commented_lines.append("#\n")
    commented_lines.append(
        "# For Dual LLM Verification, ensure you have keys for TWO different providers.\n"
    )
    commented_lines.append(sep + "\n")
    commented_lines.append("# Other settings can be customized below.\n\n")

    for line in lines:
        stripped = line.strip()
        # Comment out lines that are not empty, not comments, and not section headers
        if stripped and not stripped.startswith("[") and not stripped.startswith("#"):
            commented_lines.append(f"# {line}")
        else:
            commented_lines.append(line)

    with CONFIG_FILE_PATH.open("w", encoding="utf-8") as f:
        f.writelines(commented_lines)

    # Note: We use basic print here as rich might not be fully initialized or
    # preferred during early startup.
    print(f"Initialized config at {CONFIG_FILE_PATH}", file=sys.stderr)
