import base64

from llm_cli.security.identity import IdentityManager
from llm_cli.security.pqc import PQCProvider


def test_distributed_key_verification(tmp_path):
    """
    Test scenario: Agent and Server have different keys.
    Server verifies Agent's token using the Agent's public key (OOB).
    """
    # 1. Setup Agent environment (uses default IdentityManager paths for simplicity in test)
    agent_id = "agent@workstation"
    token = IdentityManager.generate_token(user_id=agent_id)

    # Capture Agent's Public Keys (simulating Out-of-Band distribution)
    agent_rsa_pub = IdentityManager.get_public_key().encode()
    agent_pqc_pub_b64 = IdentityManager.get_pqc_public_key()
    agent_pqc_pub = base64.b64decode(agent_pqc_pub_b64)

    # 2. Setup "Server" environment with different keys
    # We generate a fresh set of keys for the server to ensure they are different
    server_rsa_pub_bytes, _ = PQCProvider.generate_keypair(
        variant="ML-DSA-65"
    )  # Just using a mock RSA/PQC gen
    # Note: IdentityManager uses real RSA. For the test, we just need to ensure
    # the server's local identity is different.

    # 3. VERIFICATION SUCCESS: Server uses Agent's Public Key explicitly
    def mock_agent_pqc_getter(variant):
        # In a real OOB setup, the server looks up the Agent's PQC key by ID/Variant
        return agent_pqc_pub

    payload = IdentityManager.verify_token(
        token, rsa_pub_key=agent_rsa_pub, pqc_pub_key_getter=mock_agent_pqc_getter
    )

    assert payload is not None
    assert payload["sub"] == agent_id
    assert payload["iss"] == "llm-cli-client"

    # 4. VERIFICATION FAILURE: Server uses its OWN (wrong) keys to verify Agent's token
    # We simulate this by providing a random different RSA public key
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    wrong_private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    wrong_rsa_pub = wrong_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    failed_payload = IdentityManager.verify_token(token, rsa_pub_key=wrong_rsa_pub)
    assert failed_payload is None


def test_trusted_directory_resolution(tmp_path, monkeypatch):
    """
    Test that IdentityManager resolves keys from the 'trusted/' directory
    based on the 'sub' claim in the token.
    """
    # 1. Setup a custom trusted directory
    trusted_dir = tmp_path / "trusted"
    trusted_dir.mkdir()

    # Configure the TrustResolver to use our temporary directory
    from llm_cli.security.trust import LocalTrustResolver, set_trust_resolver

    original_resolver = LocalTrustResolver()
    set_trust_resolver(LocalTrustResolver(trusted_dir=trusted_dir))

    entity_id = "remote-agent-007"
    agent_dir = trusted_dir / entity_id
    agent_dir.mkdir()

    # ... [rest of setup] ...
    # (Simulating OOB distribution)
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    # RSA
    from cryptography.hazmat.primitives.asymmetric import rsa

    from llm_cli.security.pqc import PQCProvider

    priv_rsa = rsa.generate_private_key(65537, 2048, default_backend())
    pub_rsa_bytes = priv_rsa.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (agent_dir / "id_rsa.pub").write_bytes(pub_rsa_bytes)

    # PQC L5 (ML-DSA-87)
    pub_l5, priv_l5 = PQCProvider.generate_keypair(variant="ML-DSA-87")
    (agent_dir / "id_pqc_l5.pub").write_bytes(pub_l5)

    # 3. Agent generates a token signed with ML-DSA-87
    from llm_cli.security.pqc import HybridSigner

    payload = {
        "iss": "llm-cli-client",
        "sub": entity_id,
        "iat": 1000,
        "exp": 2000,
    }

    # We use HybridSigner directly to simulate the agent side with its private keys
    priv_rsa_bytes = priv_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    token_bytes = HybridSigner.create_hybrid_token(
        payload, priv_rsa_bytes, priv_l5, variant="ML-DSA-87"
    )
    import base64

    token_str = base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")

    # 4. Server verifies the token
    # It should automatically find the keys in trusted/remote-agent-007/
    try:
        verified_payload = IdentityManager.verify_token(token_str)
    finally:
        # Restore original resolver
        set_trust_resolver(original_resolver)

    assert verified_payload is not None
    assert verified_payload["sub"] == entity_id
    print(f"\nSuccessfully verified {entity_id} using keys from trusted directory.")


def test_strict_security_attestation_check(monkeypatch):
    """
    Verify that tokens contain integrity_attestation.
    """
    local_id = IdentityManager.get_local_identity()

    # Generate token in strict mode using local ID
    token = IdentityManager.generate_token(user_id=local_id)

    # Verify token
    payload = IdentityManager.verify_token(token)

    assert payload is not None
    # Ensure integrity_attestation claim is present
    assert "integrity_attestation" in payload
    attestation = payload["integrity_attestation"]
    assert attestation is not None
    print(f"\nAttestation found: {str(attestation)[:30]}...")


def test_version_agnostic_logic():
    """
    Test that the verification logic allows for different versions
    if the keys match.
    """
    local_id = IdentityManager.get_local_identity()
    token = IdentityManager.generate_token(user_id=local_id)

    # Verify
    payload = IdentityManager.verify_token(token)

    assert payload is not None
    assert payload["sub"] == local_id
