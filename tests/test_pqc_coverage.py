import base64
from unittest.mock import MagicMock, patch

from llm_cli.security.pqc import (
    AuditAnchoring,
    HybridSigner,
    PQCAgilityManager,
    PQCProvider,
    ResponseSigner,
)


def test_pqc_provider_is_available():
    assert PQCProvider.is_available() is True


def test_pqc_provider_verify_exception():
    """Test that verify returns False on exception."""
    # Invalid public key should cause an exception in dilithium-py
    assert PQCProvider.verify(b"msg", b"sig", b"invalid_pubkey") is False


def test_pqc_agility_manager_levels():
    """Test PQCAgilityManager.get_required_level with various scenarios."""

    with patch("llm_cli.clients.config._load_config_from_file") as mock_load:
        # Default config
        mock_load.return_value = {}

        # High risk tools
        assert (
            PQCAgilityManager.get_required_level("execute_shell_command") == "ML-DSA-87"
        )
        assert PQCAgilityManager.get_required_level("edit_file") == "ML-DSA-87"

        # Sensitive context in args
        # /etc/shadow is not in default patterns: [".ssh/", ".env", "config", "credential", "password", "sudo", "rm -rf"]
        # read_file is a moderate tool, so it returns ML-DSA-65
        assert (
            PQCAgilityManager.get_required_level(
                "read_file", args={"path": "/etc/shadow"}
            )
            == "ML-DSA-65"
        )

        # Default patterns: [".ssh/", ".env", "config", "credential", "password", "sudo", "rm -rf"]
        assert (
            PQCAgilityManager.get_required_level("read_file", args="sudo something")
            == "ML-DSA-87"
        )
        assert (
            PQCAgilityManager.get_required_level("read_file", args=".ssh/id_rsa")
            == "ML-DSA-87"
        )

        # Environment risk
        assert (
            PQCAgilityManager.get_required_level("read_file", environment_risk="high")
            == "ML-DSA-87"
        )

        # Moderate risk tools
        assert PQCAgilityManager.get_required_level("read_file") == "ML-DSA-65"
        assert (
            PQCAgilityManager.get_required_level("list_files_in_directory")
            == "ML-DSA-65"
        )

        # Standard tool
        assert PQCAgilityManager.get_required_level("get_weather") == "ML-DSA-44"

        # Custom config with scaling patterns and blocked paths
        mock_load.return_value = {
            "security": {
                "scaling_patterns": ["critical_file"],
                "blocked_paths": ["/secret"],
            }
        }
        assert (
            PQCAgilityManager.get_required_level("read_file", args="critical_file.txt")
            == "ML-DSA-87"
        )
        assert (
            PQCAgilityManager.get_required_level("read_file", args="/secret/data")
            == "ML-DSA-87"
        )
        # .ssh should no longer be sensitive as we overwrote scaling_patterns?
        # Actually line 87: security_config.get("scaling_patterns", [...])
        # So it DOES overwrite the defaults if present.
        assert (
            PQCAgilityManager.get_required_level("read_file", args=".ssh/config")
            == "ML-DSA-65"
        )  # Moderate tool, not sensitive context


def test_response_signer():
    """Test ResponseSigner.sign_response."""
    pub, priv = PQCProvider.generate_keypair()
    response_text = "Analysis complete."
    verification_id = "exec_123"

    signed = ResponseSigner.sign_response(response_text, verification_id, priv)

    assert signed["response"] == response_text
    assert signed["verification_id"] == verification_id
    assert "pqc_signature" in signed
    assert signed["algorithm"] == PQCProvider.DEFAULT_VARIANT

    # Verify the signature
    sig = base64.urlsafe_b64decode(signed["pqc_signature"])
    message = f"{verification_id}:{response_text}".encode()
    assert PQCProvider.verify(message, sig, pub) is True


def test_audit_anchoring():
    """Test AuditAnchoring.generate_anchor_root."""
    # Empty
    assert AuditAnchoring.generate_anchor_root([]) == "0" * 64

    # Single entry
    logs = [{"event": "login", "user": "alice"}]
    root1 = AuditAnchoring.generate_anchor_root(logs)
    assert len(root1) == 64

    # Two entries
    logs.append({"event": "read", "file": "data.txt"})
    root2 = AuditAnchoring.generate_anchor_root(logs)
    assert len(root2) == 64
    assert root2 != root1

    # Three entries (odd number, tests duplication logic)
    logs.append({"event": "logout"})
    root3 = AuditAnchoring.generate_anchor_root(logs)
    assert len(root3) == 64
    assert root3 != root2


def test_hybrid_signer_init():
    """Test HybridSigner constructor."""
    mock_classical = MagicMock()
    signer = HybridSigner(mock_classical, PQCProvider)
    assert signer.classical == mock_classical
    assert signer.pqc == PQCProvider


def test_hybrid_signer_verify_failures():
    """Test HybridSigner.verify_hybrid_token failure modes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Setup keys
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
    pqc_pub, pqc_priv = PQCProvider.generate_keypair()

    # 1. Invalid format (not 4 parts)
    assert (
        HybridSigner.verify_hybrid_token("part1.part2.part3", rsa_pub, pqc_pub) is None
    )

    # 2. Invalid classical signature
    valid_token = HybridSigner.create_hybrid_token({"sub": "user"}, rsa_priv, pqc_priv)
    parts = valid_token.split(".")
    # Tamper with JWT payload part
    bad_payload = base64.b64encode(b'{"sub": "attacker"}').decode().rstrip("=")
    tampered_classical = f"{parts[0]}.{bad_payload}.{parts[2]}.{parts[3]}"
    assert (
        HybridSigner.verify_hybrid_token(tampered_classical, rsa_pub, pqc_pub) is None
    )

    # 3. Invalid PQC signature
    # Tamper with PQC part
    tampered_pqc = f"{parts[0]}.{parts[1]}.{parts[2]}.{base64.urlsafe_b64encode(b'bad_sig').decode()}"
    assert HybridSigner.verify_hybrid_token(tampered_pqc, rsa_pub, pqc_pub) is None

    # 4. PQC verification failed (right format but wrong signature)
    wrong_pqc_sig = (
        base64.urlsafe_b64encode(b"0" * 2420).decode().rstrip("=")
    )  # Large enough to be valid format maybe
    tampered_pqc_2 = f"{parts[0]}.{parts[1]}.{parts[2]}.{wrong_pqc_sig}"
    assert HybridSigner.verify_hybrid_token(tampered_pqc_2, rsa_pub, pqc_pub) is None
