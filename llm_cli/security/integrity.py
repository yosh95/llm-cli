import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from llm_cli.consts import LLM_CLI_BASE_DIR

logger = logging.getLogger(__name__)


class IntegrityVerifier:
    """
    Implements a Root of Trust mechanism by verifying the integrity
    of critical application files and audit logs at startup.
    Uses TOFU (Trust On First Use) to establish a baseline.
    """

    # Critical files to monitor for tampering
    CRITICAL_FILES = [
        "llm_cli/apps/mcp_server.py",
        "llm_cli/security/identity.py",
        "llm_cli/security/policy.py",
        "llm_cli/security/audit.py",
        "llm_cli/security/integrity.py",
        "pyproject.toml",
    ]

    MANIFEST_PATH = LLM_CLI_BASE_DIR / "integrity_manifest.json"

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with file_path.open("rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
            return "MISSING"

    def _load_manifest(self) -> dict[str, Any] | None:
        """Load the trusted hash manifest."""
        if not self.MANIFEST_PATH.exists():
            return None
        try:
            with self.MANIFEST_PATH.open("r", encoding="utf-8") as f:
                from typing import cast

                return cast(dict[str, Any], json.load(f))
        except Exception as e:
            logger.error(f"Failed to load integrity manifest: {e}")
            return None

    def _save_manifest(self, manifest: dict[str, str]) -> None:
        """Save the current hashes as the trusted manifest with PQC signature."""
        try:
            import base64

            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import PQCProvider

            self.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

            # Create a canonical representation of the manifest for signing
            manifest_data = json.dumps(
                manifest, indent=None, sort_keys=True, separators=(",", ":")
            )

            # Sign the manifest with PQC key
            pqc_priv = IdentityManager._get_pqc_private_key_content()
            signature = PQCProvider.sign(manifest_data.encode(), pqc_priv)

            output = {
                "hashes": manifest,
                "pqc_signature": base64.b64encode(signature).decode(),
                "pqc_algorithm": PQCProvider.ALGORITHM_NAME,
            }

            with self.MANIFEST_PATH.open("w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, sort_keys=True)
            logger.info(
                f"🛡️  PQC-Signed Integrity manifest saved to {self.MANIFEST_PATH}"
            )
        except Exception as e:
            logger.error(f"Failed to save integrity manifest: {e}")

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
        """Verify integrity of critical files and audit log (with PQC signature)."""
        logger.info("🛡️  Root of Trust: Verifying system integrity (PQC-enabled)...")

        raw_manifest = self._load_manifest()
        trusted_manifest: dict[str, str] | None = None

        if raw_manifest:
            # Check if it's the new format with PQC signature
            if "hashes" in raw_manifest:
                trusted_manifest = raw_manifest["hashes"]
                pqc_sig_b64 = raw_manifest.get("pqc_signature")

                # Verify PQC Signature of the manifest itself
                if pqc_sig_b64:
                    try:
                        import base64

                        from llm_cli.security.identity import IdentityManager
                        from llm_cli.security.pqc import PQCProvider

                        # Recreate canonical data for verification
                        manifest_data = json.dumps(
                            trusted_manifest,
                            indent=None,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        pqc_pub = IdentityManager._get_pqc_public_key_content()
                        signature = base64.b64decode(pqc_sig_b64)

                        if not PQCProvider.verify(
                            manifest_data.encode(), signature, pqc_pub
                        ):
                            logger.error(
                                "❌ Integrity Violated: Manifest PQC Mismatch!"
                            )
                            return False
                        logger.debug("✅ Manifest PQC Signature verified.")
                    except Exception as e:
                        logger.error(f"PQC verification error: {e}")
                        return False
            else:
                # Legacy format (migration)
                trusted_manifest = raw_manifest

        current_manifest = {}
        all_ok = True

        # Calculate current hashes
        for rel_path in self.CRITICAL_FILES:
            full_path = self.base_path / rel_path
            # Check existence
            if not full_path.exists():
                # It might be normal if running from installed package
                # and source files are not there in same structure
                # But assuming standard install where files exist.
                # If file is missing, and it was in manifest, that's an error.
                if trusted_manifest and rel_path in trusted_manifest:
                    logger.error(
                        f"❌ Integrity Violated: Critical file missing: {rel_path}"
                    )
                    all_ok = False
                continue

            file_hash = self._calculate_hash(full_path)
            current_manifest[rel_path] = file_hash

        # If no manifest exists, establish trust (TOFU)
        if trusted_manifest is None:
            # Default to strict mode (1) unless explicitly disabled (0)
            if os.getenv("LLM_CLI_STRICT_SECURITY", "1") == "1":
                logger.critical(
                    "🚨 STRICT MODE: Integrity manifest missing. "
                    "In strict mode, TOFU is disabled. "
                    "Please generate it using 'llm-cli-security manifest'."
                )
                return False

            logger.warning(
                "⚠️  No integrity manifest found. Establishing trust baseline (TOFU)..."
            )
            self._save_manifest(current_manifest)
            trusted_manifest = current_manifest

        # Compare against trusted manifest
        for rel_path, trusted_hash in trusted_manifest.items():
            current_hash = current_manifest.get(rel_path)

            if current_hash is None:
                logger.error(
                    f"❌ Integrity Violated: Critical file missing: {rel_path}"
                )
                all_ok = False
                continue

            if current_hash != trusted_hash:
                logger.error(f"❌ Integrity Violated: Hash mismatch for {rel_path}")
                logger.error(f"   Expected: {trusted_hash}")
                logger.error(f"   Actual:   {current_hash}")
                all_ok = False
            else:
                logger.debug(f"✅ Verified: {rel_path}")

        # Also verify the audit log chain
        if not self.verify_audit_log():
            all_ok = False

        if all_ok:
            logger.info("✅ System Integrity Verified.")

        return all_ok

    def rebuild_manifest(self) -> bool:
        """
        Force rebuild of the integrity manifest.
        This establishes a new root of trust based on the current system state.
        Use with caution.
        """
        logger.warning("🛡️  Rebuilding integrity trust anchor (TOFU)...")
        if self.MANIFEST_PATH.exists():
            try:
                self.MANIFEST_PATH.unlink()
                logger.info("Deleted existing manifest.")
            except Exception as e:
                logger.error(f"Failed to delete manifest: {e}")
                return False

        # Calling verify() will trigger TOFU logic since manifest is gone
        return self.verify()


def verify_installation() -> None:
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
