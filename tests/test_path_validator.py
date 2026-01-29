# tests/test_path_validator.py

from pathlib import Path

import pytest

from llm_cli.modules.tools.file_ops import (
    list_files_in_directory,
    read_file_content,
    create_or_overwrite_file,
)
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

    def test_file_ops_integrity(self, tmp_path, monkeypatch):
        """Test that file_ops tools actually respect the validator."""
        # Change CWD to a temp directory for this test
        monkeypatch.chdir(tmp_path)

        # 1. read_file_content restriction
        result = read_file_content("/etc/passwd")
        assert "Security Error" in result

        result = read_file_content("../any_file")
        assert "Security Error" in result

        # 2. create_or_overwrite_file restriction
        result = create_or_overwrite_file("/tmp/malicious.sh", "echo hi")
        assert "Security Error" in result

        # 3. list_files_in_directory restriction
        result = list_files_in_directory("/")
        assert "Security Error" in result

        # 4. Success case within sandbox
        (tmp_path / "safe.txt").write_text("hello")
        result = read_file_content("safe.txt")
        assert "hello" in result

