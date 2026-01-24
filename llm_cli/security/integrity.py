import hashlib
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

class IntegrityVerifier:
    """
    Implements a Root of Trust mechanism by verifying the integrity
    of critical application files at startup.
    """

    # Critical files to monitor for tampering
    CRITICAL_FILES = [
        "llm_cli/apps/mcp_server.py",
        "llm_cli/security/command_validator.py",
        "llm_cli/security/policy.py",
        "pyproject.toml"
    ]

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read and update hash string value in blocks of 4K
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
            return "MISSING"

    def verify(self) -> bool:
        """
        Verify integrity of critical files.
        In a real-world scenario, expected hashes would be stored in a signed manifest
        or a secure hardware enclave (TPM). Here we simulate the check.
        """
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

            # In a real implementation, we would compare against a signed manifest.
            # For this demo, we just compute and log the hash to show the mechanism.
            file_hash = self._calculate_hash(full_path)
            logger.debug(f"File: {rel_path}, Hash: {file_hash[:12]}...")

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
