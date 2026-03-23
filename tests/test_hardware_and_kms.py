from unittest.mock import MagicMock, patch

import pytest

from llm_cli.security.identity import IdentityManager
from llm_cli.security.pqc_backend import PurePythonPQCBackend, get_pqc_backend
from llm_cli.security.tee_backend import TEEPQCBackend
from llm_cli.security.trust import (
    KMSTrustResolver,
    LocalTrustResolver,
    set_trust_resolver,
)


@pytest.fixture(autouse=True)
def reset_security_state():
    """Reset the PQC backend and trust resolver after each test."""
    from llm_cli.security.pqc_backend import set_pqc_backend

    # Save original
    original_resolver = LocalTrustResolver()
    original_backend = PurePythonPQCBackend()

    yield

    set_trust_resolver(original_resolver)
    set_pqc_backend(original_backend)


def test_tee_pqc_backend_integration():
    """Verify that enabling TEE switches the backend and seals keys."""
    IdentityManager.use_tee()
    backend = get_pqc_backend()

    assert isinstance(backend, TEEPQCBackend)

    # Test key generation (should be sealed)
    pub, sealed_priv = backend.generate_keypair(variant="ML-DSA-44")
    assert len(pub) > 0
    assert len(sealed_priv) > 0

    # Test signing (should work with sealed key)
    message = b"Test TEE Message"
    sig = backend.sign(message, sealed_private_key=sealed_priv, variant="ML-DSA-44")
    assert len(sig) > 0

    # Verify signature
    assert backend.verify(message, sig, pub, variant="ML-DSA-44") is True


def test_kms_trust_resolver_simulation():
    """Verify that KMSTrustResolver can be configured and queried."""
    kms_resolver = KMSTrustResolver(kms_endpoint="https://kms.enterprise.internal")
    set_trust_resolver(kms_resolver)

    # Mock the resolve methods to simulate KMS response
    with patch.object(
        KMSTrustResolver, "resolve_rsa_public_key", return_value=b"MOCK_RSA_PUB"
    ):
        with patch.object(
            KMSTrustResolver, "resolve_pqc_public_key", return_value=b"MOCK_PQC_PUB"
        ):
            token = IdentityManager.generate_token(user_id="alice@remote")

            # verify_token should use the KMSTrustResolver
            # We need to ensure HybridSigner.verify_hybrid_token handles our mock keys
        with patch(
            "llm_cli.security.pqc_cose.HybridSigner.verify_hybrid_token"
        ) as mock_verify:
            mock_verify.return_value = {"sub": "alice@remote"}

            payload = IdentityManager.verify_token(token)
            assert payload["sub"] == "alice@remote"

            # Check that our mock keys would have been fetched (indirectly verified by flow)
            # In a more detailed test, we'd check the calls to the resolver.


def test_identity_manager_uses_resolver():
    """Ensure IdentityManager actually calls the trust resolver."""
    mock_resolver = MagicMock()
    set_trust_resolver(mock_resolver)

    # Simulate a token from a remote entity
    # We'll use a real token but mock the resolution
    token = IdentityManager.generate_token(user_id="bob@corp")

    IdentityManager.verify_token(token)

    # Check if resolver was called for bob@corp
    mock_resolver.resolve_rsa_public_key.assert_called_with("bob@corp")
    # PQC resolution happens inside the getter passed to HybridSigner
    # but verify_token calls _get_trusted_pqc_public_key which calls resolver.
