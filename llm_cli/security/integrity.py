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

    # Patterns for critical files to monitor for tampering
    CRITICAL_PATTERNS = [
        "llm_cli/**/*.py",
        "llm_cli/**/*.toml",
        "pyproject.toml",
        "Makefile",
        "pytest.ini",
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
            logger.error(f"[ERROR] Failed to load integrity manifest: {e}")
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
            logger.info(f"[OK] Integrity manifest saved to {self.MANIFEST_PATH}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to save integrity manifest: {e}")

    def _get_current_hashes(self) -> dict[str, str]:
        """Calculate hashes for all critical files found via patterns."""
        current_manifest = {}
        found_files = set()

        for pattern in self.CRITICAL_PATTERNS:
            # Recursively find files matching the pattern
            for p in self.base_path.glob(pattern):
                if p.is_file() and "__pycache__" not in p.parts:
                    rel_path = str(p.relative_to(self.base_path))
                    found_files.add(rel_path)

        for rel_path in sorted(found_files):
            current_manifest[rel_path] = self._calculate_hash(self.base_path / rel_path)

        return current_manifest

    def verify_audit_log(self, path: Path | None = None, pqc_verify_tail_lines: int = 50) -> bool:
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

        logger.info(f"[INFO] Verifying audit log integrity: {log_path.name}")
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
                    logger.error(f"[ERROR] Malformed JSON at {log_path.name}:{i + 1}")
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
                    logger.error(f"[ERROR] Hash mismatch at {log_path.name}:{i + 1}")
                    return False

                # 2. Verify PQC Signature only for the tail window
                #    Hash-chain continuity (step 3) guarantees integrity for
                #    all earlier entries; full PQC re-verification of every
                #    historical entry is O(N×PQC) and dominated startup time.
                if pqc_sig_b64 and i >= pqc_start_idx:
                    import base64

                    from llm_cli.security.identity import IdentityManager

                    if variant not in pqc_pub_cache:
                        pqc_pub_cache[variant] = IdentityManager._get_pqc_public_key_content(
                            variant=variant
                        )
                    pqc_pub = pqc_pub_cache[variant]
                    pqc_sig = base64.b64decode(pqc_sig_b64)
                    if not PQCProvider.verify(
                        actual_hash.encode(), pqc_sig, pqc_pub, variant=variant
                    ):
                        logger.error(f"[ERROR] Signature mismatch at {log_path.name}:{i + 1}")
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
                            logger.error(f"[ERROR] Snapshot chain gap at {log_path.name}:{i + 1}")
                            return False

                    # Set the expected next prev_hash to what this
                    # snapshot anchors to
                    last_hash = entry.get("args", {}).get("snapshot_prev_hash")
                else:
                    if entry.get("prev_hash") != last_hash:
                        logger.error(f"[ERROR] Chain broken at {log_path.name}:{i + 1}")
                        return False
                    last_hash = actual_hash
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to verify {log_path.name}: {e}")
            return False

    def verify(self, pqc_verify_tail_lines: int = 50) -> bool:
        """
        Verify integrity.
        Returns True if verified. Returns False on tampering or missing manifest.

        Args:
            pqc_verify_tail_lines: Number of audit-log tail lines to PQC-verify.
                Defaults to 50 for fast startup. Pass a value like 10**9
                for exhaustive verification (``llm-cli-security verify``).
        """
        logger.info("[INFO] System Integrity: Verifying application files...")

        raw_manifest = self._load_manifest()
        if not raw_manifest:
            logger.error("[ERROR] Integrity Failure: Manifest not found.")
            return False

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

                    if not PQCProvider.verify(manifest_data.encode(), signature, pqc_pub):
                        logger.error("[ERROR] Integrity Failure: Manifest signature mismatch.")
                        logger.error("Try running 'llm-cli-security manifest' to re-sign.")
                        return False
                except Exception as e:
                    logger.error(f"[ERROR] PQC verification error: {e}")
                    logger.error(
                        "Run 'llm-cli-security keygen' or 'llm-cli-security manifest' to fix."
                    )
                    return False
        else:
            trusted_manifest = raw_manifest

        current_manifest = self._get_current_hashes()
        files_ok = True

        # Check for modifications or missing files
        for rel_path, trusted_hash in trusted_manifest.items():
            current_hash = current_manifest.get(rel_path)
            if current_hash is None:
                logger.error(f"[ERROR] Integrity Failure: Missing file {rel_path}")
                files_ok = False
            elif current_hash != trusted_hash:
                logger.error(f"[ERROR] Integrity Failure: Hash mismatch for {rel_path}")
                files_ok = False

        # Check for unauthorized new files
        for rel_path in current_manifest:
            if rel_path not in trusted_manifest:
                logger.error(f"[ERROR] Integrity Failure: Unauthorized file: {rel_path}")
                files_ok = False

        if not files_ok:
            logger.error(
                "Run 'llm-cli-security manifest' to update the integrity baseline "
                "if these changes are intended."
            )

        # Audit log check
        audit_ok = self.verify_audit_log(pqc_verify_tail_lines=pqc_verify_tail_lines)
        if not audit_ok:
            logger.error("[ERROR] Integrity Failure: Audit log verification failed.")
            logger.error(
                "This may be caused by a key change or manual log tampering. "
                "If you are developing and changed your identity keys, you may need "
                "to clear the audit log (audit.jsonl)."
            )

        return files_ok and audit_ok

    def rebuild_manifest(self) -> bool:
        """Force rebuild of the integrity manifest (Admin Action)."""
        logger.info("[INFO] Establishing new integrity baseline...")
        try:
            from llm_cli.security.identity import IdentityManager

            # Ensure keys exist, but don't force REGENERATION of existing keys.
            # Identity keys are separate from the integrity manifest baseline.
            IdentityManager._ensure_keys(force=False)
        except Exception:
            return False

        current_hashes = self._get_current_hashes()
        self._save_manifest(current_hashes)

        # Also check the audit log and warn the user if it's currently broken.
        if not self.verify_audit_log():
            logger.warning(
                "[bold yellow]WARNING[/bold yellow] [WARNING] The audit log has a "
                "signature mismatch. The manifest was updated successfully, but "
                "the system will still fail the integrity check on startup until "
                "the audit log is fixed."
            )
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
    import os

    from llm_cli.clients.config import config_manager

    root_path = Path(__file__).resolve().parent.parent.parent
    verifier = IntegrityVerifier(root_path)

    # 1. Handle missing manifest (First Run)
    if not verifier.MANIFEST_PATH.exists():
        try:
            from rich.panel import Panel

            from llm_cli.ui import console

            console.print(
                Panel(
                    "[bold cyan]System Integrity baseline established.[/bold cyan]\n"
                    "A cryptographic manifest of all critical application files has "
                    "been generated.\n\n"
                    "Any future unauthorized modifications to the source code or "
                    "audit logs will be detected on startup.",
                    title="[bold yellow]Security Initialization[/bold yellow]",
                    border_style="cyan",
                )
            )
        except Exception:
            logger.info("Establishing initial integrity manifest baseline...")

        if not verifier.rebuild_manifest():
            logger.error("Failed to establish initial integrity manifest.")
            # Continue anyway on first run, but it will be missing next time
        return

    # 2. Run standard verification
    if not verifier.verify():
        # Check security level (Compatibility Mode)
        security_level = os.getenv("LLM_CLI_SECURITY_LEVEL") or config_manager.get(
            "security", "security_level", "high"
        )

        if security_level == "standard":
            from llm_cli.ui import report_warning

            report_warning(
                "Integrity Failure: System files do not match manifest, but "
                "security_level is 'standard'."
            )
            return

        from rich.panel import Panel

        from llm_cli.ui import console

        console.print(
            Panel(
                "[bold red]CRITICAL: SYSTEM INTEGRITY FAILURE[/bold red]\n\n"
                "Unauthorized modifications were detected in the application files "
                "or audit logs.\n"
                "For security, the startup process has been aborted.\n\n"
                "[bold yellow]If you modified the source code intentionally, "
                "run:[/bold yellow]\n"
                "[bold cyan]llm-cli-security manifest[/bold cyan]\n\n"
                "[dim]Note: If the failure is in the audit log (Signature mismatch), "
                "you may need to clear 'audit.jsonl' if you recently changed your "
                "identity keys.[/dim]",
                title="[bold red]Security Guard[/bold red]",
                border_style="red",
                expand=False,
            )
        )
        sys.exit(1)
