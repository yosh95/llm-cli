import time

import jwt

from llm_cli.security.audit import log_audit
from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier
from llm_cli.security.policy import PolicyEngine


class TestIdentityManager:
    def test_generate_and_verify_token(self):
        user_id = "test_user"
        roles = ["admin"]
        token = IdentityManager.generate_token(user_id, roles)
        assert isinstance(token, str)

        payload = IdentityManager.verify_token(token)
        assert payload is not None
        assert payload["sub"] == user_id
        assert payload["roles"] == roles
        assert payload["iss"] == "llm-cli-client"

    def test_verify_invalid_token(self):
        assert IdentityManager.verify_token("invalid.token.here") is None

    def test_verify_expired_token(self):
        # Manually create an expired token
        private_key = IdentityManager._get_private_key_content()
        payload = {
            "iss": "llm-cli-client",
            "sub": "user",
            "iat": time.time() - 7200,
            "exp": time.time() - 3600,
            "roles": ["user"],
        }
        token = jwt.encode(payload, private_key, algorithm="RS256")
        assert IdentityManager.verify_token(token) is None

    def test_get_current_context(self):
        context = IdentityManager.get_current_context()
        assert "authorization" in context
        assert "trace_id" in context
        assert context["authorization"].startswith("Bearer ")


class TestIntegrityVerifier:
    def test_verify_success(self, tmp_path, monkeypatch):
        # Create dummy critical files
        # We need to recreate the directory structure expected by IntegrityVerifier
        # The verifier takes a base_path.

        # Override critical files list for testing to avoid creating deep structure
        saved_critical_files = IntegrityVerifier.CRITICAL_FILES
        saved_manifest_path = IntegrityVerifier.MANIFEST_PATH

        IntegrityVerifier.CRITICAL_FILES = ["test_file.py"]
        IntegrityVerifier.MANIFEST_PATH = tmp_path / "integrity_manifest.json"

        # Mock audit log path to avoid checking system's real audit log
        monkeypatch.setattr("llm_cli.consts.AUDIT_LOG_PATH", tmp_path / "audit.jsonl")

        try:
            (tmp_path / "test_file.py").write_text("dummy content")
            verifier = IntegrityVerifier(tmp_path)
            assert verifier.verify() is True
        finally:
            IntegrityVerifier.CRITICAL_FILES = saved_critical_files
            IntegrityVerifier.MANIFEST_PATH = saved_manifest_path

    def test_verify_missing_file(self, tmp_path, monkeypatch):
        saved_critical_files = IntegrityVerifier.CRITICAL_FILES
        saved_manifest_path = IntegrityVerifier.MANIFEST_PATH

        IntegrityVerifier.CRITICAL_FILES = ["test_file.py", "missing.py"]
        IntegrityVerifier.MANIFEST_PATH = tmp_path / "integrity_manifest.json"

        # Mock audit log path to avoid checking system's real audit log
        monkeypatch.setattr("llm_cli.consts.AUDIT_LOG_PATH", tmp_path / "audit.jsonl")

        try:
            # Create all files initially to establish a baseline
            (tmp_path / "test_file.py").write_text("dummy content")
            (tmp_path / "missing.py").write_text("will be deleted")

            # First run: Establish trust (TOFU) with all files present
            verifier = IntegrityVerifier(tmp_path)
            assert verifier.verify() is True

            # Now delete one file to simulate tampering/loss
            (tmp_path / "missing.py").unlink()

            # Second run: Should fail because file is missing from established manifest
            assert verifier.verify() is False
        finally:
            IntegrityVerifier.CRITICAL_FILES = saved_critical_files
            IntegrityVerifier.MANIFEST_PATH = saved_manifest_path

    def test_rebuild_manifest_in_strict_mode(self, tmp_path, monkeypatch):
        # Setup
        saved_critical_files = IntegrityVerifier.CRITICAL_FILES
        saved_manifest_path = IntegrityVerifier.MANIFEST_PATH
        IntegrityVerifier.CRITICAL_FILES = ["test_file.py"]
        IntegrityVerifier.MANIFEST_PATH = tmp_path / "integrity_manifest.json"

        # Mock keys directory to avoid cluttering local dev environment
        monkeypatch.setattr(
            "llm_cli.security.identity.IdentityManager._KEY_DIR", tmp_path / "keys"
        )
        monkeypatch.setattr(
            "llm_cli.security.identity.IdentityManager._PRIVATE_KEY_PATH",
            tmp_path / "keys" / "id_rsa",
        )
        monkeypatch.setattr(
            "llm_cli.security.identity.IdentityManager._PUBLIC_KEY_PATH",
            tmp_path / "keys" / "id_rsa.pub",
        )
        monkeypatch.setattr(
            "llm_cli.security.identity.IdentityManager._PQC_PRIVATE_KEY_PATH",
            tmp_path / "keys" / "id_pqc.key",
        )
        monkeypatch.setattr(
            "llm_cli.security.identity.IdentityManager._PQC_PUBLIC_KEY_PATH",
            tmp_path / "keys" / "id_pqc.pub",
        )
        # Mock audit log path to avoid checking system's real audit log
        monkeypatch.setattr("llm_cli.consts.AUDIT_LOG_PATH", tmp_path / "audit.jsonl")

        try:
            (tmp_path / "test_file.py").write_text("initial content")

            # Enable strict mode
            monkeypatch.setenv("LLM_CLI_STRICT_SECURITY", "1")

            verifier = IntegrityVerifier(tmp_path)

            # verify() should fail in strict mode if manifest is missing
            assert verifier.verify() is False

            # rebuild_manifest() should succeed even in strict mode
            assert verifier.rebuild_manifest() is True
            assert IntegrityVerifier.MANIFEST_PATH.exists()

            # Now verify() should succeed because manifest exists
            assert verifier.verify() is True
        finally:
            IntegrityVerifier.CRITICAL_FILES = saved_critical_files
            IntegrityVerifier.MANIFEST_PATH = saved_manifest_path


