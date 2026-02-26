import base64
import logging
from typing import Any

from dilithium_py.ml_dsa import ML_DSA_65

logger = logging.getLogger(__name__)


class PQCProvider:
    """
    NIST-compliant PQC Provider.
    Primary: ML-DSA-65 (FIPS 204)
    """

    ALGORITHM_NAME = "ML-DSA-65"

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def generate_keypair(cls) -> tuple[bytes, bytes]:
        # pk, sk
        return ML_DSA_65.keygen()  # type: ignore[no-any-return]

    @classmethod
    def sign(cls, message: bytes, private_key_bytes: bytes) -> bytes:
        return ML_DSA_65.sign(private_key_bytes, message, deterministic=True)  # type: ignore[no-any-return]

    @classmethod
    def verify(cls, message: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
        try:
            return ML_DSA_65.verify(public_key_bytes, message, signature)  # type: ignore[no-any-return]
        except Exception:
            return False


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
