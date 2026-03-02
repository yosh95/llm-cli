import base64
import logging
from typing import Any

from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87

logger = logging.getLogger(__name__)


class PQCProvider:
    """
    NIST-compliant PQC Provider.
    Supports ML-DSA (FIPS 204) variants for cryptographic agility.
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
        """Generate a PQC keypair for the specified NIST security level."""
        algo = cls.VARIANTS.get(variant, ML_DSA_65)
        return algo.keygen()  # type: ignore[no-any-return]

    @classmethod
    def sign(
        cls, message: bytes, private_key_bytes: bytes, variant: str = DEFAULT_VARIANT
    ) -> bytes:
        """Sign a message using the specified ML-DSA variant."""
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
        """Verify a signature using the specified ML-DSA variant."""
        algo = cls.VARIANTS.get(variant, ML_DSA_65)
        try:
            return algo.verify(public_key_bytes, message, signature)  # type: ignore[no-any-return]
        except Exception:
            return False


class PQCAgilityManager:
    """
    Manages Context-Adaptive Security Scaling (CASS).
    Dynamically adjusts NIST security levels based on task risk and execution environment.
    """

    @staticmethod
    def get_required_level(tool_name: str, environment_risk: str = "standard") -> str:
        """Determines the required PQC security level using a risk-aware matrix."""
        # Risk levels for specific tools
        high_risk_tools = {
            "execute_shell_command",
            "edit_file",
            "create_or_overwrite_file",
            "delete_file",
            "database_query",
        }

        # Policy Matrix
        if environment_risk == "high" or tool_name in high_risk_tools:
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
            "pqc_signature": base64.b64encode(signature).decode(),
            "algorithm": PQCProvider.DEFAULT_VARIANT
        }


class AuditAnchoring:
    """
    Facilitates external anchoring of audit logs to prevent historical revisionism.
    """

    @staticmethod
    def generate_anchor_root(log_entries: list[dict]) -> str:
        """
        Generates a Merkle Root for a batch of audit logs to be anchored externally.
        """
        import hashlib
        combined = "".join(str(entry) for entry in log_entries).encode()
        return hashlib.sha256(combined).hexdigest()


class HybridSigner:
    """
    Implements Hybrid Signatures (Classical + Post-Quantum).
    Ensures security even if one algorithm is compromised.
    """

    def __init__(self, classical_signer: Any, pqc_provider: type[PQCProvider]):
        self.classical = classical_signer
        self.pqc = pqc_provider

    @classmethod
    def create_hybrid_token(
        cls, payload: dict, rsa_private_key: bytes, pqc_private_key: bytes
    ) -> str:
        """
        Creates a JWT token signed with RSA and adds a PQC signature in the header.
        """

        import jwt

        # 1. Generate Classical JWT
        token = jwt.encode(payload, rsa_private_key, algorithm="RS256")

        # 2. Generate PQC Signature of the classical token
        pqc_sig = PQCProvider.sign(token.encode(), pqc_private_key)
        pqc_sig_b64 = base64.b64encode(pqc_sig).decode()

        # 3. Create a Hybrid Wrap
        return f"{token}.{pqc_sig_b64}"

    @classmethod
    def verify_hybrid_token(
        cls, hybrid_token: str, rsa_public_key: bytes, pqc_public_key: bytes
    ) -> dict | None:
        """
        Verifies both Classical and PQC signatures.
        """
        import jwt

        parts = hybrid_token.split(".")
        if len(parts) != 4:  # JWT (3 parts) + PQC Sig (1 part)
            logger.warning("Invalid hybrid token format.")
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
        pqc_sig = base64.b64decode(pqc_sig_b64)
        if not PQCProvider.verify(jwt_token.encode(), pqc_sig, pqc_public_key):
            error_msg = "[SECURITY_ALERT] Post-Quantum signature verification failed! Potential Quantum Spoofing attempt detected."
            logger.error(error_msg)

            # Explicitly tag the security event in the chained audit logs
            try:
                from llm_cli.security.audit import log_audit

                log_audit(
                    tool_name="security_identity_verify",
                    args={"protocol": "hybrid_pqc", "variant": cls.ALGORITHM_NAME},
                    _output=None,
                    error=error_msg,
                    context={"user_id": payload.get("sub", "unknown"), "action": "pqc_auth_failure"},
                )
            except Exception as audit_err:
                logger.debug(f"Failed to record PQC failure to audit log: {audit_err}")

            return None

        logger.info("✅ Hybrid Signature Verified (RSA + PQC)")
        return payload
