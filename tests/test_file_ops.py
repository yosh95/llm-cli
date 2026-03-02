# tests/test_file_ops.py

from llm_cli.modules.tools.file_ops import (
    create_or_overwrite_file,
    edit_file,
    replace_lines,
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


def test_replace_lines_success(tmp_path, monkeypatch):
    """Test replacing a specific range of lines."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.txt"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\n")

    # Replace lines 2 and 3
    result = replace_lines(
        str(test_file),
        start_line=2,
        end_line=3,
        replacement="new line 2\nnew line 3",
    )

    assert "Successfully updated" in result
    assert test_file.read_text() == "line 1\nnew line 2\nnew line 3\nline 4\n"


def test_replace_lines_out_of_range(tmp_path, monkeypatch):
    """Test error when line numbers are out of range."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.txt"
    test_file.write_text("line 1\n")

    result = replace_lines(str(test_file), start_line=5, end_line=6, replacement="fail")
    assert "Error: start_line 5 is out of range" in result


def test_edit_file_fuzzy_match_feedback(tmp_path, monkeypatch):
    """Test the improved feedback message when a similar match is found."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.tex"
    content = "\\begin{equation}\n  E = mc^2\n\\end{equation}\n"
    test_file.write_text(content)

    # Attempt to edit with incorrect indentation (4 spaces instead of 2)
    search_block = "\\begin{equation}\n    E = mc^2\n\\end{equation}"
    replace_block = "\\begin{equation}\n    E = h \\nu\n\\end{equation}"

    result = edit_file(str(test_file), search=search_block, replace=replace_block)

    assert (
        "The 'search' block was not found exactly, but a similar match was found "
        "ignoring whitespace"
    ) in result
    assert "replace_lines" in result


def test_replace_lines_no_newline_handling(tmp_path, monkeypatch):
    """Test that replace_lines maintains newlines if the original block had them."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.txt"
    test_file.write_text("line 1\nline 2\n")

    # Replace line 2 with content that doesn't end with newline
    # The tool should automatically add it because the original line had one.
    result = replace_lines(
        str(test_file), start_line=2, end_line=2, replacement="new line 2"
    )

    assert "Successfully updated" in result
    assert test_file.read_text() == "line 1\nnew line 2\n"


def test_replace_lines_deletion(tmp_path, monkeypatch):
    """Test deleting lines by replacing with an empty string."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.txt"
    test_file.write_text("line 1\nline 2\nline 3\n")

    # Delete line 2 by replacing it with an empty string
    result = replace_lines(str(test_file), start_line=2, end_line=2, replacement="")

    assert "Successfully updated" in result
    assert test_file.read_text() == "line 1\nline 3\n"
