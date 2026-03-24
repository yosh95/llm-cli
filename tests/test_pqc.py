import base64
import json

import pytest

from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier
from llm_cli.security.pqc import PQCAgilityManager, PQCProvider
from llm_cli.security.pqc_cose import HybridSigner


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

    payload = {"sub": "test_user", "pqc": True}

    # Create hybrid token
    hybrid_token = HybridSigner.create_hybrid_token(payload, rsa_priv, pqc_priv)
    assert isinstance(hybrid_token, bytes)
    assert len(hybrid_token) > 0

    # Verify hybrid token
    verified_payload = HybridSigner.verify_hybrid_token(
        hybrid_token, rsa_pub, lambda _: pqc_pub
    )
    assert verified_payload is not None
    assert verified_payload["sub"] == "test_user"
    assert "roles" not in verified_payload


def test_identity_manager_integration(tmp_path, monkeypatch):
    """Test IdentityManager's PQC integration."""
    # Use temporary directory for keys
    key_dir = tmp_path / "keys"
    monkeypatch.setattr("llm_cli.security.identity.IdentityManager._KEY_DIR", key_dir)
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._TRUSTED_DIR", key_dir / "trusted"
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PRIVATE_KEY_PATH",
        key_dir / "id_rsa",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PUBLIC_KEY_PATH",
        key_dir / "id_rsa.pub",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_PATH",
        key_dir / "id_pqc_l3.key",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_PATH",
        key_dir / "id_pqc_l3.pub",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_L2_PATH",
        key_dir / "id_pqc_l2.key",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_L2_PATH",
        key_dir / "id_pqc_l2.pub",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_L5_PATH",
        key_dir / "id_pqc_l5.key",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_L5_PATH",
        key_dir / "id_pqc_l5.pub",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_KEM_PRIVATE_KEY_PATH",
        key_dir / "id_kem.key",
    )
    monkeypatch.setattr(
        "llm_cli.security.identity.IdentityManager._PQC_KEM_PUBLIC_KEY_PATH",
        key_dir / "id_kem.pub",
    )

    # Use local identity for the test to ensure fallback works without trusted directory entry
    local_id = IdentityManager.get_local_identity()
    token = IdentityManager.generate_token(user_id=local_id)
    assert isinstance(token, str)

    # Verify token
    payload = IdentityManager.verify_token(token)
    assert payload is not None
    assert payload["sub"] == local_id
    assert "roles" not in payload
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
    audit_log_path = tmp_path / "audit.jsonl"

    monkeypatch.setattr("llm_cli.security.identity.KEY_DIR", key_dir)
    monkeypatch.setattr(
        "llm_cli.security.integrity.IntegrityVerifier.MANIFEST_PATH", manifest_path
    )
    monkeypatch.setattr("llm_cli.consts.AUDIT_LOG_PATH", audit_log_path)
    monkeypatch.setattr(
        "llm_cli.security.integrity.IntegrityVerifier.CRITICAL_PATTERNS",
        ["llm_cli/apps/mcp_server.py"],
    )

    verifier = IntegrityVerifier(root_path)

    # 1. Establish trust (Admin Action) - will sign with PQC
    assert verifier.rebuild_manifest() is True
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


# ---------------------------------------------------------------------------
# PQCAgilityManager – tool name / risk-level mapping
# ---------------------------------------------------------------------------


class TestPQCAgilityManager:
    """Verify that PQCAgilityManager returns the correct ML-DSA variant for each
    tool name and that no stale/incorrect tool names slip back in."""

    @pytest.fixture(autouse=True)
    def _patch_config(self, monkeypatch):
        """Provide a minimal config so the manager does not hit the filesystem."""
        monkeypatch.setattr(
            "llm_cli.clients.config.config_manager.load_config",
            lambda: {
                "security": {
                    "scaling_patterns": [],
                    "blocked_paths": [],
                    "high_risk_tools": [
                        "execute_python",
                        "edit_file",
                        "create_or_overwrite_file",
                    ],
                    "medium_risk_tools": [
                        "read_file_content",
                        "list_files_in_directory",
                        "search_files",
                        "search_web",
                        "read_url_content",
                    ],
                }
            },
        )

    def test_high_risk_tools_use_ml_dsa_87(self):
        high_risk = [
            "execute_python",
            "edit_file",
            "create_or_overwrite_file",
        ]
        for tool in high_risk:
            level = PQCAgilityManager.get_required_level(tool)
            assert level == "ML-DSA-87", (
                f"Expected ML-DSA-87 for high-risk tool '{tool}', got {level}"
            )

    def test_moderate_risk_tools_use_ml_dsa_65(self):
        """Ensure all tools registered in moderate_risk_tools use ML-DSA-65.

        This test was added to catch the historical bug where 'read_file'
        (non-existent) was used instead of the actual tool name 'read_file_content'.
        """
        moderate_risk = [
            "read_file_content",  # actual registered tool name
            "list_files_in_directory",
            "search_files",
            "search_web",
            "read_url_content",
        ]
        for tool in moderate_risk:
            level = PQCAgilityManager.get_required_level(tool)
            assert level == "ML-DSA-65", (
                f"Expected ML-DSA-65 for moderate-risk tool '{tool}', got {level}"
            )

    def test_stale_tool_name_read_file_is_low_risk(self):
        """'read_file' is NOT a registered tool name and must NOT be treated as
        moderate-risk after the fix.  It should fall through to ML-DSA-44."""
        level = PQCAgilityManager.get_required_level("read_file")
        assert level == "ML-DSA-44", (
            f"Stale tool name 'read_file' should be low-risk (ML-DSA-44), got {level}"
        )

    def test_low_risk_unknown_tool_uses_ml_dsa_44(self):
        level = PQCAgilityManager.get_required_level("some_unknown_tool")
        assert level == "ML-DSA-44"

    def test_sensitive_context_escalates_to_ml_dsa_87(self, monkeypatch):
        """If args contain a sensitive pattern the level should escalate.

        We override the config fixture to include '.ssh/' as a scaling pattern,
        which is the default value in defaults.toml.  Without a matching pattern
        in 'scaling_patterns' the sensitive-context branch cannot fire.
        """
        monkeypatch.setattr(
            "llm_cli.clients.config.config_manager.load_config",
            lambda: {"security": {"scaling_patterns": [".ssh/"], "blocked_paths": []}},
        )
        level = PQCAgilityManager.get_required_level(
            "read_file_content", args={"path": "/home/user/.ssh/id_rsa"}
        )
        assert level == "ML-DSA-87"
