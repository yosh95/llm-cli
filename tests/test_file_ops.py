# tests/test_file_ops.py


from llm_cli.modules.tools.file_ops import (
    edit_file,
    list_files,
    read_text_file,
    write_file,
)


def test_write_and_read_file(tmp_path, monkeypatch):
    """Test writing a file and then reading it back."""
    # Mock current working directory to tmp_path for sandbox validation
    monkeypatch.chdir(tmp_path)

    test_path = "subdir/test.txt"
    content = "Hello, LLM tools!"

    # Test write_file
    write_result = write_file(test_path, content)
    assert "Successfully wrote" in write_result
    assert (tmp_path / test_path).exists()

    # Test read_text_file
    read_result = read_text_file(test_path)
    assert content in read_result


def test_read_file_line_range(tmp_path, monkeypatch):
    """Test reading a specific line range from a file."""
    monkeypatch.chdir(tmp_path)

    lines = ["Line 1", "Line 2", "Line 3", "Line 4"]
    test_path = "range.txt"
    (tmp_path / test_path).write_text("\n".join(lines))

    # Read lines 2 to 3
    result = read_text_file(test_path, start_line=2, end_line=3)
    assert "Line 1" not in result
    assert "Line 2" in result
    assert "Line 3" in result
    assert "Line 4" not in result


def test_list_files_recursive(tmp_path, monkeypatch):
    """Test listing files with depth and directory structure."""
    monkeypatch.chdir(tmp_path)

    # Create structure:
    # dir1/file1.txt
    # dir1/dir2/file2.txt
    (tmp_path / "dir1" / "dir2").mkdir(parents=True)
    (tmp_path / "dir1" / "file1.txt").touch()
    (tmp_path / "dir1" / "dir2" / "file2.txt").touch()

    # List with depth 1
    res_d1 = list_files(directory="dir1", depth=1)
    assert "file1.txt" in res_d1
    assert "dir2/" in res_d1
    assert "file2.txt" not in res_d1

    # List with depth 2
    res_d2 = list_files(directory="dir1", depth=2)
    assert "file2.txt" in res_d2


def test_file_ops_security_block(tmp_path, monkeypatch):
    """Test that file operations block paths outside the sandbox."""
    monkeypatch.chdir(tmp_path)

    # Try to write to a path outside the tmp_path (simulated by /tmp or similar)
    # The sandbox validator checks if the path is within CWD.
    result = write_file("../illegal.txt", "content")
    assert "Security Error" in result or "outside the sandbox" in result.lower()


def test_list_files_max_files(tmp_path, monkeypatch):
    """Test list_files respects max_files limit."""
    monkeypatch.chdir(tmp_path)

    for i in range(10):
        (tmp_path / f"file_{i}.txt").touch()

    result = list_files(max_files=5)
    assert "file_0.txt" in result
    assert "Too many files" in result


def test_edit_file_success(tmp_path, monkeypatch):
    """Test editing a file by replacing a block of text."""
    monkeypatch.chdir(tmp_path)
    test_path = "edit_test.txt"
    content = "Line 1\nLine 2\nLine 3"
    (tmp_path / test_path).write_text(content, encoding="utf-8")

    search = "Line 2"
    replace = "Line Two Modified"

    result = edit_file(test_path, search, replace)
    assert "Successfully updated" in result

    new_content = (tmp_path / test_path).read_text(encoding="utf-8")
    assert "Line 1" in new_content
    assert "Line Two Modified" in new_content
    assert "Line 3" in new_content
    assert "Line 2" not in new_content


def test_edit_file_not_found_error(tmp_path, monkeypatch):
    """Test error when file does not exist."""
    monkeypatch.chdir(tmp_path)
    result = edit_file("nonexistent.txt", "foo", "bar")
    assert "Error" in result
    assert "not a file" in result


def test_edit_file_content_not_found(tmp_path, monkeypatch):
    """Test error when search block is not in file."""
    monkeypatch.chdir(tmp_path)
    test_path = "edit_test_missing.txt"
    (tmp_path / test_path).write_text("Hello World", encoding="utf-8")

    result = edit_file(test_path, "Goodbye", "Farewell")
    assert "Error" in result
    assert "block was not found" in result


def test_edit_file_multiple_occurrences(tmp_path, monkeypatch):
    """Test error when search block appears multiple times."""
    monkeypatch.chdir(tmp_path)
    test_path = "edit_test_multi.txt"
    content = "Repeat\nUnique\nRepeat"
    (tmp_path / test_path).write_text(content, encoding="utf-8")

    result = edit_file(test_path, "Repeat", "Fixed")
    assert "Error" in result
    assert "occurrences" in result


def test_edit_file_indentation(tmp_path, monkeypatch):
    """Test that indentation is preserved and handled correctly."""
    monkeypatch.chdir(tmp_path)
    test_path = "edit_indent.py"
    content = "def func():\n    return True\n"
    (tmp_path / test_path).write_text(content, encoding="utf-8")

    search = "    return True"
    replace = "    return False"

    result = edit_file(test_path, search, replace)
    assert "Successfully updated" in result

    new_content = (tmp_path / test_path).read_text(encoding="utf-8")
    assert "def func():\n    return False\n" == new_content