class TestPolicyEngine:
    def test_evaluate_admin(self):
        engine = PolicyEngine()
        context = {"roles": ["admin"]}
        assert engine.evaluate("any_tool", {}, context) is True

    def test_evaluate_guest_allowed(self):
        engine = PolicyEngine()
        context = {"roles": ["guest"]}
        assert engine.evaluate("read_file_content", {}, context) is True
        # Guest does not have search_web by default
        assert engine.evaluate("search_web", {}, context) is False

    def test_evaluate_guest_denied(self):
        engine = PolicyEngine()
        context = {"roles": ["guest"]}
        assert engine.evaluate("execute_command", {}, context) is False

    def test_evaluate_custom_roles(self):
        config = {
            "roles": {
                "developer": {"allow_all": False, "allowed_tools": ["execute_command"]}
            }
        }
        engine = PolicyEngine(config)
        assert engine.evaluate("execute_command", {}, {"roles": ["developer"]}) is True
        assert engine.evaluate("write_file", {}, {"roles": ["developer"]}) is False

    def test_validate_dangerous_args(self):
        engine = PolicyEngine()
        # Admin trying to write to /etc
        context = {"roles": ["admin"]}
        assert engine.evaluate("write_file", {"path": "/etc/passwd"}, context) is False
        assert (
            engine.evaluate("write_file", {"path": "/home/user/test.txt"}, context)
            is True
        )


class TestAuditLog:
    def test_log_audit_success(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit.log"

        # Patch the constant path used in log_audit
        monkeypatch.setattr("llm_cli.security.audit.AUDIT_LOG_PATH", audit_file)

        def mock_get_setting(key, section):
            if key == "max_audit_log_lines":
                return 100
            return None

        monkeypatch.setattr("llm_cli.security.audit.get_setting", mock_get_setting)

        log_audit("test_tool", {"arg1": "val1"}, "output content")

        assert audit_file.exists()
        content = audit_file.read_text()

        import json

        entry = json.loads(content.strip())

        assert entry["tool"] == "test_tool"
        assert entry["args"] == {"arg1": "val1"}
        assert entry["status"] == "SUCCESS"

    def test_log_audit_error(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit_error.log"
        monkeypatch.setattr("llm_cli.security.audit.AUDIT_LOG_PATH", audit_file)
        monkeypatch.setattr("llm_cli.security.audit.get_setting", lambda _k, _s: None)

        log_audit("fail_tool", {}, "no output", exit_code=1, error="Some error")
        content = audit_file.read_text()

        import json

        entry = json.loads(content.strip())

        assert entry["tool"] == "fail_tool"
        assert entry["status"] == "FAILED: Some error"
        assert entry["exit_code"] == 1

    def test_log_audit_exit_code_only(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit_exit.log"
        monkeypatch.setattr("llm_cli.security.audit.AUDIT_LOG_PATH", audit_file)
        monkeypatch.setattr("llm_cli.security.audit.get_setting", lambda _k, _s: None)

        log_audit("cmd_tool", {}, "some output", exit_code=127)
        content = audit_file.read_text()

        import json

        entry = json.loads(content.strip())

        assert entry["tool"] == "cmd_tool"
        assert entry["exit_code"] == 127
        assert entry["status"] == "SUCCESS"

    def test_log_audit_with_model(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit_model.log"
        monkeypatch.setattr("llm_cli.security.audit.AUDIT_LOG_PATH", audit_file)
        monkeypatch.setattr("llm_cli.security.audit.get_setting", lambda _k, _s: None)

        log_audit(
            "test_tool",
            {"arg1": "val1"},
            "output",
            context={"model": "gpt-4-turbo"},
        )
        content = audit_file.read_text()

        import json

        entry = json.loads(content.strip())

        assert entry["tool"] == "test_tool"
        assert entry["model"] == "gpt-4-turbo"

    def test_trim_log_file(self, tmp_path):
        from llm_cli.security.audit import _trim_log_file

        log_file = tmp_path / "trim.log"
        log_file.write_text("line1\nline2\nline3\nline4\n")

        _trim_log_file(log_file, 2)
        lines = log_file.read_text().splitlines()

        # New behavior: rotate overflow into an archive and insert a snapshot anchor.
        assert len(lines) == 3

        import json

        snapshot = json.loads(lines[0])
        assert snapshot["tool"] == "__audit_snapshot__"
        assert "archive" in snapshot["args"]
        assert snapshot["args"]["kept_lines"] == 2

        # The kept lines remain as the tail of the file
        assert lines[1] == "line3"
        assert lines[2] == "line4"

        # Archive file should exist
        from pathlib import Path

        archive_path = Path(snapshot["args"]["archive"])
        assert archive_path.exists()
        assert archive_path.read_text() == "line1\nline2\n"
