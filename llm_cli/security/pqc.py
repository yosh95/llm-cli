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
    Manages cryptographic agility for AI agents.
    Allows the orchestrator to scale security levels based on task risk.
    """

    @staticmethod
    def get_required_level(tool_name: str) -> str:
        """Determines the required PQC security level for a given tool."""
        high_risk_tools = {
            "execute_shell_command",
            "edit_file",
            "create_or_overwrite_file",
            "delete_file",
            "database_query",
        }
        if tool_name in high_risk_tools:
            return "ML-DSA-87"  # NIST Level 5 for high-impact actions
        return "ML-DSA-65"  # NIST Level 3 for standard actions


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
            logger.error("Post-Quantum signature verification failed!")
            return None

        logger.info("✅ Hybrid Signature Verified (RSA + PQC)")
        return payload
