# tests/test_file_ops.py

from llm_cli.modules.tools.file_modification import (
    create_or_overwrite_file,
    edit_file,
    validate_create_or_overwrite_file,
)


def _get_result_text(result: str | dict) -> str:
    """Extract the plain text from a tool result.

    High-risk tools (create_or_overwrite_file, edit_file) now return a signed
    dict when PQC keys are available, or a plain str as a fallback.
    This helper normalises both forms so that tests remain provider-agnostic.
    """
    if isinstance(result, dict):
        return str(result.get("result", result.get("response", "")))
    return result


def test_write_and_read_file(tmp_path, monkeypatch):
    """Test writing a file and then reading it back."""
    monkeypatch.chdir(tmp_path)

    test_path = "subdir/test.txt"
    content = "Hello, LLM tools!"

    # Test create_or_overwrite_file
    write_result = _get_result_text(create_or_overwrite_file(test_path, content))
    assert "Successfully wrote" in write_result
    assert (tmp_path / test_path).exists()


def test_file_ops_security_block(tmp_path, monkeypatch):
    """Test that file operations block paths outside the sandbox."""
    monkeypatch.chdir(tmp_path)
    result = _get_result_text(create_or_overwrite_file("../illegal.txt", "content"))
    assert "Security Error" in result or "outside the sandbox" in result.lower()


def test_edit_file_success(tmp_path, monkeypatch):
    """Test editing a file by replacing a block."""
    monkeypatch.chdir(tmp_path)
    test_path = "edit_test.txt"
    content = "Line 1\nLine 2\nLine 3\nLine 4"
    (tmp_path / test_path).write_text(content, encoding="utf-8")

    # Replace Line 2 and Line 3
    search_block = "Line 2\nLine 3"
    replacement = "Line 2 Mod\nLine 3 Mod"
    result = _get_result_text(edit_file(test_path, search=search_block, replace=replacement))

    assert "Successfully updated" in result

    new_content = (tmp_path / test_path).read_text(encoding="utf-8")
    new_lines = new_content.splitlines()

    assert "Line 1" == new_lines[0]
    assert "Line 2 Mod" == new_lines[1]
    assert "Line 3 Mod" == new_lines[2]
    assert "Line 4" == new_lines[3]
    assert "Line 2" not in new_lines  # Exact line match check


def test_edit_file_not_found(tmp_path, monkeypatch):
    """Test error when file does not exist."""
    monkeypatch.chdir(tmp_path)
    result = _get_result_text(edit_file("nonexistent.txt", "search", "replace"))
    assert "Error" in result
    assert "not a file" in result


def test_edit_file_search_block_not_found(tmp_path, monkeypatch):
    """Test error when search block is not in file."""
    monkeypatch.chdir(tmp_path)
    test_path = "no_match.txt"
    (tmp_path / test_path).write_text("Line A\nLine B", encoding="utf-8")

    result = _get_result_text(edit_file(test_path, search="Line C", replace="Line D"))
    assert "not found exactly or fuzzily" in result


# ============================================================
# 2-A: validate_create_or_overwrite_file tests
# ============================================================


class TestValidateCreateOrOverwriteFile:
    """Verify that the pre-validation function for create_or_overwrite_file
    correctly accepts safe paths and rejects unsafe ones."""

    def test_valid_path_within_cwd_returns_true(self, tmp_path, monkeypatch):
        """A path inside CWD must return True."""
        monkeypatch.chdir(tmp_path)
        result = validate_create_or_overwrite_file("new_file.txt")
        assert result is True

    def test_traversal_path_returns_error_string(self, tmp_path, monkeypatch):
        """A directory traversal path must return an error string (not raise)."""
        monkeypatch.chdir(tmp_path)
        result = validate_create_or_overwrite_file("../evil.txt")
        assert isinstance(result, str)
        assert result.startswith("Error")

    def test_blocked_absolute_path_returns_error_string(self, tmp_path, monkeypatch):
        """A blocked absolute path must return an error string."""
        monkeypatch.chdir(tmp_path)
        result = validate_create_or_overwrite_file("/etc/passwd")
        assert isinstance(result, str)
        assert result.startswith("Error")

    def test_parent_is_not_a_directory_returns_error(self, tmp_path, monkeypatch):
        """If the parent path exists but is a file (not a dir) an error is returned."""
        monkeypatch.chdir(tmp_path)
        # Create a file where we expect a directory
        fake_parent = tmp_path / "not_a_dir"
        fake_parent.write_text("I am a file", encoding="utf-8")
        result = validate_create_or_overwrite_file("not_a_dir/child.txt")
        # validate_path will either fail or the parent check will catch it
        assert isinstance(result, str) and result.startswith("Error")
