# tests/test_path_validator_advanced.py

from unittest.mock import patch

import pytest

from llm_cli.security.path_validator import PathValidationError, validate_path


class TestPathValidatorAdvanced:
    @patch("llm_cli.security.path_validator.config_manager.load_config")
    def test_allowed_paths_whitelist(self, mock_load_config):
        """Should allow access only within the allowed_paths whitelist."""
        mock_load_config.return_value = {
            "security": {
                "allowed_paths": ["/tmp", "."],
                "blocked_paths": ["/etc"],
            }
        }

        # Accessing /tmp should be allowed
        path = validate_path("/tmp")
        assert str(path) == "/tmp"

        # Accessing CWD should be allowed because of "."
        path = validate_path("test_file.txt")
        assert path.name == "test_file.txt"

        # Should block /etc
        with pytest.raises(
            PathValidationError, match="Access to blocked path is forbidden"
        ):
            validate_path("/etc/passwd")

    @patch("llm_cli.security.path_validator.config_manager.load_config")
    def test_path_not_in_whitelist(self, mock_load_config):
        """Should block paths not explicitly in the whitelist."""
        mock_load_config.return_value = {
            "security": {
                "allowed_paths": ["."],
                "blocked_paths": [],
            }
        }

        # /tmp is not in whitelist
        with pytest.raises(
            PathValidationError, match="Access to path is not in the whitelist"
        ):
            validate_path("/tmp")
