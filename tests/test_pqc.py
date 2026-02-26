import base64
import json

from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier
from llm_cli.security.pqc import HybridSigner, PQCProvider


def test_pqc_provider_key_gen():
    """Test ML-DSA key generation."""
    pub, priv = PQCProvider.generate_keypair()
    assert isinstance(pub, bytes)
    assert isinstance(priv, bytes)
    assert len(pub) > 0
    assert len(priv) > 0


def test_pqc_sign_verify():
    """Test signing and verification."""
    pub, priv = PQCProvider.generate_keypair()
    message = b"Test message for PQC"

    signature = PQCProvider.sign(message, priv)
    assert isinstance(signature, bytes)
    assert len(signature) > 0

    # Verify correct signature
    assert PQCProvider.verify(message, signature, pub) is True

    # Negative tests
    # Verify wrong message
    assert PQCProvider.verify(b"Wrong message", signature, pub) is False
    # Verify wrong signature
    assert PQCProvider.verify(message, b"wrong" * 10, pub) is False


def test_hybrid_signer_token():
    """Test Hybrid RSA + ML-DSA token creation and verification."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Setup classical RSA key
    rsa_priv_obj = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_priv = rsa_priv_obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    rsa_pub = rsa_priv_obj.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Setup PQC key
    pqc_pub, pqc_priv = PQCProvider.generate_keypair()

    payload = {"sub": "test_user", "roles": ["admin"]}

    # Create hybrid token
    hybrid_token = HybridSigner.create_hybrid_token(payload, rsa_priv, pqc_priv)
    assert isinstance(hybrid_token, str)
    assert hybrid_token.count(".") == 3  # JWT (2 dots) + PQC (1 dot) = 3 dots

    # Verify hybrid token
    verified_payload = HybridSigner.verify_hybrid_token(hybrid_token, rsa_pub, pqc_pub)
    assert verified_payload is not None
    assert verified_payload["sub"] == "test_user"
    assert verified_payload["roles"] == ["admin"]


def test_identity_manager_integration(tmp_path, monkeypatch):
    """Test IdentityManager's PQC integration."""
    # Use temporary directory for keys
    key_dir = tmp_path / "keys"
    monkeypatch.setattr("llm_cli.security.identity.KEY_DIR", key_dir)

    # Generate token
    token = IdentityManager.generate_token(
        user_id="pqc_tester", roles=["security_audit"]
    )
    assert isinstance(token, str)

    # Verify token
    payload = IdentityManager.verify_token(token)
    assert payload is not None
    assert payload["sub"] == "pqc_tester"
    assert payload["roles"] == ["security_audit"]
    assert payload.get("pqc") is True


def test_integrity_verifier_pqc(tmp_path, monkeypatch):
    """Test IntegrityVerifier with PQC-signed manifest."""
    # Setup environment
    root_path = tmp_path / "project"
    root_path.mkdir()

    # Create a critical file
    critical_file = root_path / "llm_cli/apps/mcp_server.py"
    critical_file.parent.mkdir(parents=True)
    critical_file.write_text("print('hello')")

    # Mock KEY_DIR and MANIFEST_PATH
    key_dir = tmp_path / "keys"
    manifest_path = tmp_path / "integrity_manifest.json"

    monkeypatch.setattr("llm_cli.security.identity.KEY_DIR", key_dir)
    monkeypatch.setattr(
        "llm_cli.security.integrity.IntegrityVerifier.MANIFEST_PATH", manifest_path
    )
    monkeypatch.setattr(
        "llm_cli.security.integrity.IntegrityVerifier.CRITICAL_FILES",
        ["llm_cli/apps/mcp_server.py"],
    )

    verifier = IntegrityVerifier(root_path)

    # 1. Establish trust (TOFU) - will sign with PQC
    assert verifier.verify() is True
    assert manifest_path.exists()

    with manifest_path.open() as f:
        data = json.load(f)
        assert "pqc_signature" in data
        assert "hashes" in data
        assert data["pqc_algorithm"] == PQCProvider.ALGORITHM_NAME

    # 2. Verify integrity
    assert verifier.verify() is True

    # 3. Tamper with file
    critical_file.write_text("print('tampered')")
    assert verifier.verify() is False

    # 4. Tamper with manifest signature (but restore file)
    critical_file.write_text("print('hello')")
    with manifest_path.open("r") as f:
        data = json.load(f)
    data["pqc_signature"] = base64.b64encode(b"invalid_signature").decode()
    with manifest_path.open("w") as f:
        json.dump(data, f)

    assert verifier.verify() is False
