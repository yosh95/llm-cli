import pytest

from llm_cli.modules.tools.file_ops import grep_files, list_files_in_directory


def _get_result_text(result: str | dict) -> str:
    if isinstance(result, dict):
        return str(result.get("result", result.get("response", "")))
    return result


@pytest.fixture
def setup_test_dirs(tmp_path):
    # Create subdirectories and files for testing
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file1.txt").write_text("content1", encoding="utf-8")
    (tmp_path / "subdir" / "file2.txt").write_text("content2", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "root_file.txt").write_text("root content", encoding="utf-8")
    return tmp_path


def test_list_files_with_trailing_slash(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    # Test trailing slash
    res = _get_result_text(list_files_in_directory("subdir/"))
    assert "file1.txt" in res
    assert "file2.txt" in res
    assert "Error" not in res


def test_list_files_with_quotes_and_whitespace(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    # Test quotes and whitespace
    res = _get_result_text(list_files_in_directory(" 'subdir/' "))
    assert "file1.txt" in res
    assert "Error" not in res

    res = _get_result_text(list_files_in_directory(' "subdir" '))
    assert "file1.txt" in res
    assert "Error" not in res


def test_list_files_non_existent(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    res = _get_result_text(list_files_in_directory("non_existent"))
    assert "Error" in res
    assert "does not exist" in res


def test_list_files_on_file(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    res = _get_result_text(list_files_in_directory("root_file.txt"))
    assert "Error" in res
    assert "is not a directory" in res


def test_search_files_with_trailing_slash(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    # Test search with trailing slash
    res = _get_result_text(grep_files(directory="subdir/", query="content1"))
    assert "file1.txt:1:content1" in res
    assert "Error" not in res


def test_search_files_with_quotes_and_whitespace(setup_test_dirs, monkeypatch):
    monkeypatch.chdir(setup_test_dirs)

    # Test search with quotes and whitespace
    res = _get_result_text(grep_files(directory=" 'subdir/' ", query="content2"))
    assert "file2.txt:1:content2" in res
    assert "Error" not in res
