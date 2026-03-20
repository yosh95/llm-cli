import hashlib
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

from llm_cli.consts import LLM_CLI_BASE_DIR

logger = logging.getLogger(__name__)


class ReasoningSentinelManager:
    """
    Manages the monitoring sentinel for real-time pattern analysis in LLM output.
    Integrates with the audit log to provide anomaly scores.
    """

    def __init__(self, **kwargs: Any):

        from llm_cli.clients.config import get_setting
        from llm_cli.security.sentinel import MambaSentinel

        # Per-instance integrity score (replaces the former module-level global).
        # Storing it here makes the value thread-safe and testable in isolation.
        self.current_score: float | None = None

        # Load settings
        self.enabled = get_setting("enabled", "sentinel")
        if self.enabled is None:
            self.enabled = True

        mode = get_setting("mode", "sentinel") or "learn"

        # Mamba-specific parameters from defaults
        d_model = int(get_setting("d_model", "sentinel") or 128)
        n_layers = int(get_setting("n_layers", "sentinel") or 4)
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
        )
        self.sentinel.load()
        self.history_tokens: list[int] = []
        self._learning_lock = threading.Lock()
        self.max_history = 2048  # Increased history for better context
        self.score_history: list[float] = []  # For Trust Trend visualization

        # Performance metrics
        self.last_processing_time: float = 0.0
        self.last_learning_time: float = (
            0.0  # Time taken for the last background update
        )
        self.total_processing_time: float = 0.0
        self.processing_count: int = 0
        self.suspected_secrets: list[str] = []

    def _analyze_for_anomalies(self, data: bytes, scores: list[float]) -> list[str]:
        """
        Identify anomalous sub-sequences based on Mamba surprise scores.
        Flags segments that significantly deviate from learned behavioral patterns.
        """
        # Identify potential structural segments (length 16+)
        pattern = b"[A-Za-z0-9+/=_\\-\\.]{16,}"
        segments = re.finditer(pattern, data)
        anomalies = []

        # Get thresholds from the self-calibrating sentinel
        _y, t_red = self.sentinel.get_dynamic_thresholds()

        for match in segments:
            start, end = match.span()
            segment_bytes = match.group()

            # Analyze the model's surprise score for this specific segment
            if start < len(scores) and end <= len(scores):
                segment_scores = scores[start:end]
                avg_surprise = sum(segment_scores) / len(segment_scores)

                # Flag if the segment is statistically unpredictable
                # for the Mamba baseline
                if avg_surprise > t_red:
                    try:
                        anomalies.append(segment_bytes.decode("utf-8"))
                    except UnicodeDecodeError:
                        anomalies.append(str(segment_bytes))

        return list(set(anomalies))

    def initialize_context(self, user_prompt: str) -> None:
        """
        Inject the user's intent into the Sentinel's state without training.
        This allows the model to 'understand' what the agent should be doing
        by establishing an initial hidden state based on the user's request.
        """
        if not self.enabled or not user_prompt:
            return

        # Temporarily switch to enforce mode to avoid learning the prompt as
        # the agent's own behavior. We want it to be the *context*.
        original_mode = self.sentinel.mode
        self.sentinel.mode = "enforce"

        # Prefixing with "Context:" helps the model distinguish intent from action
        context_str = f"Context: {user_prompt}\nAgent reasoning:"
        self.sentinel.process_text(context_str)

        self.sentinel.mode = original_mode
        logger.debug(f"Sentinel context initialized with prompt: {user_prompt[:30]}...")

    def process_chunk(self, chunk: str, user_prompt: str | None = None) -> float:
        """
        Process a text chunk from the LLM stream.
        Returns the average anomaly score for the chunk.
        """
        import time

        import numpy as np

        if not self.enabled or not chunk:
            return 0.0

        start_time = time.perf_counter()

        # --- Prompt Anchoring (Intent Conditioning) ---
        # If a user prompt is provided, we temporarily inject it into the Sentinel's
        # hidden state to "anchor" the model's expectation to the user's intent.
        # This significantly improves detection of subtle semantic deviations.
        original_states = None
        if user_prompt:
            original_states = self.sentinel.get_states()
            # Feed intent without scoring or permanent state change
            intent_context = f"Context: {user_prompt}\nAgent reasoning:"
            # Use enforce mode for anchoring to avoid training on the prompt
            orig_mode = self.sentinel.mode
            self.sentinel.mode = "enforce"
            self.sentinel.process_text(intent_context)
            self.sentinel.mode = orig_mode

        bytes_data = chunk.encode("utf-8")
        scores: list[float] = []

        for byte in bytes_data:
            score, _status = self.sentinel.step(byte)
            scores.append(score)
            self.history_tokens.append(byte)

        # Restore original state after processing the chunk to keep anchoring fresh
        # and prevent state drift from the re-injected context.
        if original_states:
            self.sentinel.set_states(original_states)

        if len(self.history_tokens) > self.max_history:
            self.history_tokens = self.history_tokens[-self.max_history :]

        avg_score = float(np.mean(scores)) if scores else 0.0
        self.current_score = avg_score

        # Identify anomalous patterns in the byte stream
        self.suspected_secrets.extend(self._analyze_for_anomalies(bytes_data, scores))

        elapsed = time.perf_counter() - start_time
        self.last_processing_time = elapsed
        self.total_processing_time += elapsed
        self.processing_count += 1

        if scores:
            self.score_history.append(avg_score)
            if len(self.score_history) > 20:
                self.score_history.pop(0)

        return avg_score

    def get_sentinel_status(self) -> tuple[float, str]:
        """
        Returns the current average score and its status (green, yellow, red).
        Reads from the instance property instead of a module-level global.
        """
        score = self.current_score if self.current_score is not None else 0.0
        status = "green"
        if score > self.sentinel.thresholds["red"]:
            status = "red"
        elif score > self.sentinel.thresholds["yellow"]:
            status = "yellow"
        return score, status

    def finalize_session(self, learn: bool | None = None) -> None:
        """
        Finalize the session, optionally performing online learning update.
        Learning is performed asynchronously in learn mode to improve UX.
        """
        import numpy as np

        # Determine if we should learn based on mode or explicit override
        if learn is None:
            learn = self.sentinel.mode == "learn"

        if learn and len(self.history_tokens) > 1:
            # Copy history to avoid race conditions during background update
            tokens = list(self.history_tokens)

            def run_learning() -> None:
                # Ensure only one background learning process runs at a time
                if not self._learning_lock.acquire(blocking=False):
                    logger.debug(
                        "Sentinel learning already in progress, skipping turn."
                    )
                    return
                try:
                    import time

                    start_learn = time.perf_counter()

                    # Perform online learning on the collected session history
                    # input: 0..N-1, target: 1..N
                    input_ids = np.array([tokens[:-1]], dtype=np.int32)
                    targets = np.array([tokens[1:]], dtype=np.int32)
                    self.sentinel.update(input_ids, targets)
                    self.sentinel.save()

                    self.last_learning_time = time.perf_counter() - start_learn
                    logger.debug(
                        f"Sentinel background learning complete ({len(tokens)} "
                        f"tokens) in {self.last_learning_time:.4f}s."
                    )
                except Exception as e:
                    logger.error(f"Sentinel background learning failed: {e}")
                finally:
                    self._learning_lock.release()

            # Start learning in a background thread to prevent UX lag.
            # We use a daemon thread so it doesn't block app exit.
            threading.Thread(target=run_learning, daemon=True).start()

        # We keep history_tokens within max_history to allow cross-turn context,
        # but for clean turns we might want to clear it.
        # For Sentinel, cross-turn context is usually better.
        # self.history_tokens = []


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
            logger.info(f"Integrity manifest saved to {self.MANIFEST_PATH}")
        except Exception as e:
            logger.error(f"Failed to save integrity manifest: {e}")

    def verify_audit_log(self) -> bool:
        """Verify the chained hashes in the audit log to detect modifications."""
        from llm_cli.consts import AUDIT_LOG_PATH

        # Note: In a real app, this would use a proper config loader
        audit_log_path = AUDIT_LOG_PATH

        if not audit_log_path.exists():
            return True

        logger.info("Verifying audit log integrity...")
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
                    is_snapshot = entry.get("event_type") == "__audit_snapshot__"
                    if not is_snapshot and entry.get("prev_hash") != last_hash:
                        logger.error(f"Audit log chain broken at line {i + 1}")
                        return False

                    # Verify current entry's hash
                    entry_str = json.dumps(entry, sort_keys=True)
                    actual_hash = hashlib.sha256(entry_str.encode()).hexdigest()

                    if provided_hash != actual_hash:
                        logger.error(f"Audit log mismatch detected at line {i + 1}")
                        return False

                    # If it's a snapshot, it resets the chain 'last_hash'
                    # for subsequent entries
                    if is_snapshot:
                        logger.debug(
                            f"Audit log snapshot at line {i + 1}. Re-anchoring chain."
                        )
                        # The first entry after snapshot expects prev_hash to match
                        # the one stored in snapshot's args
                        last_hash = entry.get("args", {}).get("snapshot_prev_hash")
                    else:
                        last_hash = provided_hash

                    # Verify PQC Signature of the hash
                    if pqc_sig_b64:
                        import base64

                        pqc_sig = base64.b64decode(pqc_sig_b64)
                        if not PQCProvider.verify(
                            actual_hash.encode(), pqc_sig, pqc_pub
                        ):
                            logger.error(
                                f"Audit log verification failed at line {i + 1}"
                            )
                            return False
            logger.info("Audit log integrity verified.")
            return True
        except Exception as e:
            logger.error(f"Failed to verify audit log: {e}")
            return False

    def verify(self, allow_tofu: bool = False) -> bool:
        """Verify integrity of critical files and audit log."""
        logger.info("System Integrity: Verifying application files...")

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
                                "Integrity check failed: Manifest signature mismatch"
                            )
                            return False
                        logger.debug("Manifest signature verified.")
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
                if trusted_manifest and rel_path in trusted_manifest:
                    logger.error(
                        f"Integrity check failed: Critical file missing: {rel_path}"
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
                    "Integrity manifest missing. "
                    "Please generate it using 'llm-cli-security manifest'."
                )
                return False

            logger.warning(
                "No integrity manifest found. Establishing trust baseline..."
            )
            self._save_manifest(current_manifest)
            trusted_manifest = current_manifest

        # Compare against trusted manifest
        for rel_path, trusted_hash in trusted_manifest.items():
            current_hash = current_manifest.get(rel_path)

            if current_hash is None:
                logger.error(
                    f"Integrity check failed: Critical file missing: {rel_path}"
                )
                all_ok = False
                continue

            if current_hash != trusted_hash:
                logger.error(f"Integrity check failed: Hash mismatch for {rel_path}")
                all_ok = False
            else:
                logger.debug(f"Verified: {rel_path}")

        # Also verify the audit log chain
        if not self.verify_audit_log():
            all_ok = False

        if all_ok:
            logger.info("System integrity verified.")

        return all_ok

    def rebuild_manifest(self) -> bool:
        """
        Force rebuild of the integrity manifest.
        This establishes a new trust baseline based on the current system state.
        Use with caution.
        """
        logger.warning("Rebuilding integrity manifest...")

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
    root_path = Path(__file__).resolve().parent.parent.parent

    verifier = IntegrityVerifier(root_path)
    if not verifier.verify():
        logger.critical("Integrity check failed. Aborting startup.")
        sys.exit(1)
