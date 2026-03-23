"""
Post-Quantum Cryptography (PQC) module.

Hybrid Signature implementation conforming to COSE (RFC 9052 / CBOR Object
Signing and Encryption).  This module is intentionally self-contained:
it uses ``cbor2`` and ``cryptography`` directly rather than a COSE helper
library so that integration with non-standard ML-DSA algorithm identifiers
is straightforward and fully auditable.

COSE algorithm identifiers used
--------------------------------
- ``-257`` : RS256  – RSASSA-PKCS1-v1_5 w/ SHA-256  (classical)
- ``-48``  : ML-DSA – NIST ML-DSA (Dilithium), custom registration

COSE message structure (tag 98 = COSE_Sign)
--------------------------------------------
COSE_Sign = [
    protected   : bstr .cbor header_map,   # {1: alg_id, ...}
    unprotected : header_map,              # {}
    payload     : bstr / nil,
    signatures  : [+ COSE_Signature],
]

COSE_Signature = [
    protected   : bstr .cbor header_map,
    unprotected : header_map,
    signature   : bstr,
]

Sig_Structure (the bytes that are signed) = [
    "Signature",         # context
    body_protected,      # protected header of the outer message
    sign_protected,      # protected header of this signer
    b"",                 # external_aad (empty)
    payload,             # message payload
]
"""

