# tests/test_file_ops.py

from llm_cli.modules.tools.file_ops import (
    create_or_overwrite_file,
    edit_file,
)


def test_write_and_read_file(tmp_path, monkeypatch):
    """Test writing a file and then reading it back."""
    monkeypatch.chdir(tmp_path)

    test_path = "subdir/test.txt"
    content = "Hello, LLM tools!"

    # Test create_or_overwrite_file
    write_result = create_or_overwrite_file(test_path, content)
    assert "Successfully wrote" in write_result
    assert (tmp_path / test_path).exists()


def test_file_ops_security_block(tmp_path, monkeypatch):
    """Test that file operations block paths outside the sandbox."""
    monkeypatch.chdir(tmp_path)
    result = create_or_overwrite_file("../illegal.txt", "content")
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
    result = edit_file(test_path, search=search_block, replace=replacement)

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
    result = edit_file("nonexistent.txt", "search", "replace")
    assert "Error" in result
    assert "not a file" in result


def test_edit_file_search_block_not_found(tmp_path, monkeypatch):
    """Test error when search block is not in file."""
    monkeypatch.chdir(tmp_path)
    test_path = "no_match.txt"
    (tmp_path / test_path).write_text("Line A\nLine B", encoding="utf-8")

    result = edit_file(test_path, search="Line C", replace="Line D")
    assert "not found in the file" in result
