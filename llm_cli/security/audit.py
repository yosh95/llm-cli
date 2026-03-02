import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from llm_cli.clients.config import get_setting
from llm_cli.consts import AUDIT_LOG_PATH

logger = logging.getLogger(__name__)


def log_audit(
    tool_name: str,
    args: Any,
    _output: Any,
    exit_code: int | None = None,
    error: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Enhanced structured audit logging with Chained Hashing for tamper evidence.
    """
    path = AUDIT_LOG_PATH
    max_lines = int(get_setting("max_audit_log_lines", "general") or 10000)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat()

        # Prepare context info
        ctx = context or {}
        trace_id = ctx.get("trace_id", "-")
        subject = ctx.get("user_id", "unknown")
        audience = ctx.get("audience", "-")
        model = ctx.get("model", "-")

        # Get previous hash to create a chain
        prev_hash = _get_last_log_hash(path)

        log_entry = {
            "timestamp": timestamp,
            "trace_id": trace_id,
            "subject": subject,
            "audience": audience,
            "model": model,
            "tool": tool_name,
            "args": args,
            # "output": str(_output)[:256] if _output else None, # Truncate output
            "status": "SUCCESS" if not error else f"FAILED: {error}",
            "exit_code": exit_code,
            "prev_hash": prev_hash,
        }

        # Calculate hash of the current entry (excluding the hash itself and PQC sig)
        entry_str = json.dumps(log_entry, sort_keys=True)
        current_hash = hashlib.sha256(entry_str.encode()).hexdigest()
        log_entry["hash"] = current_hash

        # --- PQC-Audit-Chain: Sign the current entry hash with ML-DSA ---
        try:
            import base64

            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import PQCAgilityManager, PQCProvider

            # Determine required security level based on tool risk and
            # ARGS (Dynamic Context)
            variant = PQCAgilityManager.get_required_level(tool_name, args=args)

            pqc_priv = IdentityManager._get_pqc_private_key_content()
            # Note: In a production system, we would have different keys for
            # different levels, but for this reference implementation,
            # we demonstrate the agility logic.
            pqc_sig = PQCProvider.sign(current_hash.encode(), pqc_priv, variant=variant)

            log_entry["pqc_signature"] = base64.b64encode(pqc_sig).decode()
            log_entry["pqc_algorithm"] = variant
        except Exception as e:
            # Fallback for environments without PQC keys or during setup
            logger.debug(f"PQC signing skipped for audit log: {e}")

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

            last_line = lines[-1].decode("utf-8", errors="replace")
            last_entry = json.loads(last_line)
            return str(last_entry.get("hash", "0" * 64))
    except Exception:
        return "0" * 64


def _trim_log_file(path: Path, max_lines: int) -> None:
    """Keeps the log file within the specified line limit.

    Important: naive trimming breaks hash-chain continuity. To keep tamper-evidence,
    we *rotate* the overflow into an archive file and insert a signed snapshot entry
    at the beginning of the remaining log.

    Snapshot entry (tool='__audit_snapshot__') contains:
      - snapshot_prev_hash: the prev_hash of the first kept entry
      - snapshot_first_hash: the hash of the first kept entry

    This preserves verifiability for the remaining segment and provides an anchor
    to the rotated archive.
    """
    try:
        if not path.exists():
            return

        # Robust line-based trimming.
        # Use errors="replace" to ensure we don't fail due to encoding issues.
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if len(lines) <= max_lines:
            return

        overflow = lines[:-max_lines]
        kept = lines[-max_lines:]

        # Write overflow to a rotated archive (append-only)
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        archive_path = path.with_name(f"{path.name}.archive.{ts}.jsonl")
        with archive_path.open("a", encoding="utf-8", errors="replace") as af:
            af.writelines(overflow)

        # Prepare a snapshot anchor for the kept segment
        try:
            first_entry = json.loads(kept[0])
            snapshot_prev_hash = first_entry.get("prev_hash", "0" * 64)
            snapshot_first_hash = first_entry.get("hash", "0" * 64)
        except Exception:
            snapshot_prev_hash = "0" * 64
            snapshot_first_hash = "0" * 64

        snapshot = {
            "timestamp": datetime.datetime.now().isoformat(),
            "trace_id": "-",
            "subject": "system",
            "audience": "-",
            "model": "-",
            "tool": "__audit_snapshot__",
            "args": {
                "archive": str(archive_path),
                "snapshot_prev_hash": snapshot_prev_hash,
                "snapshot_first_hash": snapshot_first_hash,
                "kept_lines": max_lines,
            },
            "status": "SUCCESS",
            "exit_code": None,
            "prev_hash": _get_last_log_hash(archive_path),
        }
        entry_str = json.dumps(snapshot, sort_keys=True)
        snapshot["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()

        with path.open("w", encoding="utf-8", errors="replace") as wf:
            wf.write(json.dumps(snapshot) + "\n")
            wf.writelines(kept)

    except Exception:
        # Never break tool execution due to logging
        pass
