import runpy
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.ollama_models import main as ollama_main


def test_ollama_models_success(capsys):
    # Mock get_setting to return a URL
    with (
        patch(
            "llm_cli.apps.ollama_models.get_setting",
            return_value="http://my-ollama:11434/v1",
        ),
        patch("llm_cli.apps.ollama_models.requests.get") as mock_get,
    ):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "llama3:latest",
                    "size": 5000000000,
                    "modified_at": "2024-01-01",
                }
            ]
        }
        mock_get.return_value = mock_response

        ollama_main()

    captured = capsys.readouterr()
    assert "llama3:latest" in captured.out
    assert "5.00 GB" in captured.out


def test_ollama_models_no_url(capsys):
    # Test fallback URL when get_setting returns None
    with (
        patch("llm_cli.apps.ollama_models.get_setting", return_value=None),
        patch("llm_cli.apps.ollama_models.requests.get") as mock_get,
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_get.return_value = mock_response

        ollama_main()

        # Check if it used the default host
        mock_get.assert_called_once()
        args, _ = mock_get.call_args
        assert "localhost:11434" in args[0]


def test_ollama_models_exception(capsys):
    # Lines 46-48: Exception handling
    with patch(
        "llm_cli.apps.ollama_models.get_setting", side_effect=Exception("Config error")
    ):
        with pytest.raises(SystemExit) as excinfo:
            ollama_main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error fetching Ollama models: Config error" in captured.out


def test_ollama_models_main_block():
    # Line 52: __name__ == "__main__"
    # We let it run the real main() to get coverage.
    # We just need to mock dependencies so it doesn't fail.
    with (
        patch("llm_cli.apps.ollama_models.get_setting", return_value=None),
        patch("llm_cli.apps.ollama_models.requests.get") as mock_get,
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_get.return_value = mock_response

        runpy.run_module("llm_cli.apps.ollama_models", run_name="__main__")
