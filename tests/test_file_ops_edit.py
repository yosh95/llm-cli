import shutil
from pathlib import Path

import pytest

from llm_cli.modules.tools.file_ops import edit_file


@pytest.fixture
def test_dir():
    # Create a temporary directory inside the project root to satisfy security guardrails
    d = Path("temp_test_dir")
    d.mkdir(exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d)


def test_edit_file_success(test_dir):
    # Setup
    test_file = test_dir / "test.txt"
    original_content = (
        "def hello():\n    print('hello')\n\ndef world():\n    print('world')"
    )
    test_file.write_text(original_content, encoding="utf-8")

    search_block = "def hello():\n    print('hello')"
    replace_block = "def hello(name):\n    print(f'hello {name}')"

    # Execute
    result = edit_file(str(test_file), search_block, replace_block)

    # Assert
    assert "Successfully updated" in result
    new_content = test_file.read_text(encoding="utf-8")
    assert "def hello(name):" in new_content
    assert "print(f'hello {name}')" in new_content
    assert "def world():" in new_content


def test_edit_file_not_found(test_dir):
    test_file = test_dir / "test.txt"
    test_file.write_text("content", encoding="utf-8")

    result = edit_file(str(test_file), "non-existent", "replacement")
    assert "Error: The 'search' block was not found" in result


def test_edit_file_multiple_occurrences(test_dir):
    test_file = test_dir / "test.txt"
    content = "duplicate\nduplicate\n"
    test_file.write_text(content, encoding="utf-8")

    result = edit_file(str(test_file), "duplicate", "new")
    assert "Error: Found 2 occurrences" in result
