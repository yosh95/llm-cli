from typing import Any
from unittest.mock import patch

import pytest

from llm_cli.modules.tools.file_ops import search_files


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


def test_search_files_by_name_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Setup files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").touch()
    (tmp_path / "src" / "utils.py").touch()
    (tmp_path / "README.md").touch()

    # Search for '*.py'
    result = _get_result_text(search_files(pattern="*.py"))
    assert "[F] src/main.py" in result
    assert "[F] src/utils.py" in result
    assert "README.md" not in result


def test_search_files_by_name_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Setup directories
    (tmp_path / "test_dir").mkdir()
    (tmp_path / "other_dir").mkdir()

    # Search for '*_dir'
    result = _get_result_text(search_files(pattern="*_dir"))
    assert "[D] test_dir" in result
    assert "[D] other_dir" in result


def test_search_files_by_name_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test.txt").touch()

    result = _get_result_text(search_files(pattern="*.py"))
    assert "No files found matching the pattern." in result


def test_search_files_by_name_exclude(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keep.py").touch()
    (tmp_path / "skip.py").touch()

    result = _get_result_text(search_files(pattern="*.py", exclude_patterns=["skip.py"]))
    assert "keep.py" in result
    assert "skip.py" not in result