import base64
import logging
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from llm_cli.security.pqc_backend import (
    get_kem_backend,
    get_pqc_backend,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# COSE algorithm identifiers (RFC 9052 §9.1 + custom registration)
# ---------------------------------------------------------------------------
_COSE_ALG_RS256 = -257  # RSASSA-PKCS1-v1_5 with SHA-256
_COSE_ALG_MLDSA = -48  # ML-DSA-65 (custom / IANA pending)

# COSE header label for Algorithm (RFC 9052 §3.1)
_COSE_HEADER_ALG = 1

# CBOR tag for COSE_Sign
_COSE_SIGN_TAG = 98


# ---------------------------------------------------------------------------
# Internal COSE helpers
# ---------------------------------------------------------------------------


def _encode_protected(alg_id: int) -> bytes:
    """Encode a COSE protected header containing only the algorithm label."""
    return cbor2.dumps({_COSE_HEADER_ALG: alg_id})


def _build_sig_structure(
    body_protected: bytes,
    sign_protected: bytes,
    payload: bytes,
) -> bytes:
    """
    Build the Sig_Structure byte string per RFC 9052 §4.4.

    Sig_Structure = [
        context      : "Signature",
        body_protected,
        sign_protected,
        external_aad : b"",
        payload,
    ]
    """
    return cbor2.dumps(["Signature", body_protected, sign_protected, b"", payload])


# ---------------------------------------------------------------------------
# ML-KEM (Key Encapsulation Mechanism)
# ---------------------------------------------------------------------------


class KEMProvider:
    """
    Backward-compatible KEMProvider that delegates to the active KEMBackend.
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
        """
        Encrypt *data* using a hybrid approach.

        Returns::

            {
                'kem_ct': <b64>,
                'aes_ct': <b64>,
                'nonce':  <b64>,
                'tag':    <b64>,
                'algo':   'ML-KEM-768/AES-256-GCM',
            }
        """
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        kem_ct, shared_secret = KEMProvider.encapsulate(recipient_public_key)

        aesgcm = AESGCM(shared_secret[:32])
        nonce = os.urandom(12)
        ct_with_tag = aesgcm.encrypt(nonce, data, None)

        # cryptography appends the 16-byte tag at the end
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
    Backward-compatible facade that delegates to the active PQCBackend.
    This maintains API compatibility with existing code (identity.py etc.).
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
    Manages security levels based on task risk.
    Adjusts algorithm parameters based on the tool being executed.
    """

    @staticmethod
    def get_required_level(
        tool_name: str,
        args: Any = None,
        environment_risk: str = "standard",
    ) -> str:
        """
        Determine the required ML-DSA security level based on a risk matrix.

        Note: While this manager selects different variants (ML-DSA-44/65/87),
        the current IdentityManager implementation uses a single primary key pair
        for simplicity.  In a full production deployment, separate keys per
        security level would be managed to satisfy cryptographic isolation.
        """
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

        if (
            environment_risk == "high"
            or tool_name in high_risk_tools
            or is_sensitive_context
        ):
            return "ML-DSA-87"

        moderate_risk_tools = set(security_config.get("medium_risk_tools", []))
        if tool_name in moderate_risk_tools:
            return "ML-DSA-65"

        return "ML-DSA-44"


# ---------------------------------------------------------------------------
# Response Signer
# ---------------------------------------------------------------------------


class ResponseSigner:
    """
    Implements Bi-directional Verification.
    Signs the final output to prove it was derived from verified tool observations.
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


# ---------------------------------------------------------------------------
# Hybrid COSE Signer  (RFC 9052 COSE_Sign, tag 98)
# ---------------------------------------------------------------------------


class HybridSigner:
    """
    Hybrid Signatures (Classical + Post-Quantum) conforming to RFC 9052.

    Produces a ``COSE_Sign`` structure (CBOR tag 98) with two
    ``COSE_Signature`` entries:

    * Signer 0 – RSA-PKCS1v15-SHA256 (COSE alg ``-257``)
    * Signer 1 – ML-DSA-65 (COSE alg ``-48``)

    This implementation is intentionally independent of any COSE helper
    library so that custom (non-registered) algorithm identifiers are fully
    supported without monkey-patching.
    """

    @classmethod
    def create_hybrid_token(
        cls,
        payload: dict[str, Any],
        rsa_private_key_pem: bytes,
        pqc_private_key: bytes,
        variant: str = PQCProvider.DEFAULT_VARIANT,
    ) -> bytes:
        """
        Encode a ``COSE_Sign`` token signed by both RSA and ML-DSA.

        Parameters
        ----------
        payload:
            Arbitrary dict – will be serialised to CBOR.
        rsa_private_key_pem:
            PKCS#8 PEM-encoded RSA private key (bytes).
        pqc_private_key:
            Raw ML-DSA private key bytes.
        variant:
            ML-DSA variant name (default ``"ML-DSA-65"``).

        Returns
        -------
        bytes
            CBOR-encoded COSE_Sign message (CBOR tag 98).
        """
        payload_bytes = cbor2.dumps(payload)

        # Protected header of the outer COSE_Sign (no algorithm here; each
        # signer carries its own protected header)
        body_protected = cbor2.dumps({})  # empty for the outer message

        # --- Signer 0: RSA-PKCS1v15-SHA256 (alg = -257) ---
        rsa_sign_protected = _encode_protected(_COSE_ALG_RS256)
        rsa_tbs = _build_sig_structure(
            body_protected, rsa_sign_protected, payload_bytes
        )
        _rsa_key = load_pem_private_key(rsa_private_key_pem, password=None)
        if not isinstance(_rsa_key, RSAPrivateKey):
            raise TypeError("rsa_private_key_pem must encode an RSA private key")
        rsa_sig: bytes = _rsa_key.sign(rsa_tbs, padding.PKCS1v15(), hashes.SHA256())
        rsa_signature_entry: list[Any] = [rsa_sign_protected, {}, rsa_sig]

        # --- Signer 1: ML-DSA (alg = -48) ---
        # Store the variant name in the unprotected header so the verifier
        # knows which ML-DSA level to use.
        pqc_sign_protected = _encode_protected(_COSE_ALG_MLDSA)
        pqc_uhdr: dict[int | str, Any] = {
            # Label 4 = kid (key identifier) – we reuse it to carry the
            # variant string as an informal extension.
            4: variant.encode()
        }
        pqc_tbs = _build_sig_structure(
            body_protected, pqc_sign_protected, payload_bytes
        )
        pqc_sig = PQCProvider.sign(pqc_tbs, pqc_private_key, variant=variant)
        pqc_signature_entry = [pqc_sign_protected, pqc_uhdr, pqc_sig]

        # --- Assemble COSE_Sign ---
        cose_sign = cbor2.CBORTag(
            _COSE_SIGN_TAG,
            [
                body_protected,  # protected (outer)
                {},  # unprotected (outer)
                payload_bytes,  # payload
                [rsa_signature_entry, pqc_signature_entry],
            ],
        )
        return cbor2.dumps(cose_sign)  # type: ignore[no-any-return]

    @classmethod
    def verify_hybrid_token(
        cls,
        cose_token: bytes,
        rsa_public_key_pem: bytes,
        pqc_public_key_provider: Any = None,
    ) -> dict[str, Any] | None:
        """
        Verify both RSA and ML-DSA signatures in a ``COSE_Sign`` token.

        Parameters
        ----------
        cose_token:
            Bytes produced by :meth:`create_hybrid_token`.
        rsa_public_key_pem:
            PEM-encoded RSA public key.
        pqc_public_key_provider:
            Optional callable ``(variant: str) -> bytes`` that returns the
            ML-DSA public key for the given variant.  When *None*, falls back
            to ``IdentityManager._get_pqc_public_key_content``.

        Returns
        -------
        dict | None
            Decoded payload dict on success, ``None`` on any failure.
        """
        try:
            top = cbor2.loads(cose_token)

            # Unwrap CBOR tag 98 if present
            if isinstance(top, cbor2.CBORTag):
                if top.tag != _COSE_SIGN_TAG:
                    logger.error(
                        "Unexpected CBOR tag %d (expected %d)",
                        top.tag,
                        _COSE_SIGN_TAG,
                    )
                    return None
                structure = top.value
            else:
                structure = top

            if not isinstance(structure, list) or len(structure) != 4:
                logger.error("Malformed COSE_Sign structure")
                return None

            body_protected: bytes
            payload_bytes: bytes
            signatures: list[Any]
            body_protected, _uhdr, payload_bytes, signatures = structure

            if len(signatures) < 2:
                logger.warning(
                    "COSE_Sign has %d signer(s); hybrid requires at least 2",
                    len(signatures),
                )
                return None

            # ------------------------------------------------------------------
            # Signer 0: RSA-PKCS1v15-SHA256
            # ------------------------------------------------------------------
            rsa_entry = signatures[0]
            if not isinstance(rsa_entry, list) or len(rsa_entry) != 3:
                logger.error("Malformed RSA COSE_Signature entry")
                return None

            rsa_sign_protected: bytes
            rsa_sign_protected, _rsa_uhdr, rsa_sig = rsa_entry

            # Validate algorithm label
            rsa_phdr = cbor2.loads(rsa_sign_protected)
            if rsa_phdr.get(_COSE_HEADER_ALG) != _COSE_ALG_RS256:
                logger.error(
                    "RSA entry has unexpected alg %s", rsa_phdr.get(_COSE_HEADER_ALG)
                )
                return None

            rsa_tbs = _build_sig_structure(
                body_protected, rsa_sign_protected, payload_bytes
            )
            _rsa_pub = load_pem_public_key(rsa_public_key_pem)
            if not isinstance(_rsa_pub, RSAPublicKey):
                logger.error("rsa_public_key_pem does not encode an RSA public key")
                return None
            try:
                _rsa_pub.verify(rsa_sig, rsa_tbs, padding.PKCS1v15(), hashes.SHA256())
            except Exception as exc:
                logger.error("Classical (RSA) signature verification failed: %s", exc)
                return None

            # ------------------------------------------------------------------
            # Signer 1: ML-DSA
            # ------------------------------------------------------------------
            pqc_entry = signatures[1]
            if not isinstance(pqc_entry, list) or len(pqc_entry) != 3:
                logger.error("Malformed PQC COSE_Signature entry")
                return None

            pqc_sign_protected: bytes
            pqc_sign_protected, pqc_uhdr, pqc_sig = pqc_entry

            pqc_phdr = cbor2.loads(pqc_sign_protected)
            if pqc_phdr.get(_COSE_HEADER_ALG) != _COSE_ALG_MLDSA:
                logger.error(
                    "PQC entry has unexpected alg %s", pqc_phdr.get(_COSE_HEADER_ALG)
                )
                return None

            # Retrieve the variant from the kid field (label 4)
            variant_raw = pqc_uhdr.get(4, b"")
            if isinstance(variant_raw, bytes):
                variant = variant_raw.decode() or PQCProvider.DEFAULT_VARIANT
            else:
                variant = str(variant_raw) or PQCProvider.DEFAULT_VARIANT

            if pqc_public_key_provider is not None:
                pqc_pub: bytes = pqc_public_key_provider(variant)
            else:
                from llm_cli.security.identity import IdentityManager

                pqc_pub = IdentityManager._get_pqc_public_key_content(variant)

            pqc_tbs = _build_sig_structure(
                body_protected, pqc_sign_protected, payload_bytes
            )
            if not PQCProvider.verify(pqc_tbs, pqc_sig, pqc_pub, variant=variant):
                logger.error("Post-Quantum (ML-DSA) signature verification failed")
                return None

            logger.info("✅ Hybrid COSE Signature Verified (RSA + ML-DSA)")
            return cbor2.loads(payload_bytes)  # type: ignore[no-any-return]

        except Exception as exc:
            logger.error("COSE verification error: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Tool-result signing helper
# ---------------------------------------------------------------------------


def sign_tool_result(result_text: str) -> str | dict[str, str]:
    """
    Sign a tool result with PQC (ML-DSA) for Bi-directional Verification.

    Returns a dict with ``result``, ``pqc_signature``, ``verification_id``,
    and ``algorithm`` when signing succeeds, or the plain string on failure.
    The dict format is recognised and verified by
    ``tool_executor.execute_tool_call``.
    """
    import uuid

    try:
        from llm_cli.security.identity import IdentityManager

        pqc_priv = IdentityManager._get_pqc_private_key_content()
        verification_id = str(uuid.uuid4())
        signed = ResponseSigner.sign_response(
            response_text=result_text,
            source_verification_id=verification_id,
            private_key=pqc_priv,
        )
        return signed
    except Exception as exc:
        # Signing is best-effort; never block tool execution on crypto failure.
        logger.debug("Failed to sign tool result: %s", exc)
        return result_text
