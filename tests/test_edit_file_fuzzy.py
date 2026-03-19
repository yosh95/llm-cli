from unittest.mock import patch

import pytest

from llm_cli.modules.tools.file_ops import edit_file


@pytest.fixture(autouse=True)
def mock_path_config(tmp_path):
    # Mock the configuration to allow the temporary directory
    with patch("llm_cli.security.path_validator._load_config_from_file") as mock_load:
        mock_load.return_value = {
            "security": {
                "allowed_paths": [str(tmp_path)],
                "blocked_paths": [],
            }
        }
        yield


@pytest.fixture
def temp_test_file(tmp_path):
    p = tmp_path / "test_file.py"
    p.write_text(
        "def main():\n    print('Hello world')\n    # A comment here\n    return 0\n",
        encoding="utf-8",
    )
    return p


def get_result_text(res):
    if isinstance(res, dict) and "result" in res:
        return res["result"]
    return res


def test_edit_file_exact_match(temp_test_file):
    """Test standard exact matching."""
    res = edit_file(
        path=str(temp_test_file),
        search="    print('Hello world')",
        replace="    print('Modified world')",
    )
    res_text = get_result_text(res)
    assert "Successfully updated" in res_text
    content = temp_test_file.read_text()
    assert "print('Modified world')" in content
    assert "print('Hello world')" not in content


def test_edit_file_fuzzy_match_whitespace(temp_test_file):
    """Test fuzzy matching with whitespace differences."""
    # Indentation difference in search block
    res = edit_file(
        path=str(temp_test_file),
        search="  print(  'Hello world'  )",  # extra spaces
        replace="    print('Fuzzy Modified')",
    )
    res_text = get_result_text(res)
    assert "Successfully updated" in res_text
    content = temp_test_file.read_text()
    assert "print('Fuzzy Modified')" in content
    assert "print('Hello world')" not in content


def test_edit_file_multi_line_fuzzy(temp_test_file):
    """Test multi-line fuzzy matching."""
    # Search block with messy whitespace
    messy_search = "  # A comment here  \n   return 0  "

    res = edit_file(
        path=str(temp_test_file),
        search=messy_search,
        replace="    # Replaced comment\n    return 1",
    )
    res_text = get_result_text(res)
    assert "Successfully updated" in res_text
    content = temp_test_file.read_text()
    assert "return 1" in content
    assert "Replaced comment" in content


def test_edit_file_multiple_matches_error(temp_test_file):
    """Test that multiple matches (exact or fuzzy) lead to an error."""
    # Add another line that's identical to one
    with temp_test_file.open("a") as f:
        f.write("\n    return 0\n")

    res = edit_file(
        path=str(temp_test_file), search="    return 0", replace="    return 99"
    )
    res_text = get_result_text(res)
    assert "2 matches found" in res_text
    # Should not have changed
    content = temp_test_file.read_text()
    assert "return 0" in content


def test_edit_file_not_found(temp_test_file):
    """Test that non-existent content leads to an error."""
    res = edit_file(
        path=str(temp_test_file),
        search="non-existent content",
        replace="something else",
    )
    res_text = get_result_text(res)
    assert "The 'search' block was not found" in res_text


def test_edit_file_dry_run(temp_test_file):
    """Test dry run mode does not modify the file."""
    initial_content = temp_test_file.read_text()
    res = edit_file(
        path=str(temp_test_file),
        search="    return 0",
        replace="    return 42",
        dry_run=True,
    )
    res_text = get_result_text(res)
    assert "Dry run enabled" in res_text
    assert "Successfully updated" not in res_text
    assert initial_content == temp_test_file.read_text()
