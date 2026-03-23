"""
Hybrid Signature implementation (RSA + ML-DSA) conforming to COSE (RFC 9052).
This module provides the HybridSigner class and associated CBOR helpers.
"""

import logging
from typing import Any, cast

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

# Avoid circularity: only import what we need
from llm_cli.security.pqc_backend import get_pqc_backend

# ---------------------------------------------------------------------------
# COSE algorithm identifiers (RFC 9052 §9.1 + custom registration)
# ---------------------------------------------------------------------------
_COSE_ALG_RS256 = -257  # RSASSA-PKCS1-v1_5 with SHA-256
_COSE_ALG_MLDSA = -48  # ML-DSA-65 (custom / IANA pending)

# COSE header label for Algorithm (RFC 9052 §3.1)
_COSE_HEADER_ALG = 1

# CBOR tag for COSE_Sign
_COSE_SIGN_TAG = 98

logger = logging.getLogger(__name__)


def _encode_protected(alg_id: int) -> bytes:
    """Encode a COSE protected header containing only the algorithm label."""
    return cbor2.dumps({_COSE_HEADER_ALG: alg_id})


def _build_sig_structure(
    body_protected: bytes,
    sign_protected: bytes,
    payload: bytes,
) -> bytes:
    """Build the Sig_Structure byte string per RFC 9052 §4.4."""
    return cbor2.dumps(["Signature", body_protected, sign_protected, b"", payload])


class HybridSigner:
    """
    Hybrid Signatures (Classical + Post-Quantum) conforming to RFC 9052.

    Produces a ``COSE_Sign`` structure (CBOR tag 98) with two
    ``COSE_Signature`` entries:
    * Signer 0 – RSA-PKCS1v15-SHA256 (COSE alg ``-257``)
    * Signer 1 – ML-DSA-65 (COSE alg ``-48``)
    """

    @classmethod
    def create_hybrid_token(
        cls,
        payload: dict[str, Any],
        rsa_private_key_pem: bytes,
        pqc_private_key: bytes,
        variant: str = "ML-DSA-65",
    ) -> bytes:
        """Encode a ``COSE_Sign`` token signed by both RSA and ML-DSA."""
        payload_bytes = cbor2.dumps(payload)
        body_protected = cbor2.dumps({})

        # --- Signer 0: RSA ---
        rsa_sign_protected = _encode_protected(_COSE_ALG_RS256)
        rsa_tbs = _build_sig_structure(
            body_protected, rsa_sign_protected, payload_bytes
        )
        _rsa_key = load_pem_private_key(rsa_private_key_pem, password=None)
        if not isinstance(_rsa_key, RSAPrivateKey):
            raise TypeError("rsa_private_key_pem must encode an RSA private key")
        rsa_sig: bytes = _rsa_key.sign(rsa_tbs, padding.PKCS1v15(), hashes.SHA256())
        rsa_signature_entry: list[Any] = [rsa_sign_protected, {}, rsa_sig]

        # --- Signer 1: ML-DSA ---
        pqc_sign_protected = _encode_protected(_COSE_ALG_MLDSA)
        pqc_uhdr: dict[int | str, Any] = {4: variant.encode()}
        pqc_tbs = _build_sig_structure(
            body_protected, pqc_sign_protected, payload_bytes
        )
        pqc_sig = get_pqc_backend().sign(pqc_tbs, pqc_private_key, variant)
        pqc_signature_entry = [pqc_sign_protected, pqc_uhdr, pqc_sig]

        # --- Assemble COSE_Sign ---
        cose_sign = cbor2.CBORTag(
            _COSE_SIGN_TAG,
            [
                body_protected,
                {},
                payload_bytes,
                [rsa_signature_entry, pqc_signature_entry],
            ],
        )
        return cbor2.dumps(cose_sign)

    @classmethod
    def verify_hybrid_token(
        cls,
        cose_token: bytes,
        rsa_public_key_pem: bytes,
        pqc_public_key_provider: Any = None,
    ) -> dict[str, Any] | None:
        """Verify both RSA and ML-DSA signatures in a ``COSE_Sign`` token."""
        try:
            top = cbor2.loads(cose_token)
            if isinstance(top, cbor2.CBORTag):
                if top.tag != _COSE_SIGN_TAG:
                    return None
                structure = top.value
            else:
                structure = top

            if not isinstance(structure, list) or len(structure) != 4:
                return None

            body_protected, _uhdr, payload_bytes, signatures = structure
            if len(signatures) < 2:
                return None

            # Signer 0: RSA
            rsa_entry = signatures[0]
            rsa_sign_protected, _rsa_uhdr, rsa_sig = rsa_entry
            rsa_phdr = cbor2.loads(rsa_sign_protected)
            if rsa_phdr.get(_COSE_HEADER_ALG) != _COSE_ALG_RS256:
                return None

            rsa_tbs = _build_sig_structure(
                body_protected, rsa_sign_protected, payload_bytes
            )
            _rsa_pub = load_pem_public_key(rsa_public_key_pem)
            if not isinstance(_rsa_pub, RSAPublicKey):
                return None
            _rsa_pub.verify(rsa_sig, rsa_tbs, padding.PKCS1v15(), hashes.SHA256())

            # Signer 1: ML-DSA
            pqc_entry = signatures[1]
            pqc_sign_protected, pqc_uhdr, pqc_sig = pqc_entry
            pqc_phdr = cbor2.loads(pqc_sign_protected)
            if pqc_phdr.get(_COSE_HEADER_ALG) != _COSE_ALG_MLDSA:
                return None

            variant_raw = pqc_uhdr.get(4, b"")
            variant = (
                variant_raw.decode()
                if isinstance(variant_raw, bytes)
                else str(variant_raw)
            ) or "ML-DSA-65"

            if pqc_public_key_provider is not None:
                pqc_pub: bytes = pqc_public_key_provider(variant)
            else:
                from llm_cli.security.identity import IdentityManager

                pqc_pub = IdentityManager._get_pqc_public_key_content(variant)

            pqc_tbs = _build_sig_structure(
                body_protected, pqc_sign_protected, payload_bytes
            )
            if not get_pqc_backend().verify(pqc_tbs, pqc_sig, pqc_pub, variant):
                return None

            return cast(dict[str, Any], cbor2.loads(payload_bytes))
        except Exception as exc:
            logger.error("COSE verification error: %s", exc)
            return None
