# tests/test_path_validator_advanced.py

from unittest.mock import patch

import pytest

from llm_cli.security.path_validator import PathValidationError, validate_path


class TestPathValidatorAdvanced:
    @patch("llm_cli.security.path_validator._load_config_from_file")
    def test_allow_outside_cwd(self, mock_load_config):
        """Should allow access outside CWD if configured."""
        mock_load_config.return_value = {
            "security": {
                "allow_outside_cwd": True,
                "allow_sensitive_path_access": False,
            }
        }

        # Accessing /tmp should be allowed if it's not in the sensitive list
        # Note: /tmp is NOT in sensitive_prefixes in the code
        # sensitive_prefixes = ["/etc", "/var", "/root", "/bin", "/sbin", "/usr", "/dev", "/proc", "/sys", "/boot", "/home"]

        # Should not raise for /tmp (assuming it exists on the system)
        path = validate_path("/tmp")
        assert str(path) == "/tmp"

        # Should still block /etc
        with pytest.raises(
            PathValidationError, match="Access to sensitive system path is forbidden"
        ):
            validate_path("/etc/passwd")

    @patch("llm_cli.security.path_validator._load_config_from_file")
    def test_allow_sensitive_path_access(self, mock_load_config):
        """Should allow access to sensitive paths if explicitly enabled."""
        mock_load_config.return_value = {
            "security": {"allow_outside_cwd": True, "allow_sensitive_path_access": True}
        }

        # Should now allow /etc/passwd
        path = validate_path("/etc/passwd")
        assert str(path) == "/etc/passwd"
