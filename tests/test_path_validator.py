# tests/test_path_validator.py

from pathlib import Path

import pytest

from llm_cli.security.path_validator import PathValidationError, validate_path


class TestPathValidator:
    def test_sandbox_within_cwd(self):
        """Should allow paths within current directory."""
        cwd = Path.cwd()
        test_file = cwd / "test_file.txt"
        # Should not raise
        validate_path("test_file.txt")
        validate_path(str(test_file))

    def test_blocks_traversal(self):
        """Should block any use of .."""
        with pytest.raises(
            PathValidationError, match="Directory traversal '..' is forbidden"
        ):
            validate_path("../outside.txt")
        with pytest.raises(
            PathValidationError, match="Directory traversal '..' is forbidden"
        ):
            validate_path("dir/../../etc/passwd")

    def test_blocks_absolute_system_paths(self):
        """Should block absolute paths to system directories."""
        with pytest.raises(
            PathValidationError, match="Access outside project directory is forbidden"
        ):
            validate_path("/etc/passwd")
        with pytest.raises(
            PathValidationError, match="Access outside project directory is forbidden"
        ):
            validate_path("/var/log/syslog")
