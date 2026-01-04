# llm_cli/security/audit.py

import datetime
from pathlib import Path
from typing import Any, Optional

from llm_cli.clients.config import get_setting


def log_audit(
    tool_name: str,
    args: Any,
    output: Any,
    exit_code: Optional[int] = None,
    error: Optional[str] = None,
):
    """
    Logs tool execution (especially command execution) for auditing purposes.
    Maintains a line limit by trimming the log file.
    """
    audit_log_path = get_setting("LLM_AUDIT_LOG", "general")
    if not audit_log_path:
        audit_log_path = "~/.local/state/llm_cli/audit.log"

    path = Path(audit_log_path).expanduser()
    max_lines = int(get_setting("max_audit_log_lines", "general") or 5000)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status = "SUCCESS"
        if exit_code is not None:
            status = f"Exit Code: {exit_code}"
        if error:
            status = f"FAILED ({error})"

        # Format arguments and output safely
        def _fmt(val):
            s = str(val)
            if len(s) > 2000:
                return s[:2000] + "\n... [Truncated]"
            return s

        log_entry = (
            f"--- {timestamp} ---\n"
            f"Tool:   {tool_name}\n"
            f"Args:   {_fmt(args)}\n"
            f"Status: {status}\n"
            f"Result:\n{_fmt(output)}\n"
            f"{'=' * 40}\n\n"
        )

        with path.open("a", encoding="utf-8") as f:
            f.write(log_entry)

        _trim_log_file(path, max_lines)

    except Exception:
        # Avoid crashing the application due to logging errors
        pass


def _trim_log_file(path: Path, max_lines: int):
    """Keeps the log file within the specified line limit."""
    try:
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > max_lines:
            path.write_text("".join(lines[-max_lines:]), encoding="utf-8")
    except Exception:
        pass
