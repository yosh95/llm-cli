import hashlib
import json
import logging
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from llm_cli.consts import LLM_CLI_BASE_DIR

logger = logging.getLogger(__name__)

# Global state to track the latest reasoning integrity score for audit logging
current_integrity_score: float | None = None


class ReasoningSentinelManager:
    """
    Manages the MambaSentinel for real-time anomaly detection in AI reasoning.
    Integrates with the audit log to provide 'Reasoning Integrity' scores.
    """

    def __init__(self, **kwargs: Any):

        from llm_cli.clients.config import get_setting
        from llm_cli.security.sentinel import MambaSentinel

        global current_integrity_score
        current_integrity_score = None  # Reset global score on new manager init

        # Load settings
        self.enabled = get_setting("enabled", "sentinel")
        if self.enabled is None:
            self.enabled = True

        mode = get_setting("mode", "sentinel") or "collect"
        t_yellow = float(get_setting("threshold_yellow", "sentinel") or 3.5)
        t_red = float(get_setting("threshold_red", "sentinel") or 5.0)

        # Mamba-specific parameters from defaults
        d_model = int(get_setting("d_model", "sentinel") or 128)
        n_layers = int(get_setting("n_layers", "sentinel") or 2)
        d_state = int(get_setting("d_state", "sentinel") or 16)
        d_conv = int(get_setting("d_conv", "sentinel") or 4)
        expand = int(get_setting("expand", "sentinel") or 2)
        lr = float(get_setting("lr", "sentinel") or 1e-3)

        # Override with kwargs if provided
        d_model = kwargs.get("d_model", d_model)
        n_layers = kwargs.get("n_layers", n_layers)

        checkpoint_name = (
            get_setting("checkpoint_path", "sentinel") or "sentinel_state.npz"
        )
        checkpoint_path = str(LLM_CLI_BASE_DIR / checkpoint_name)

        self.sentinel = MambaSentinel(
            d_model=d_model,
            n_layers=n_layers,
            d_state=d_state,
            d_conv=d_conv,
            expand=expand,
            lr=lr,
            checkpoint_path=checkpoint_path,
            mode=mode,
            threshold_yellow=t_yellow,
            threshold_red=t_red,
        )
        self.sentinel.load()
        self.history_tokens: list[int] = []
        self.max_history = 2048  # Increased history for better context
        self.score_history: list[float] = []  # For Trust Trend visualization

        # Performance metrics
        self.last_processing_time: float = 0.0
        self.total_processing_time: float = 0.0
        self.processing_count: int = 0
        self.suspected_secrets: list[str] = []

    def _calculate_shannon_entropy(self, data: bytes) -> float:
        """Calculate Shannon entropy of a byte sequence."""
        if not data:
            return 0.0
        counter = Counter(data)
        len_data = len(data)
        entropy = 0.0
        for count in counter.values():
            p = count / len_data
            entropy -= p * math.log2(p)
        return entropy

    def _analyze_for_secrets(self, data: bytes, scores: list[float]) -> list[str]:
        """
        Analyze a sequence of bytes and their Mamba surprise scores for secrets.
        Uses a combination of Shannon Entropy and Model Surprise.
        """
        # Match secret-like tokens at byte level to ensure indices match 'scores'
        # Pattern: Alphanumeric + common Base64/Key symbols, length 16+
        pattern = b"[A-Za-z0-9+/=_\\-\\.]{16,}"
        potential_tokens = re.finditer(pattern, data)
        suspected = []

        for match in potential_tokens:
            token_bytes = match.group()
            start, end = match.span()

            # 1. Calculate Shannon Entropy (0.0 to 8.0)
            entropy = self._calculate_shannon_entropy(token_bytes)

            # 2. Calculate average Mamba surprise (cross-entropy) for this token
            token_scores = scores[start:end]
            avg_surprise = (
                sum(token_scores) / len(token_scores) if token_scores else 0.0
            )

            # --- Heuristics ---
            # Thresholds are chosen to be conservative to minimize false positives
            # while catching random keys.
            is_high_entropy = entropy > 4.7
            is_surprising = avg_surprise > self.sentinel.thresholds["yellow"]

            # If both entropy and surprise are high, it's likely a secret/key
            if is_high_entropy and is_surprising:
                try:
                    suspected.append(token_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    suspected.append(str(token_bytes))

        return list(set(suspected))

    def process_chunk(self, chunk: str) -> float:
        """
        Process a text chunk from the LLM stream.
        Returns the average anomaly score for the chunk.
        """
        import time

        import numpy as np

        global current_integrity_score

        if not self.enabled or not chunk:
            return 0.0

        start_time = time.perf_counter()

        bytes_data = chunk.encode("utf-8")
        scores: list[float] = []

        for byte in bytes_data:
            # Step the sentinel: it returns the score for THIS byte based
            # on PREVIOUS logits, and then updates its internal logits
            # for the NEXT byte.
            score, _status = self.sentinel.step(byte)
            scores.append(score)
            self.history_tokens.append(byte)

        # Truncate history if needed
        if len(self.history_tokens) > self.max_history:
            self.history_tokens = self.history_tokens[-self.max_history :]

        avg_score = float(np.mean(scores)) if scores else 0.0
        current_integrity_score = avg_score

        # Secret detection (Entropy + Mamba Surprise)
        self.suspected_secrets.extend(self._analyze_for_secrets(bytes_data, scores))

        # Track performance
        elapsed = time.perf_counter() - start_time
        self.last_processing_time = elapsed
        self.total_processing_time += elapsed
        self.processing_count += 1

        # Track history for visualization
        if scores:
            self.score_history.append(avg_score)
            if len(self.score_history) > 20:
                self.score_history.pop(0)

        return avg_score

    def get_sentinel_status(self) -> tuple[float, str]:
        """
        Returns the current average score and its status (green, yellow, red).
        """
        score = current_integrity_score if current_integrity_score is not None else 0.0
        status = "green"
        if score > self.sentinel.thresholds["red"]:
            status = "red"
        elif score > self.sentinel.thresholds["yellow"]:
            status = "yellow"
        return score, status

    def finalize_session(self, learn: bool | None = None) -> None:
        """
        Finalize the session, optionally performing online learning update.
        """
        import numpy as np

        # Determine if we should learn based on mode or explicit override
        if learn is None:
            learn = self.sentinel.mode == "collect"

        if learn and len(self.history_tokens) > 1:
            # Perform online learning on the collected session history
            # input: 0..N-1, target: 1..N
            input_ids = np.array([self.history_tokens[:-1]], dtype=np.int32)
            targets = np.array([self.history_tokens[1:]], dtype=np.int32)
            self.sentinel.update(input_ids, targets)
            self.sentinel.save()

        # Reset session state for next turn
        self.sentinel.reset_state()
        # We keep history_tokens within max_history to allow cross-turn context,
        # but for clean turns we might want to clear it.
        # For Sentinel, cross-turn context is usually better.
        # self.history_tokens = []


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
            from llm_cli.security.identity import IdentityManager
            from llm_cli.security.pqc import PQCProvider

            pqc_pub = IdentityManager._get_pqc_public_key_content()

            with audit_log_path.open("r", encoding="utf-8") as f:
                last_hash = "0" * 64
                for i, line in enumerate(f):
                    entry = json.loads(line)
                    provided_hash = entry.pop("hash", None)
                    pqc_sig_b64 = entry.pop("pqc_signature", None)
                    entry.pop("pqc_algorithm", None)

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

                    # Verify PQC Signature of the hash
                    if pqc_sig_b64:
                        import base64

                        pqc_sig = base64.b64decode(pqc_sig_b64)
                        if not PQCProvider.verify(
                            actual_hash.encode(), pqc_sig, pqc_pub
                        ):
                            logger.error(
                                f"❌ Audit log PQC verification failed at line {i + 1}"
                            )
                            return False

                    last_hash = provided_hash
            logger.info("✅ Audit log integrity and PQC signatures verified.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to verify audit log: {e}")
            return False

    def verify(self, allow_tofu: bool = False) -> bool:
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
            if not allow_tofu and os.getenv("LLM_CLI_STRICT_SECURITY", "1") == "1":
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

        # Ensure we have keys for signing, even in strict mode
        try:
            from llm_cli.security.identity import IdentityManager

            IdentityManager._ensure_keys(force=True)
        except Exception as e:
            logger.error(f"Failed to ensure identity keys: {e}")
            return False

        if self.MANIFEST_PATH.exists():
            try:
                self.MANIFEST_PATH.unlink()
                logger.info("Deleted existing manifest.")
            except Exception as e:
                logger.error(f"Failed to delete manifest: {e}")
                return False

        # Calling verify() with allow_tofu=True will trigger TOFU logic
        # since manifest is gone
        return self.verify(allow_tofu=True)

    def generate_attestation_token(self) -> dict:
        """
        Generates a PQC-signed attestation object of the current system integrity.
        This is embedded into identity tokens for Zero-Trust propagation.
        """
        import base64
        import time

        from llm_cli.security.identity import IdentityManager
        from llm_cli.security.pqc import PQCProvider

        # Collect current state
        state = {
            "ts": time.time(),
            "integrity_ok": True,
            "workload": IdentityManager.get_local_identity(),
        }

        # Create message to sign
        message = json.dumps(state, sort_keys=True)
        pqc_priv = IdentityManager._get_pqc_private_key_content()

        # Sign with PQC
        signature = PQCProvider.sign(message.encode(), pqc_priv)

        return {
            "evidence": state,
            "pqc_signature": base64.b64encode(signature).decode(),
            "pqc_algorithm": PQCProvider.ALGORITHM_NAME,
        }


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
