# tests/test_file_ops.py


from llm_cli.modules.tools.file_ops import list_files, read_file, write_file


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

    # Test read_file
    read_result = read_file(test_path)
    assert content in read_result


def test_read_file_line_range(tmp_path, monkeypatch):
    """Test reading a specific line range from a file."""
    monkeypatch.chdir(tmp_path)

    lines = ["Line 1", "Line 2", "Line 3", "Line 4"]
    test_path = "range.txt"
    (tmp_path / test_path).write_text("\n".join(lines))

    # Read lines 2 to 3
    result = read_file(test_path, start_line=2, end_line=3)
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
