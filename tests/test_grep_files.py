from typing import Any
from unittest.mock import patch

import pytest

from llm_cli.modules.tools.file_ops import grep_files


def _get_result_text(result: str | dict[str, Any]) -> str:
    """Extract the plain text from a tool result."""
    if isinstance(result, dict):
        return str(result.get("result", result.get("response", "")))
    return result


@pytest.fixture(autouse=True)
def mock_search_config():
    with patch("llm_cli.security.path_validator.config_manager.load_config") as mock_load:
        mock_load.return_value = {"security": {"allowed_paths": ["."], "blocked_paths": ["/etc"]}}
        yield


def test_grep_files_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Setup files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def hello():\n    print('Hello World')", encoding="utf-8"
    )
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    pass", encoding="utf-8")

    # Setup ignore directory
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "temp.txt").write_text("Hello in cache", encoding="utf-8")

    # Search for 'hello'
    result = _get_result_text(grep_files(query="hello"))
    assert "src/main.py:1:def hello():" in result
    assert "cache/temp.txt" not in result


def test_grep_files_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test.txt").write_text("no match here", encoding="utf-8")

    result = _get_result_text(grep_files(query="target"))
    assert "No matches found." in result


def test_grep_files_with_pattern(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test.py").write_text("pattern in python", encoding="utf-8")
    (tmp_path / "test.txt").write_text("pattern in text", encoding="utf-8")

    result = _get_result_text(grep_files(query="pattern", file_pattern="*.py"))
    assert "test.py:1:pattern in python" in result
    assert "test.txt" not in result


def test_grep_files_invalid_regex(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _get_result_text(grep_files(query="["))
    assert "Error" in result


def test_grep_files_security_violation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _get_result_text(grep_files(query="test", directory="/etc"))
    assert "Security Error" in result
