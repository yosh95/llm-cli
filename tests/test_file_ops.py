# tests/test_file_ops.py

from llm_cli.modules.tools.file_ops import (
    list_files,
    read_text_file,
    replace_lines,
    search_files,
    write_file,
)


def test_write_and_read_file(tmp_path, monkeypatch):
    """Test writing a file and then reading it back."""
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


def test_read_file_with_line_numbers(tmp_path, monkeypatch):
    """Test reading with line numbers."""
    monkeypatch.chdir(tmp_path)
    test_path = "nums.txt"
    lines = ["A", "B", "C"]
    (tmp_path / test_path).write_text("\n".join(lines))

    result = read_text_file(test_path, with_line_numbers=True)
    assert "   1 | A" in result
    assert "   2 | B" in result
    assert "   3 | C" in result


def test_list_files_recursive(tmp_path, monkeypatch):
    """Test listing files with depth and directory structure."""
    monkeypatch.chdir(tmp_path)

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


def test_list_files_ignore(tmp_path, monkeypatch):
    """Test ignore patterns in list_files."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keep.txt").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignore.js").touch()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "secrets.env").touch()

    # Default ignore should catch node_modules and __pycache__
    # Custom ignore for .env
    result = list_files(ignore_patterns=["node_modules", "__pycache__", "*.env"])

    assert "keep.txt" in result
    assert "node_modules" not in result
    assert "ignore.js" not in result
    assert "__pycache__" not in result
    assert "secrets.env" not in result


def test_file_ops_security_block(tmp_path, monkeypatch):
    """Test that file operations block paths outside the sandbox."""
    monkeypatch.chdir(tmp_path)
    result = write_file("../illegal.txt", "content")
    assert "Security Error" in result or "outside the sandbox" in result.lower()


def test_search_files_basic(tmp_path, monkeypatch):
    """Test searching for text in files."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("def target_func():\n    pass")
    (tmp_path / "b.txt").write_text("Just some text")
    (tmp_path / "c.py").write_text("call target_func()")

    result = search_files(query="target_func", file_pattern="*.py")
    assert "a.py:1: def target_func():" in result
    assert "c.py:1: call target_func()" in result
    assert "b.txt" not in result


def test_replace_lines_success(tmp_path, monkeypatch):
    """Test replacing lines in a file."""
    monkeypatch.chdir(tmp_path)
    test_path = "replace_test.txt"
    content = "Line 1\nLine 2\nLine 3\nLine 4"
    (tmp_path / test_path).write_text(content, encoding="utf-8")

    # Replace Line 2 and Line 3
    replacement = "Line 2 Mod\nLine 3 Mod"
    result = replace_lines(test_path, start_line=2, end_line=3, replacement=replacement)

    assert "Successfully updated" in result
    assert "Diff:" in result
    # Check Diff content
    assert "-Line 2" in result
    assert "+Line 2 Mod" in result

    new_content = (tmp_path / test_path).read_text(encoding="utf-8")
    new_lines = new_content.splitlines()
    
    assert "Line 1" == new_lines[0]
    assert "Line 2 Mod" == new_lines[1]
    assert "Line 3 Mod" == new_lines[2]
    assert "Line 4" == new_lines[3]
    assert "Line 2" not in new_lines # Exact line match check


def test_replace_lines_file_not_found(tmp_path, monkeypatch):
    """Test error when file does not exist."""
    monkeypatch.chdir(tmp_path)
    result = replace_lines("nonexistent.txt", 1, 1, "foo")
    assert "Error" in result
    assert "not a file" in result


def test_replace_lines_out_of_bounds(tmp_path, monkeypatch):
    """Test error when line numbers are invalid."""
    monkeypatch.chdir(tmp_path)
    test_path = "bounds.txt"
    (tmp_path / test_path).write_text("Line 1", encoding="utf-8")

    # Start line too big
    res1 = replace_lines(test_path, 5, 5, "Content")
    assert "out of bounds" in res1

    # End < Start
    res2 = replace_lines(test_path, 1, 0, "Content")
    assert "smaller than start_line" in res2
