from llm_cli.modules.tools.file_ops import apply_diff, read_file, write_file


def test_apply_diff_success(tmp_path, monkeypatch):
    """Test applying a simple unified diff."""
    monkeypatch.chdir(tmp_path)

    path = "test.py"
    original_content = (
        "def hello():\n    print('hello')\n\ndef world():\n    print('world')\n"
    )
    write_file(path, original_content)

    diff = """--- test.py
+++ test.py
@@ -1,5 +1,5 @@
 def hello():
-    print('hello')
+    print('hi')

 def world():
     print('world')
"""
    result = apply_diff(path, diff)
    assert "Successfully applied diff" in result

    new_content = read_file(path)
    assert "print('hi')" in new_content
    assert "print('hello')" not in new_content
    assert "def world():" in new_content


def test_apply_diff_multiple_hunks(tmp_path, monkeypatch):
    """Test applying a diff with multiple hunks."""
    monkeypatch.chdir(tmp_path)

    path = "multi.txt"
    original_content = (
        "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8\n"
    )
    write_file(path, original_content)

    diff = """--- multi.txt
+++ multi.txt
@@ -1,3 +1,3 @@
-Line 1
+Changed 1
 Line 2
 Line 3
@@ -6,3 +6,3 @@
 Line 6
-Line 7
+Changed 7
 Line 8
"""
    result = apply_diff(path, diff)
    assert "Successfully applied diff" in result

    new_content = read_file(path)
    assert "Changed 1" in new_content
    assert "Changed 7" in new_content
    assert "Line 2" in new_content
    assert "Line 6" in new_content


def test_apply_diff_mismatch(tmp_path, monkeypatch):
    """Test behavior when context lines do not match."""
    monkeypatch.chdir(tmp_path)

    path = "mismatch.txt"
    original_content = "Original Line A\nOriginal Line B\n"
    write_file(path, original_content)

    # Diff expects "Wrong Line" which doesn't exist
    diff = """--- mismatch.txt
+++ mismatch.txt
@@ -1,2 +1,2 @@
-Wrong Line
+New Line
 Original Line B
"""
    result = apply_diff(path, diff)
    assert "Error" in result

    # Content should remain unchanged
    current_content = read_file(path)
    assert "Original Line A" in current_content


def test_apply_diff_security(tmp_path, monkeypatch):
    """Test that apply_diff respects path validation."""
    monkeypatch.chdir(tmp_path)

    result = apply_diff("../outside.txt", "some diff")
    assert "Security Error" in result
