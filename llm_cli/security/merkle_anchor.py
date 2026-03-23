import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from llm_cli.consts import AUDIT_LOG_PATH
from llm_cli.security.identity import IdentityManager
from llm_cli.security.merkle import MerkleTree
from llm_cli.security.pqc import PQCProvider

logger = logging.getLogger(__name__)

# The directory where session anchors are stored
ANCHOR_DIR = AUDIT_LOG_PATH.parent / "anchors"


class SessionAnchorManager:
    """
    Manages session-wide audit anchoring using Merkle Trees and PQC signatures.
    """

    @staticmethod
    def get_session_entries(
        trace_id: str, log_path: Path | None = None
    ) -> list[dict[str, Any]]:
        """
        Extracts all audit log entries for a given trace_id.
        Searches both current log and any archives in chronological order.
        """
        if log_path is None:
            log_path = AUDIT_LOG_PATH

        entries = []

        # 1. Collect all candidate log files: archives first (oldest to newest),
        # then current log
        # Archive filenames include a timestamp of when they were created.
        # Since newer entries are moved to archives later, name-sorting archives
        # gives us chronological order.
        archive_pattern = f"{log_path.name}.archive.*.jsonl"
        log_files = sorted(log_path.parent.glob(archive_pattern))
        log_files.append(log_path)

        for path in log_files:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            if entry.get("trace_id") == trace_id:
                                entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"Failed to read log {path} for anchoring: {e}")

        # Within each file and across files in log_files order,
        # entries are now naturally in chronological order.
        return entries

    @staticmethod
    def create_anchor(trace_id: str) -> str | None:
        """
        Creates a session anchor (Merkle Root) for the given trace_id.
        Saves the signed anchor to disk.
        """
        entries = SessionAnchorManager.get_session_entries(trace_id)
        if not entries:
            logger.debug(
                f"No log entries found for session {trace_id}. Skipping anchor."
            )
            return None

        # Collect the hashes of each entry to build the Merkle Tree
        # The 'hash' field in each entry is the result of hashing the entry content.
        leaf_hashes: list[str] = [str(e["hash"]) for e in entries if e.get("hash")]

        if not leaf_hashes:
            logger.error(f"No hashes found in entries for session {trace_id}.")
            return None

        # Build Merkle Tree
        tree = MerkleTree(leaf_hashes)
        root_hex = tree.root_hex

        # Create the anchor metadata
        anchor = {
            "trace_id": trace_id,
            "merkle_root": root_hex,
            "entry_count": len(entries),
            "first_entry_hash": leaf_hashes[0],
            "last_entry_hash": leaf_hashes[-1],
            "timestamp": entries[-1].get(
                "timestamp"
            ),  # Use the timestamp of the last entry
            "anchored_at": AUDIT_LOG_PATH.stat().st_mtime
            if AUDIT_LOG_PATH.exists()
            else None,
        }

        # Sign the Merkle Root with PQC (Identity-based signature)
        try:
            import base64

            # Use the canonical representation for signing
            message = json.dumps(anchor, sort_keys=True)
            pqc_priv = IdentityManager._get_pqc_private_key_content()
            signature = PQCProvider.sign(message.encode(), pqc_priv)

            anchor["pqc_signature"] = base64.b64encode(signature).decode()
            anchor["pqc_algorithm"] = PQCProvider.ALGORITHM_NAME
        except Exception as e:
            logger.error(f"Failed to sign session anchor for {trace_id}: {e}")
            # We still return the root even if signing fails, but it won't be
            # cryptographically verifiable as a 'signed' anchor.
        # Save anchor to disk
        ANCHOR_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        anchor_path = ANCHOR_DIR / f"{trace_id}.anchor.json"

        try:
            with anchor_path.open("w", encoding="utf-8") as f:
                json.dump(anchor, f, indent=2, sort_keys=True)
            logger.info(f"Session anchor for {trace_id} saved to {anchor_path}")
        except Exception as e:
            logger.error(f"Failed to save anchor file: {e}")

        return root_hex

    @staticmethod
    def cleanup_orphaned_anchors(log_path: Path = AUDIT_LOG_PATH) -> int:
        """
        Removes session anchors that no longer have any entries in the
        current logs or archives.
        Returns the number of deleted anchors.
        """
        if not ANCHOR_DIR.exists():
            return 0

        # 1. Collect all trace_ids currently present in log files
        active_traces = set()
        archive_pattern = f"{log_path.name}.archive.*.jsonl"
        log_files = sorted(log_path.parent.glob(archive_pattern))
        log_files.append(log_path)

        for path in log_files:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            # Use a fast check to avoid full JSON parsing if possible,
                            # but trace_id is at the start mostly.
                            if '"trace_id": "' in line:
                                # Quick extract trace_id
                                start = line.find('"trace_id": "') + 13
                                end = line.find('"', start)
                                if start > 12 and end > start:
                                    trace_id = line[start:end]
                                    if trace_id != "-":
                                        active_traces.add(trace_id)
                        except Exception:
                            continue
            except Exception:
                continue

        # 2. Iterate through anchor files and delete those not in active_traces
        deleted_count = 0
        for anchor_file in ANCHOR_DIR.glob("*.anchor.json"):
            # Filename is {trace_id}.anchor.json
            trace_id = anchor_file.name.replace(".anchor.json", "")
            if trace_id not in active_traces:
                try:
                    anchor_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete orphaned anchor {anchor_file}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} orphaned session anchors.")

        return deleted_count

    @staticmethod
    def verify_session(trace_id: str) -> bool:
        """
        Verifies all log entries for a trace_id against its session anchor.
        """
        anchor_path = ANCHOR_DIR / f"{trace_id}.anchor.json"
        if not anchor_path.exists():
            logger.error(f"Anchor not found for session {trace_id}")
            return False

        try:
            with anchor_path.open("r", encoding="utf-8") as f:
                anchor = json.load(f)

            root_hex = anchor.get("merkle_root")
            pqc_sig_b64 = anchor.get("pqc_signature")
            variant = anchor.get("pqc_algorithm", "ML-DSA-65")

            # 1. Verify PQC Signature of the anchor itself
            if pqc_sig_b64:
                import base64

                # Reconstruct signed data
                anchor_copy = anchor.copy()
                anchor_copy.pop("pqc_signature", None)
                anchor_copy.pop("pqc_algorithm", None)
                message = json.dumps(anchor_copy, sort_keys=True)

                signature = base64.b64decode(pqc_sig_b64)
                pqc_pub = IdentityManager._get_pqc_public_key_content(variant=variant)

                if not PQCProvider.verify(
                    message.encode(), signature, pqc_pub, variant=variant
                ):
                    logger.error(f"Anchor signature mismatch for session {trace_id}")
                    return False
                logger.debug(f"Anchor signature for {trace_id} verified.")

            # 2. Verify all entries against the Merkle Root
            entries = SessionAnchorManager.get_session_entries(trace_id)
            if len(entries) != anchor.get("entry_count"):
                logger.error(
                    f"Entry count mismatch for session {trace_id}. "
                    f"Expected {anchor.get('entry_count')}, found {len(entries)}"
                )
                return False

            leaf_hashes: list[str] = []
            for entry in entries:
                provided_hash = entry.get("hash")
                if not provided_hash:
                    logger.error(f"Entry missing hash in session {trace_id}")
                    return False
                provided_hash = str(provided_hash)

                # Recalculate hash to verify integrity of the entry itself
                # We must exclude the hash and signature fields as they
                # weren't part of the original hash
                entry_copy = entry.copy()
                entry_copy.pop("hash", None)
                entry_copy.pop("pqc_signature", None)
                entry_copy.pop("pqc_algorithm", None)

                entry_str = json.dumps(entry_copy, sort_keys=True)
                actual_hash = hashlib.sha256(entry_str.encode()).hexdigest()

                if provided_hash != actual_hash:
                    logger.error(
                        f"Entry content tampered for trace {trace_id}. "
                        f"Provided: {provided_hash}, Actual: {actual_hash}"
                    )
                    return False

                leaf_hashes.append(provided_hash)

            tree = MerkleTree(leaf_hashes)

            if tree.root_hex != root_hex:
                logger.error(
                    f"Merkle Root mismatch for session {trace_id}. "
                    f"Anchor says {root_hex}, but recalculated {tree.root_hex}"
                )
                return False

            logger.info(f"Session {trace_id} integrity verified via Merkle Anchor.")
            return True

        except Exception as e:
            logger.error(f"Failed to verify session {trace_id}: {e}")
            return False
