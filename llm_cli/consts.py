from pathlib import Path

# Use a unified directory for all llm_cli data
LLM_CLI_BASE_DIR = Path.home() / ".llm_cli"

CONFIG_DIR = LLM_CLI_BASE_DIR
LOG_DIR = LLM_CLI_BASE_DIR / "logs"
KEY_DIR = LLM_CLI_BASE_DIR / "keys"

CONFIG_FILE_PATH = CONFIG_DIR / "config.toml"
AUDIT_LOG_PATH = LOG_DIR / "audit.jsonl"
SECURITY_LOG_PATH = LOG_DIR / "security.log"
HISTORY_LOG_PATH = LOG_DIR / "history.log"
CHAT_LOG_PATH = LOG_DIR / "chat.log"
TRAINING_METRICS_LOG_PATH = LOG_DIR / "training_metrics.jsonl"

UNKNOWN_TOOL_ID = "unknown"

# Tool output limits
MAX_OUTPUT_LINES = 500
MAX_OUTPUT_CHARS = 30000
