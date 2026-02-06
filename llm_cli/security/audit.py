import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from llm_cli.clients.config import get_setting

logger = logging.getLogger(__name__)


def log_audit(
    tool_name: str,
    args: Any,
    output: Any,
    exit_code: Optional[int] = None,
    error: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
):
    """
    Enhanced structured audit logging with Chained Hashing for tamper evidence.
    """
    audit_log_path = get_setting("LLM_AUDIT_LOG", "general")
    if not audit_log_path:
        from llm_cli.consts import AUDIT_LOG_PATH

        audit_log_path = str(AUDIT_LOG_PATH)

    path = Path(audit_log_path).expanduser()
    max_lines = int(get_setting("max_audit_log_lines", "general") or 10000)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat()

        # Prepare context info
        ctx = context or {}
        trace_id = ctx.get("trace_id", "-")
        subject = ctx.get("user_id", "unknown")
        audience = ctx.get("audience", "-")

        # Get previous hash to create a chain
        prev_hash = _get_last_log_hash(path)

        log_entry = {
            "timestamp": timestamp,
            "trace_id": trace_id,
            "subject": subject,
            "audience": audience,
            "tool": tool_name,
            "args": args,
            "status": "SUCCESS" if not error else f"FAILED: {error}",
            "exit_code": exit_code,
            "prev_hash": prev_hash,
        }

        # Calculate hash of the current entry (excluding the hash itself)
        entry_str = json.dumps(log_entry, sort_keys=True)
        current_hash = hashlib.sha256(entry_str.encode()).hexdigest()
        log_entry["hash"] = current_hash

        # Write as JSONL
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

        _trim_log_file(path, max_lines)

    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


def _get_last_log_hash(path: Path) -> str:
    """Read the last line of the log to get the previous hash."""
    if not path.exists() or path.stat().st_size == 0:
        return "0" * 64  # Genesis hash

    try:
        with path.open("rb") as f:
            f.seek(0, 2)  # Go to end
            pos = f.tell()
            buffer = b""
            # Read backwards to find the last newline
            while pos > 0 and buffer.count(b"\n") < 2:
                seek_pos = max(0, pos - 1024)
                f.seek(seek_pos)
                buffer = f.read(pos - seek_pos) + buffer
                pos = seek_pos

            lines = buffer.splitlines()
            if not lines:
                return "0" * 64

            last_line = lines[-1].decode("utf-8")
            last_entry = json.loads(last_line)
            return str(last_entry.get("hash", "0" * 64))
    except Exception:
        return "0" * 64


def _trim_log_file(path: Path, max_lines: int):
    """Keeps the log file within the specified line limit while preserving the chain."""
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            # When trimming, we break the hash chain from the beginning,
            # but preserve it for the remaining entries.
            # In a production system, we would archive the old logs.
            with path.open("w", encoding="utf-8") as f:
                f.writelines(lines[-max_lines:])
    except Exception:
        pass
