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
        secret = IdentityManager.get_secret_key()
        payload = {
            "iss": "llm-cli-client",
            "sub": "user",
            "iat": time.time() - 7200,
            "exp": time.time() - 3600,
            "roles": ["user"]
        }
        token = jwt.encode(payload, secret, algorithm="HS256")
        assert IdentityManager.verify_token(token) is None

    def test_get_current_context(self):
        context = IdentityManager.get_current_context()
        assert "authorization" in context
        assert "trace_id" in context
        assert context["authorization"].startswith("Bearer ")

class TestIntegrityVerifier:
    def test_verify_success(self, tmp_path):
        # Create dummy critical files
        for f_path in IntegrityVerifier.CRITICAL_FILES:
            full_path = tmp_path / f_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text("dummy content")

        verifier = IntegrityVerifier(tmp_path)
        assert verifier.verify() is True

    def test_verify_missing_file(self, tmp_path):
        # Create only some critical files
        f_path = IntegrityVerifier.CRITICAL_FILES[0]
        full_path = tmp_path / f_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text("dummy content")

        verifier = IntegrityVerifier(tmp_path)
        # Should fail because other files are missing
        assert verifier.verify() is False

class TestPolicyEngine:
    def test_evaluate_admin(self):
        engine = PolicyEngine()
        context = {"roles": ["admin"]}
        assert engine.evaluate("any_tool", {}, context) is True

    def test_evaluate_guest_allowed(self):
        engine = PolicyEngine()
        context = {"roles": ["guest"]}
        assert engine.evaluate("read_file", {}, context) is True
        assert engine.evaluate("google_search", {}, context) is True

    def test_evaluate_guest_denied(self):
        engine = PolicyEngine()
        context = {"roles": ["guest"]}
        assert engine.evaluate("execute_command", {}, context) is False

    def test_evaluate_custom_roles(self):
        config = {
            "roles": {
                "developer": {
                    "allow_all": False,
                    "allowed_tools": ["execute_command"]
                }
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
        assert engine.evaluate("write_file", {"path": "/home/user/test.txt"}, context) is True

class TestAuditLog:
    def test_log_audit_success(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit.log"

        def mock_get_setting(key, section):
            if key == "LLM_AUDIT_LOG":
                return str(audit_file)
            if key == "max_audit_log_lines":
                return 100
            return None

        monkeypatch.setattr("llm_cli.security.audit.get_setting", mock_get_setting)

        log_audit("test_tool", {"arg1": "val1"}, "output content")

        assert audit_file.exists()
        content = audit_file.read_text()
        assert "Tool:   test_tool" in content
        assert "Args:   {'arg1': 'val1'}" in content
        assert "Status: SUCCESS" in content
        assert "Result:\noutput content" in content

    def test_log_audit_error(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit_error.log"
        monkeypatch.setattr("llm_cli.security.audit.get_setting", lambda k, s: str(audit_file) if k == "LLM_AUDIT_LOG" else None)

        log_audit("fail_tool", {}, "no output", exit_code=1, error="Some error")
        content = audit_file.read_text()
        # If error is present, it overwrites status
        assert "FAILED (Some error)" in content

    def test_log_audit_exit_code_only(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit_exit.log"
        monkeypatch.setattr("llm_cli.security.audit.get_setting", lambda k, s: str(audit_file) if k == "LLM_AUDIT_LOG" else None)

        log_audit("cmd_tool", {}, "some output", exit_code=127)
        content = audit_file.read_text()
        assert "Status: Exit Code: 127" in content

    def test_trim_log_file(self, tmp_path):
        from llm_cli.security.audit import _trim_log_file
        log_file = tmp_path / "trim.log"
        log_file.write_text("line1\nline2\nline3\nline4\n")

        _trim_log_file(log_file, 2)
        content = log_file.read_text()
        assert content == "line3\nline4\n"
