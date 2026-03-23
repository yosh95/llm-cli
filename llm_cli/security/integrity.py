import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from llm_cli.consts import LLM_CLI_BASE_DIR

logger = logging.getLogger(__name__)


class IntegrityVerifier:
    """
    Verifies the integrity of critical application files and audit logs.
    Uses baseline hashes to detect unexpected modifications.
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
        """Save the current hashes as the manifest with PQC signature."""
        try:
            import base64

            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import PQCProvider

            self.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            # Create a canonical representation of the manifest for signing
            manifest_data = json.dumps(manifest, sort_keys=True, separators=(",", ":"))

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
            logger.info(f"Integrity manifest saved to {self.MANIFEST_PATH}")
        except Exception as e:
            logger.error(f"Failed to save integrity manifest: {e}")

    def _get_current_hashes(self) -> dict[str, str]:
        """Calculate hashes for all critical files."""
        current_manifest = {}
        for rel_path in self.CRITICAL_FILES:
            full_path = self.base_path / rel_path
            if full_path.exists():
                current_manifest[rel_path] = self._calculate_hash(full_path)
        return current_manifest

    def verify_audit_log(
        self, path: Path | None = None, pqc_verify_tail_lines: int = 50
    ) -> bool:
        """
        Verify the chained hashes in the audit log to detect modifications.
        This handles __audit_snapshot__ events by anchoring them to their
        respective archives.

        Hash-chain integrity is verified for ALL lines.
        PQC signature verification is limited to the last ``pqc_verify_tail_lines``
        entries to avoid O(N) post-quantum crypto overhead on every startup.
        Full PQC verification can be requested via ``llm-cli-security verify``.
        """
        from llm_cli.consts import AUDIT_LOG_PATH

        log_path = path or AUDIT_LOG_PATH
        if not log_path.exists():
            return True

        logger.info(f"Verifying audit log integrity: {log_path.name}")
        try:
            from llm_cli.security.pqc import PQCProvider

            # Pre-load all lines to know total count (files are small, ≤500 lines)
            with log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()

            total_lines = len(lines)
            pqc_start_idx = max(0, total_lines - pqc_verify_tail_lines)

            # Cache for PQC public keys keyed by variant to avoid repeated file I/O
            pqc_pub_cache: dict[str, bytes] = {}

            last_hash = "0" * 64
            for i, line in enumerate(lines):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.error(f"Malformed JSON at {log_path.name}:{i + 1}")
                    return False

                provided_hash = entry.get("hash")
                pqc_sig_b64 = entry.get("pqc_signature")
                variant = entry.get("pqc_algorithm", "ML-DSA-65")

                # 1. Recalculate hash for the current entry
                # (ignoring hash/sig fields)
                entry_copy = entry.copy()
                entry_copy.pop("hash", None)
                entry_copy.pop("pqc_signature", None)
                entry_copy.pop("pqc_algorithm", None)

                entry_str = json.dumps(entry_copy, sort_keys=True)
                actual_hash = hashlib.sha256(entry_str.encode()).hexdigest()

                if provided_hash != actual_hash:
                    logger.error(f"Hash mismatch at {log_path.name}:{i + 1}")
                    return False

                # 2. Verify PQC Signature only for the tail window
                #    Hash-chain continuity (step 3) guarantees integrity for
                #    all earlier entries; full PQC re-verification of every
                #    historical entry is O(N×PQC) and dominated startup time.
                if pqc_sig_b64 and i >= pqc_start_idx:
                    import base64

                    from llm_cli.security.identity import IdentityManager

                    if variant not in pqc_pub_cache:
                        pqc_pub_cache[variant] = (
                            IdentityManager._get_pqc_public_key_content(variant=variant)
                        )
                    pqc_pub = pqc_pub_cache[variant]
                    pqc_sig = base64.b64decode(pqc_sig_b64)
                    if not PQCProvider.verify(
                        actual_hash.encode(), pqc_sig, pqc_pub, variant=variant
                    ):
                        logger.error(f"Signature mismatch at {log_path.name}:{i + 1}")
                        return False

                # 3. Check Hash Chain
                is_snapshot = entry.get("event_type") == "__audit_snapshot__"

                if is_snapshot:
                    # Validate the anchor to the archive
                    archive_path_str = entry.get("args", {}).get("archive")
                    if archive_path_str:
                        archive_path = Path(archive_path_str)
                        # Verify the archive chain recursively
                        if not self.verify_audit_log(
                            archive_path,
                            pqc_verify_tail_lines=pqc_verify_tail_lines,
                        ):
                            return False

                        # Ensure this snapshot's prev_hash matches
                        # the archive's last hash
                        from llm_cli.security.audit import _get_last_log_hash

                        if entry.get("prev_hash") != _get_last_log_hash(archive_path):
                            logger.error(
                                f"Snapshot chain gap at {log_path.name}:{i + 1}"
                            )
                            return False

                    # Set the expected next prev_hash to what this
                    # snapshot anchors to
                    last_hash = entry.get("args", {}).get("snapshot_prev_hash")
                else:
                    if entry.get("prev_hash") != last_hash:
                        logger.error(f"Chain broken at {log_path.name}:{i + 1}")
                        return False
                    last_hash = actual_hash
            return True
        except Exception as e:
            logger.error(f"Failed to verify {log_path.name}: {e}")
            return False

    def verify(self, pqc_verify_tail_lines: int = 50) -> bool:
        """
        Verify integrity.
        Returns True if verified or missing (flexible for light users).
        Returns False on tampering.

        Args:
            pqc_verify_tail_lines: Number of audit-log tail lines to PQC-verify.
                Defaults to 50 for fast startup. Pass a large value (e.g. 10**9)
                for exhaustive verification (``llm-cli-security verify``).
        """
        logger.info("System Integrity: Verifying application files...")

        raw_manifest = self._load_manifest()
        if not raw_manifest:
            logger.warning(
                "🛡️  Integrity Lock is currently DISABLED (No manifest found)."
            )
            logger.warning(
                "Run 'llm-cli-security manifest' to enable system protection."
            )
            return self.verify_audit_log(pqc_verify_tail_lines=pqc_verify_tail_lines)

        trusted_manifest: dict[str, str] | None = None
        if "hashes" in raw_manifest:
            trusted_manifest = raw_manifest["hashes"]
            pqc_sig_b64 = raw_manifest.get("pqc_signature")

            if pqc_sig_b64:
                try:
                    import base64

                    from llm_cli.security.identity import IdentityManager
                    from llm_cli.security.pqc import PQCProvider

                    manifest_data = json.dumps(
                        trusted_manifest, sort_keys=True, separators=(",", ":")
                    )
                    pqc_pub = IdentityManager._get_pqc_public_key_content()
                    signature = base64.b64decode(pqc_sig_b64)

                    if not PQCProvider.verify(
                        manifest_data.encode(), signature, pqc_pub
                    ):
                        logger.error("Integrity Failure: Manifest signature mismatch.")
                        logger.error(
                            "Try running 'llm-cli-security manifest' to re-sign."
                        )
                        return False
                except Exception as e:
                    logger.error(f"PQC verification error: {e}")
                    logger.error(
                        "Run 'llm-cli-security keygen' or "
                        "'llm-cli-security manifest' to fix."
                    )
                    return False
        else:
            trusted_manifest = raw_manifest

        current_manifest = self._get_current_hashes()
        all_ok = True

        for rel_path, trusted_hash in trusted_manifest.items():
            current_hash = current_manifest.get(rel_path)
            if current_hash is None:
                logger.error(f"Integrity Failure: Missing file {rel_path}")
                all_ok = False
            elif current_hash != trusted_hash:
                logger.error(f"Integrity Failure: Hash mismatch for {rel_path}")
                all_ok = False

        if not all_ok:
            logger.error(
                "Run 'llm-cli-security manifest' to update the integrity baseline "
                "if these changes are intended."
            )

        if not self.verify_audit_log(pqc_verify_tail_lines=pqc_verify_tail_lines):
            all_ok = False

        return all_ok

    def rebuild_manifest(self) -> bool:
        """Force rebuild of the integrity manifest (Admin Action)."""
        logger.info("🛡️  Establishing new integrity baseline...")
        try:
            from llm_cli.security.identity import IdentityManager

            IdentityManager._ensure_keys(force=True)
        except Exception:
            return False

        current_hashes = self._get_current_hashes()
        self._save_manifest(current_hashes)
        return True

    def generate_attestation_token(self) -> dict:
        """Generates a PQC-signed attestation of system integrity."""
        import base64
        import time

        from llm_cli.security.identity import IdentityManager
        from llm_cli.security.pqc import PQCProvider

        has_manifest = self.MANIFEST_PATH.exists()
        # strictly check if manifest exists
        is_ok = self.verify() if has_manifest else False

        state = {
            "ts": time.time(),
            "integrity_ok": is_ok,
            "locked": has_manifest,
            "workload": IdentityManager.get_local_identity(),
        }
        message = json.dumps(state, sort_keys=True)
        pqc_priv = IdentityManager._get_pqc_private_key_content()
        signature = PQCProvider.sign(message.encode(), pqc_priv)

        return {
            "evidence": state,
            "pqc_signature": base64.b64encode(signature).decode(),
            "pqc_algorithm": PQCProvider.ALGORITHM_NAME,
        }


def verify_installation() -> None:
    """Helper function to run verification from current working directory."""
    root_path = Path(__file__).resolve().parent.parent.parent
    verifier = IntegrityVerifier(root_path)
    if not verifier.verify():
        logger.critical("Integrity check failed. Aborting startup.")
        logger.error(
            "Hint: If you have modified the source code or updated dependencies, "
            "you must re-generate the integrity manifest by running: "
            "llm-cli-security manifest"
        )
        sys.exit(1)
