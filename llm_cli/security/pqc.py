"""
Post-Quantum Cryptography (PQC) module.

This module provides providers for ML-KEM and ML-DSA,
as well as application-level utilities for tool result signing.
"""

import base64
import logging
from typing import Any

from llm_cli.security.pqc_backend import (
    get_kem_backend,
    get_pqc_backend,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ML-KEM (Key Encapsulation Mechanism)
# ---------------------------------------------------------------------------


class KEMProvider:
    """
    KEMProvider that delegates to the active KEMBackend (ML-KEM-768).
    """

    DEFAULT_VARIANT = "ML-KEM-768"

    @classmethod
    def generate_keypair(cls, variant: str = DEFAULT_VARIANT) -> tuple[bytes, bytes]:
        return get_kem_backend().generate_keypair(variant)

    @classmethod
    def encapsulate(
        cls, public_key_bytes: bytes, variant: str = DEFAULT_VARIANT
    ) -> tuple[bytes, bytes]:
        return get_kem_backend().encapsulate(public_key_bytes, variant)

    @classmethod
    def decapsulate(
        cls,
        ciphertext: bytes,
        private_key_bytes: bytes,
        variant: str = DEFAULT_VARIANT,
    ) -> bytes:
        return get_kem_backend().decapsulate(ciphertext, private_key_bytes, variant)


# ---------------------------------------------------------------------------
# Hybrid Encryption (ML-KEM + AES-256-GCM)
# ---------------------------------------------------------------------------


class SecureStorage:
    """
    Hybrid Encryption: ML-KEM + AES-256-GCM.
    Uses post-quantum KEM for key exchange and AES for data encryption.
    """

    @classmethod
    def encrypt(cls, data: bytes, recipient_public_key: bytes) -> dict[str, str]:
        """Encrypt *data* using a hybrid approach (ML-KEM-768/AES-256-GCM)."""
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        kem_ct, shared_secret = KEMProvider.encapsulate(recipient_public_key)
        aesgcm = AESGCM(shared_secret[:32])
        nonce = os.urandom(12)
        ct_with_tag = aesgcm.encrypt(nonce, data, None)

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
    def decrypt(cls, encrypted_packet: dict[str, str], private_key: bytes) -> bytes:
        """Decrypt a hybrid packet using the recipient's private key."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        kem_ct = base64.b64decode(encrypted_packet["kem_ct"])
        shared_secret = KEMProvider.decapsulate(kem_ct, private_key)

        nonce = base64.b64decode(encrypted_packet["nonce"])
        aes_ct = base64.b64decode(encrypted_packet["aes_ct"])
        tag = base64.b64decode(encrypted_packet["tag"])

        aesgcm = AESGCM(shared_secret[:32])
        return aesgcm.decrypt(nonce, aes_ct + tag, None)


# ---------------------------------------------------------------------------
# ML-DSA Digital Signatures
# ---------------------------------------------------------------------------


class PQCProvider:
    """
    PQC Signature facade that delegates to the active PQCBackend (ML-DSA-65).
    """

    DEFAULT_VARIANT = "ML-DSA-65"
    ALGORITHM_NAME = DEFAULT_VARIANT

    @classmethod
    def is_available(cls) -> bool:
        return get_pqc_backend().is_available()

    @classmethod
    def generate_keypair(cls, variant: str = DEFAULT_VARIANT) -> tuple[bytes, bytes]:
        return get_pqc_backend().generate_keypair(variant)

    @classmethod
    def sign(
        cls,
        message: bytes,
        private_key_bytes: bytes,
        variant: str = DEFAULT_VARIANT,
    ) -> bytes:
        return get_pqc_backend().sign(message, private_key_bytes, variant)

    @classmethod
    def verify(
        cls,
        message: bytes,
        signature: bytes,
        public_key_bytes: bytes,
        variant: str = DEFAULT_VARIANT,
    ) -> bool:
        return get_pqc_backend().verify(message, signature, public_key_bytes, variant)


# ---------------------------------------------------------------------------
# PQC Agility Manager
# ---------------------------------------------------------------------------


class PQCAgilityManager:
    """
    Manages security levels (ML-DSA-44/65/87) based on task risk.
    """

    @staticmethod
    def get_required_level(
        tool_name: str,
        args: Any = None,
        environment_risk: str = "standard",
    ) -> str:
        """Determine the required ML-DSA security level based on a risk matrix."""
        from llm_cli.clients.config import config_manager

        config = config_manager.load_config()
        security_config = config.get("security", {})

        high_risk_tools = set(security_config.get("high_risk_tools", []))
        sensitive_patterns = list(security_config.get("scaling_patterns", []))
        sensitive_patterns.extend(security_config.get("blocked_paths", []))

        is_sensitive_context = False
        if args:
            args_str = str(args).lower()
            if any(str(p).lower() in args_str for p in sensitive_patterns):
                is_sensitive_context = True

        if environment_risk == "high" or tool_name in high_risk_tools or is_sensitive_context:
            return "ML-DSA-87"

        moderate_risk_tools = set(security_config.get("medium_risk_tools", []))
        if tool_name in moderate_risk_tools:
            return "ML-DSA-65"

        return "ML-DSA-44"


# ---------------------------------------------------------------------------
# Response Signer & Tool Result Signing
# ---------------------------------------------------------------------------


class ResponseSigner:
    """
    Implements Bi-directional Verification by signing LLM outputs.
    """

    @classmethod
    def sign_response(
        cls,
        response_text: str,
        source_verification_id: str,
        private_key: bytes,
        variant: str = PQCProvider.DEFAULT_VARIANT,
    ) -> dict[str, str]:
        """Bind the LLM's response to the verified tool-execution ID."""
        message = f"{source_verification_id}:{response_text}".encode()
        signature = PQCProvider.sign(message, private_key, variant=variant)

        return {
            "result": response_text,
            "verification_id": source_verification_id,
            "pqc_signature": base64.urlsafe_b64encode(signature).decode(),
            "algorithm": variant,
        }


def sign_tool_result(
    result_text: str, variant: str = PQCProvider.DEFAULT_VARIANT
) -> str | dict[str, str]:
    """
    Sign a tool result with PQC (ML-DSA) for Bi-directional Verification.
    """
    import uuid

    try:
        from llm_cli.security.identity import IdentityManager

        pqc_priv = IdentityManager._get_pqc_private_key_content(variant=variant)
        verification_id = str(uuid.uuid4())
        signed = ResponseSigner.sign_response(
            response_text=result_text,
            source_verification_id=verification_id,
            private_key=pqc_priv,
            variant=variant,
        )
        return signed
    except Exception as exc:
        logger.warning("[WARNING] Failed to sign tool result: %s", exc)
        return result_text
