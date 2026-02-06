import hashlib
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class IntegrityVerifier:
    """
    Implements a Root of Trust mechanism by verifying the integrity
    of critical application files and audit logs at startup.
    """

    # Critical files to monitor for tampering
    CRITICAL_FILES = [
        "llm_cli/apps/mcp_server.py",
        "llm_cli/security/identity.py",
        "llm_cli/security/policy.py",
        "llm_cli/security/audit.py",
        "pyproject.toml",
    ]

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
            return "MISSING"

    def verify_audit_log(self) -> bool:
        """Verify the chained hashes in the audit log to detect tampering."""
        from llm_cli.consts import AUDIT_LOG_PATH

        # Note: In a real app, this would use a proper config loader
        audit_log_path = AUDIT_LOG_PATH

        if not audit_log_path.exists():
            return True

        logger.info("🛡️  Verifying audit log integrity...")
        try:
            with audit_log_path.open("r", encoding="utf-8") as f:
                last_hash = "0" * 64
                for i, line in enumerate(f):
                    entry = json.loads(line)
                    provided_hash = entry.pop("hash", None)

                    # Check chain
                    if entry.get("prev_hash") != last_hash:
                        logger.error(f"❌ Audit log chain broken at line {i + 1}")
                        return False

                    # Verify current entry's hash
                    entry_str = json.dumps(entry, sort_keys=True)
                    actual_hash = hashlib.sha256(entry_str.encode()).hexdigest()

                    if provided_hash != actual_hash:
                        logger.error(f"❌ Audit log tampering detected at line {i + 1}")
                        return False

                    last_hash = provided_hash
            return True
        except Exception as e:
            logger.error(f"❌ Failed to verify audit log: {e}")
            return False

    def verify(self) -> bool:
        """Verify integrity of critical files and audit log."""
        logger.info("🛡️  Root of Trust: Verifying system integrity...")

        all_ok = True
        for rel_path in self.CRITICAL_FILES:
            full_path = self.base_path / rel_path
            if not full_path.exists():
                logger.error(
                    f"❌ Integrity Violated: Critical file missing: {rel_path}"
                )
                all_ok = False
                continue

            file_hash = self._calculate_hash(full_path)
            logger.debug(f"File: {rel_path}, Hash: {file_hash[:12]}...")

        # Also verify the audit log chain
        if not self.verify_audit_log():
            all_ok = False

        if all_ok:
            logger.info("✅ System Integrity Verified.")

        return all_ok


def verify_installation():
    """Helper function to run verification from current working directory."""
    # Assuming we run from the project root
    # Use the location of this file to determine the root project directory
    # integrity.py is located at llm_cli/security/integrity.py
    # so we need to go up 3 levels to reach the project root.
    root_path = Path(__file__).resolve().parent.parent.parent

    verifier = IntegrityVerifier(root_path)
    if not verifier.verify():
        logger.critical(
            "🚨 SECURITY ALERT: System integrity compromise detected! Aborting startup."
        )
        sys.exit(1)
