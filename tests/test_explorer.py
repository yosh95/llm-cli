# tests/test_explorer.py

import shutil
import tempfile
from pathlib import Path

import pytest

from llm_cli.modules.tools.explorer import (
    generate_repository_map,
    get_repository_structure,
)


@pytest.fixture
def mock_repo():
    """Creates a temporary directory with a mock Python project structure."""
    temp_dir = tempfile.mkdtemp()
    root = Path(temp_dir)

    # 1. Root level file
    (root / "main.py").write_text(
        '''
"""Main module docstring."""
class MainApp:
    """The main application class."""
    def run(self):
        """Starts the application."""
        pass

def top_level_func():
    """A standalone function."""
    pass
''',
        encoding="utf-8",
    )

    # 2. Nested directory
    sub_dir = root / "utils"
    sub_dir.mkdir()
    (sub_dir / "helper.py").write_text(
        '''
def helper_func(data: str):
    """Helper function docstring."""
    return data.upper()
''',
        encoding="utf-8",
    )

    # 3. Ignored directory
    ignored_dir = root / ".git"
    ignored_dir.mkdir()
    (ignored_dir / "config.py").write_text("def hidden(): pass", encoding="utf-8")

    # 4. File with syntax error
    (root / "bad_syntax.py").write_text("class Unfinished:", encoding="utf-8")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


def test_generate_repository_map_basic(mock_repo):
    """Checks if the map correctly identifies classes, methods, and functions."""
    repo_map = generate_repository_map(root_dir=mock_repo)

    # Check for files
    assert "### File: main.py" in repo_map
    assert "### File: utils/helper.py" in repo_map

    # Check for symbols and docstrings
    assert "- `class MainApp` - The main application class." in repo_map
    assert "  - `method run` - Starts the application." in repo_map
    assert "- `function top_level_func` - A standalone function." in repo_map
    assert "- `function helper_func` - Helper function docstring." in repo_map


def test_generate_repository_map_ignore_dirs(mock_repo):
    """Checks if ignored directories like .git are actually skipped."""
    repo_map = generate_repository_map(root_dir=mock_repo)

    # Should not contain hidden file in .git
    assert "hidden" not in repo_map
    assert "### File: .git/config.py" not in repo_map


def test_generate_repository_map_error_handling(mock_repo):
    """Checks if the tool handles syntax errors gracefully."""
    repo_map = generate_repository_map(root_dir=mock_repo)

    # Should report error for bad_syntax.py
    assert "Error parsing bad_syntax.py" in repo_map
    # But still contain results for main.py
    assert "### File: main.py" in repo_map


def test_get_repository_structure_wrapper(mock_repo, monkeypatch):
    """Verifies the tool wrapper function."""
    # Temporarily change working directory to mock_repo
    monkeypatch.chdir(mock_repo)

    result = get_repository_structure(explanation="Testing the tool wrapper")

    assert "### File: main.py" in result
    assert "MainApp" in result
    # Verification note should exist in the tool's description but here we check the output
    assert "MainApp" in result


def test_generate_repository_map_custom_ignore(mock_repo):
    """Checks if custom ignore list works."""
    repo_map = generate_repository_map(root_dir=mock_repo, ignore_dirs=["utils"])

    assert "### File: main.py" in repo_map
    assert "### File: utils/helper.py" not in repo_map
