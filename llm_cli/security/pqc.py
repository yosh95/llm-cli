import base64
import json
import logging
from typing import Any

from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87
from kyber_py.ml_kem import ML_KEM_512, ML_KEM_768, ML_KEM_1024

logger = logging.getLogger(__name__)


class KEMProvider:
    """
    Key Encapsulation Mechanism (KEM) using ML-KEM.
    Provides post-quantum cryptographic primitives for shared secret derivation.
    """

    VARIANTS = {
        "ML-KEM-512": ML_KEM_512,  # NIST Level 1
        "ML-KEM-768": ML_KEM_768,  # NIST Level 3 (Default)
        "ML-KEM-1024": ML_KEM_1024,  # NIST Level 5
    }

    DEFAULT_VARIANT = "ML-KEM-768"

    @classmethod
    def generate_keypair(cls, variant: str = DEFAULT_VARIANT) -> tuple[bytes, bytes]:
        """Generate a KEM keypair (public_key, private_key)."""
        algo = cls.VARIANTS.get(variant, ML_KEM_768)
        return algo.keygen()  # type: ignore[no-any-return]

    @classmethod
    def encapsulate(
        cls, public_key_bytes: bytes, variant: str = DEFAULT_VARIANT
    ) -> tuple[bytes, bytes]:
        """
        Derives a shared secret and encapsulates it using the public key.
        Returns: (ciphertext, shared_secret)
        """
        algo = cls.VARIANTS.get(variant, ML_KEM_768)
        # kyber-py returns (shared_secret, ciphertext)
        ss, ct = algo.encaps(public_key_bytes)
        return ct, ss

    @classmethod
    def decapsulate(
        cls, ciphertext: bytes, private_key_bytes: bytes, variant: str = DEFAULT_VARIANT
    ) -> bytes:
        """
        Decrypts the ciphertext to retrieve the shared secret.
        """
        algo = cls.VARIANTS.get(variant, ML_KEM_768)
        # kyber-py decaps takes (sk, ct)
        return algo.decaps(private_key_bytes, ciphertext)  # type: ignore[no-any-return]


