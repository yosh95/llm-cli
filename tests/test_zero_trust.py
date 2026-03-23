import json
from unittest.mock import patch

import pytest

from llm_cli.security.audit import log_audit
from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier
from llm_cli.security.policy import PolicyEngine

# --- Identity Tests ---


@pytest.fixture
def identity_manager(tmp_path):
    """Fixture to set up temporary key directory for IdentityManager."""
    keys_dir = tmp_path / "keys"
    with (
        patch("llm_cli.security.identity.IdentityManager._KEY_DIR", keys_dir),
        patch(
            "llm_cli.security.identity.IdentityManager._TRUSTED_DIR",
            keys_dir / "trusted",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PRIVATE_KEY_PATH",
            keys_dir / "id_rsa",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PUBLIC_KEY_PATH",
            keys_dir / "id_rsa.pub",
        ),
        # Default (L3)
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_PATH",
            keys_dir / "id_pqc_l3.key",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_PATH",
            keys_dir / "id_pqc_l3.pub",
        ),
        # L2 (ML-DSA-44)
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_L2_PATH",
            keys_dir / "id_pqc_l2.key",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_L2_PATH",
            keys_dir / "id_pqc_l2.pub",
        ),
        # L5 (ML-DSA-87)
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_L5_PATH",
            keys_dir / "id_pqc_l5.key",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_L5_PATH",
            keys_dir / "id_pqc_l5.pub",
        ),
        # KEM (ML-KEM-768)
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_KEM_PRIVATE_KEY_PATH",
            keys_dir / "id_kem.key",
        ),
        patch(
            "llm_cli.security.identity.IdentityManager._PQC_KEM_PUBLIC_KEY_PATH",
            keys_dir / "id_kem.pub",
        ),
    ):
        yield IdentityManager


def test_identity_key_generation(identity_manager):
    """Test automatic RSA key generation."""
    assert not identity_manager._PRIVATE_KEY_PATH.exists()

    # Trigger key generation
    token = identity_manager.generate_token()

    assert identity_manager._PRIVATE_KEY_PATH.exists()
    assert identity_manager._PUBLIC_KEY_PATH.exists()
    assert token is not None


def test_token_verification(identity_manager):
    """Test token signing and verification flow."""
    local_id = IdentityManager.get_local_identity()
    token = identity_manager.generate_token(user_id=local_id, audience="server1")

    # Verify with correct audience
    payload = identity_manager.verify_token(token, expected_audience="server1")
    assert payload is not None
    assert payload["sub"] == local_id
    assert payload["aud"] == "server1"

    # Verify with wrong audience
    payload_wrong = identity_manager.verify_token(token, expected_audience="server2")
    assert payload_wrong is None  # Should fail


# --- Policy Engine Tests (ABAC) ---


@pytest.fixture
def policy_engine(tmp_path, monkeypatch):
    # Align ABAC scope tests with path normalization + validate_path() sandboxing.
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    config = {
        "allowed_paths": ["."],
        "high_risk_tools": ["edit_file"],
        "medium_risk_tools": ["read_file_content"],
        "blocked_paths": ["/etc/passwd"],
    }
    return PolicyEngine(config)


def test_policy_scope_enforcement(policy_engine):
    # HIGH RISK tool requires PQC proof
    context = {"user_id": "dev_user", "has_pqc_proof": True}

    # Allowed path
    assert policy_engine.evaluate("edit_file", {"path": "./main.py"}, context) is True

    # Disallowed path (Out of scope)
    # Using a path that is clearly outside the project_dir (which is now CWD)
    assert (
        policy_engine.evaluate("edit_file", {"path": "/tmp/outside.txt"}, context)
        is False
    )


def test_pqc_proof_requirement(policy_engine):
    # HIGH RISK tool without PQC proof should fail even if path is okay
    context = {"user_id": "dev_user", "has_pqc_proof": False}
    assert policy_engine.evaluate("edit_file", {"path": "./main.py"}, context) is False


def test_global_guardrails(policy_engine):
    context = {"user_id": "admin", "has_pqc_proof": True}

    # Blocked path should be blocked globally
    assert (
        policy_engine.evaluate("read_file_content", {"path": "/etc/passwd"}, context)
        is False
    )


# --- Audit & Integrity Tests ---


def test_audit_log_hashing(tmp_path):
    """Test that audit logs are chained with hashes."""
    log_file = tmp_path / "audit.jsonl"

    with patch("llm_cli.security.audit.AUDIT_LOG_PATH", log_file):
        # Log entry 1
        log_audit("tool1", {"arg": 1}, "result1")
        # Log entry 2
        log_audit("tool2", {"arg": 2}, "result2")

    assert log_file.exists()
    lines = log_file.read_text().splitlines()
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])

    # Genesis hash
    assert entry1["prev_hash"] == "0" * 64
    # Chain integrity
    assert entry2["prev_hash"] == entry1["hash"]


def test_integrity_audit_verification(tmp_path):
    """Test that IntegrityVerifier detects log tampering."""
    log_file = tmp_path / "audit.jsonl"

    # Create valid logs
    with patch("llm_cli.security.audit.AUDIT_LOG_PATH", log_file):
        log_audit("tool1", {}, "ok")
        log_audit("tool2", {}, "ok")

    verifier = IntegrityVerifier(tmp_path)

    # Mocking the hardcoded path in integrity.py is tricky, so we'll test the logic directly
    # if we can, or we mock the method that gets the path.
    # Since verify_audit_log uses Path("~/.local..."), we need to mock Path in integrity.py or use a better way.
    # For this test, let's verify the file manually to prove the concept,
    # or rely on the fact that we implemented verify_audit_log to read from a specific location.

    # Let's mock Path inside integrity.py's verify_audit_log scope context if possible,
    # but easier to just use the logic we wrote.

    # Simulate tampering: Modify first line
    lines = log_file.read_text().splitlines()
    entry1 = json.loads(lines[0])
    entry1["tool"] = "hacked_tool"  # malicious change
    # Re-calculate hash to fake a single entry, but chain will break next
    # Or just write raw JSON without updating hash
    lines[0] = json.dumps(entry1)
    log_file.write_text("\n".join(lines))

    # Now verify
    # We need to monkeypatch the path inside verify_audit_log
    # Since it imports locally from llm_cli.consts, we patch that.
    with patch("llm_cli.consts.AUDIT_LOG_PATH", log_file):
        assert verifier.verify_audit_log() is False