class SecureStorage:
    """
    Hybrid Encryption: ML-KEM + AES-256-GCM.
    Uses post-quantum KEM for key exchange and AES for data encryption.
    """

    @classmethod
    def encrypt(cls, data: bytes, recipient_public_key: bytes) -> dict:
        """
        Encrypts data using a hybrid approach.
        Returns: { 'kem_ct': b64, 'aes_ct': b64, 'nonce': b64, 'tag': b64 }
        """
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # 1. KEM Encapsulation (Returns ct, ss)
        kem_ct, shared_secret = KEMProvider.encapsulate(recipient_public_key)

        # 2. Symmetric Encryption (AES-256-GCM)
        # Use first 32 bytes of shared secret for AES-256
        aesgcm = AESGCM(shared_secret[:32])
        nonce = os.urandom(12)
        ct_with_tag = aesgcm.encrypt(nonce, data, None)

        # Split CT and Tag (cryptography appends tag at the end)
        tag = ct_with_tag[-16:]
        actual_ct = ct_with_tag[:-16]

        return {
            "kem_ct": base64.b64encode(kem_ct).decode(),
            "aes_ct": base64.b64encode(actual_ct).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "algo": "ML-KEM-768/AES-256-GCM",
        }

    @classmethod
    def decrypt(cls, encrypted_packet: dict, private_key: bytes) -> bytes:
        """
        Decrypts a hybrid packet using the recipient's private key.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # 1. KEM Decapsulation
        kem_ct = base64.b64decode(encrypted_packet["kem_ct"])
        shared_secret = KEMProvider.decapsulate(kem_ct, private_key)

        # 2. Symmetric Decryption
        nonce = base64.b64decode(encrypted_packet["nonce"])
        aes_ct = base64.b64decode(encrypted_packet["aes_ct"])
        tag = base64.b64decode(encrypted_packet["tag"])

        aesgcm = AESGCM(shared_secret[:32])
        return aesgcm.decrypt(nonce, aes_ct + tag, None)


class PQCProvider:
    """
    Digital Signature Provider using ML-DSA.
    Provides post-quantum cryptographic primitives for message signing.
    """

    VARIANTS = {
        "ML-DSA-44": ML_DSA_44,  # NIST Level 2
        "ML-DSA-65": ML_DSA_65,  # NIST Level 3 (Default)
        "ML-DSA-87": ML_DSA_87,  # NIST Level 5
    }

    DEFAULT_VARIANT = "ML-DSA-65"
    ALGORITHM_NAME = DEFAULT_VARIANT

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def generate_keypair(cls, variant: str = DEFAULT_VARIANT) -> tuple[bytes, bytes]:
        """Generate a signature keypair."""
        algo = cls.VARIANTS.get(variant, ML_DSA_65)
        return algo.keygen()  # type: ignore[no-any-return]

    @classmethod
    def sign(
        cls, message: bytes, private_key_bytes: bytes, variant: str = DEFAULT_VARIANT
    ) -> bytes:
        """Sign a message using the specified variant."""
        algo = cls.VARIANTS.get(variant, ML_DSA_65)
        return algo.sign(private_key_bytes, message, deterministic=True)  # type: ignore[no-any-return]

    @classmethod
    def verify(
        cls,
        message: bytes,
        signature: bytes,
        public_key_bytes: bytes,
        variant: str = DEFAULT_VARIANT,
    ) -> bool:
        """Verify a signature using the specified variant."""
        algo = cls.VARIANTS.get(variant, ML_DSA_65)
        try:
            return algo.verify(public_key_bytes, message, signature)  # type: ignore[no-any-return]
        except Exception:
            return False


class PQCAgilityManager:
    """
    Manages security levels based on task risk.
    Adjusts algorithm parameters based on the tool being executed.
    """

    @staticmethod
    def get_required_level(
        tool_name: str, args: Any = None, environment_risk: str = "standard"
    ) -> str:
        """Determines the required security level based on a risk matrix."""
        from llm_cli.clients.config import _load_config_from_file

        config = _load_config_from_file()
        security_config = config.get("security", {})

        # Risk levels for specific tools
        high_risk_tools = {
            "execute_python",
            "edit_file",
            "create_or_overwrite_file",
            "delete_file",
            "database_query",
        }

        # Dynamic context analysis (e.g., sensitive file access)
        # Defaults to a reasonable set if not specified in config
        sensitive_patterns = security_config.get("scaling_patterns", [])
        # Also include blocked_paths as sensitive for scaling
        sensitive_patterns.extend(security_config.get("blocked_paths", []))

        is_sensitive_context = False
        if args:
            args_str = str(args).lower()
            if any(str(pattern).lower() in args_str for pattern in sensitive_patterns):
                is_sensitive_context = True

        # Policy Matrix
        if (
            environment_risk == "high"
            or tool_name in high_risk_tools
            or is_sensitive_context
        ):
            return "ML-DSA-87"  # NIST Level 5 (Maximum Resilience)

        # Adaptive scaling for moderate tools
        moderate_risk_tools = {"read_file", "list_files_in_directory"}
        if tool_name in moderate_risk_tools:
            return "ML-DSA-65"  # NIST Level 3 (Balanced)

        return "ML-DSA-44"  # NIST Level 2 (Optimized for Latency)


class ResponseSigner:
    """
    Implements Bi-directional Verification.
    Signs the final output to prove it was derived from verified tool observations.
    """

    @classmethod
    def sign_response(
        cls, response_text: str, source_verification_id: str, private_key: bytes
    ) -> dict:
        """
        Binds the LLM's response to the verified tool execution ID.
        """
        message = f"{source_verification_id}:{response_text}".encode()
        signature = PQCProvider.sign(message, private_key)

        return {
            "response": response_text,
            "verification_id": source_verification_id,
            "pqc_signature": base64.urlsafe_b64encode(signature).decode(),
            "algorithm": PQCProvider.DEFAULT_VARIANT,
        }


class AuditAnchoring:
    """
    Facilitates external anchoring of audit logs to prevent historical revisionism.
    Uses a binary Merkle Tree for efficient integrity verification.
    """

    @staticmethod
    def generate_anchor_root(log_entries: list[dict]) -> str:
        """
        Generates a Merkle Root for a batch of audit logs.
        """
        import hashlib

        if not log_entries:
            return "0" * 64

        # 1. Generate leaves (hash of each entry)
        hashes = []
        for e in log_entries:
            # Canonicalize entry for hashing
            entry_to_hash = {k: v for k, v in e.items() if k != "pqc_signature"}
            entry_str = json.dumps(entry_to_hash, sort_keys=True)
            hashes.append(hashlib.sha256(entry_str.encode()).hexdigest())

        # 2. Build the tree level by level
        while len(hashes) > 1:
            if len(hashes) % 2 != 0:
                hashes.append(hashes[-1])  # Duplicate last element if odd

            new_level = []
            for i in range(0, len(hashes), 2):
                combined = (hashes[i] + hashes[i + 1]).encode()
                new_level.append(hashlib.sha256(combined).hexdigest())
            hashes = new_level

        return hashes[0]

    @classmethod
    def create_external_anchor(cls) -> str | None:
        """
        Performs the anchoring process: reads the audit log, generates Merkle Root,
        and provides it as an immutable anchor.
        """
        from llm_cli.consts import AUDIT_LOG_PATH

        if not AUDIT_LOG_PATH.exists():
            return None

        entries = []
        with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue

        if not entries:
            return None

        root = cls.generate_anchor_root(entries)

        # In a production system, this root would be sent to a Blockchain or
        # a Managed Immutable Log Service.
        # For this implementation, we log it to a dedicated security log.
        try:
            import datetime

            from llm_cli.clients.config import get_setting
            from llm_cli.consts import SECURITY_LOG_PATH

            SECURITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with SECURITY_LOG_PATH.open("a", encoding="utf-8") as f:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] 🔗 [POST-QUANTUM ANCHOR] Merkle Root: {root}\n")

            # Trim the security log to prevent it from growing indefinitely
            max_lines = int(get_setting("max_security_log_lines", "general") or 1000)
            with SECURITY_LOG_PATH.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with SECURITY_LOG_PATH.open(
                    "w", encoding="utf-8", errors="replace"
                ) as f:
                    f.writelines(lines[-max_lines:])
        except Exception:
            pass

        logger.info(f"🔗 [POST-QUANTUM ANCHOR] Merkle Root: {root}")
        return root


class HybridSigner:
    """
    Implements Hybrid Signatures (Classical + Post-Quantum).
    Ensures security even if one algorithm is compromised.
    Uses URL-safe Base64 for the PQC component to avoid JWT parsing issues.
    """

    def __init__(self, classical_signer: Any, pqc_provider: type[PQCProvider]):
        self.classical = classical_signer
        self.pqc = pqc_provider

    @classmethod
    def create_hybrid_token(
        cls, payload: dict, rsa_private_key: bytes, pqc_private_key: bytes
    ) -> str:
        """
        Creates a JWT token signed with RSA and adds a PQC signature as a 4th part.
        """

        import jwt

        # 1. Generate Classical JWT
        token = jwt.encode(payload, rsa_private_key, algorithm="RS256")

        # 2. Generate PQC Signature of the classical token
        pqc_sig = PQCProvider.sign(token.encode(), pqc_private_key)
        # Use urlsafe_b64encode for compatibility with JWT structure
        pqc_sig_b64 = base64.urlsafe_b64encode(pqc_sig).decode().rstrip("=")

        # 3. Create a Hybrid Wrap: [Header].[Payload].[Signature].[PQC_Signature]
        return f"{token}.{pqc_sig_b64}"

    @classmethod
    def verify_hybrid_token(
        cls, hybrid_token: str, rsa_public_key: bytes, pqc_public_key: bytes
    ) -> dict | None:
        """
        Verifies both Classical and PQC signatures.
        """
        import jwt

        # We expect 4 parts: [Header].[Payload].[RSA_Sig].[PQC_Sig]
        parts = hybrid_token.split(".")
        if len(parts) != 4:
            logger.warning(
                f"Invalid hybrid token format: expected 4 parts, got {len(parts)}."
            )
            return None

        jwt_token = ".".join(parts[:3])
        pqc_sig_b64 = parts[3]

        # 1. Verify Classical Signature
        try:
            payload = jwt.decode(
                jwt_token,
                rsa_public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except Exception as e:
            logger.error(f"Classical signature verification failed: {e}")
            return None

        # 2. Verify PQC Signature
        try:
            # Add padding back if needed for standard b64 decoding if required,
            # but urlsafe_b64decode handles it or we can add it manually.
            padding = "=" * (4 - len(pqc_sig_b64) % 4)
            pqc_sig = base64.urlsafe_b64decode(pqc_sig_b64 + padding)

            if not PQCProvider.verify(jwt_token.encode(), pqc_sig, pqc_public_key):
                raise ValueError("PQC verification failed")
        except Exception as e:
            error_msg = (
                f"[SECURITY_ALERT] Post-Quantum signature verification failed: {e}. "
                "Potential Quantum Spoofing attempt detected."
            )
            logger.error(error_msg)
            # (Omitted: Audit logging logic for brevity, same as before)
            return None

        logger.info("✅ Hybrid Signature Verified (RSA + PQC)")
        return payload
