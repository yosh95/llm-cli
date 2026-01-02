# tests/test_attachment.py

from unittest.mock import patch
from llm_cli.modules.tools.media import attach_file
from llm_cli.clients.base import BaseLlmClient


class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        self.available_models = {"default": "model-v1"}

    def _send(self, data):
        return "response", {}


@patch("llm_cli.modules.tools.media.process_file")
@patch("llm_cli.modules.tools.media.Path")
def test_attach_file_tool_success(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    mock_process.return_value = {
        "content": "base64data",
        "content_type": "image/png"
    }

    res = attach_file("test.png")

    assert "Successfully attached" in res["result"]
    assert res["__llm_cli_data__"]["content"] == "base64data"
    assert res["__llm_cli_data__"]["content_type"] == "image/png"


@patch("llm_cli.modules.tools.media.Path")
def test_attach_file_tool_not_found(mock_path):
    mock_path.return_value.exists.return_value = False
    res = attach_file("missing.png")
    assert "Error: File not found" in res["result"]


@patch("llm_cli.modules.tools.media.process_file")
@patch("llm_cli.modules.tools.media.Path")
def test_attach_file_tool_text_file(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    mock_process.return_value = {
        "content": "hello world",
        "content_type": "text/plain"
    }

    res = attach_file("test.txt")
    assert "Successfully attached" in res["result"]
    assert res["__llm_cli_data__"]["content_type"] == "text/plain"


def test_handle_attach_command():
    client = MockClient("default", "KEY", "section", True, False)
    pending_data = []

    with patch.object(
        client, "_process_single_source"
    ) as mock_process:
        mock_process.return_value = {
            "content": "data",
            "content_type": "image/png",
            "is_file_or_url": True
        }
        res = client._handle_command("/attach my.png", None, pending_data)
        assert res is True
        assert len(pending_data) == 1
        assert pending_data[0]["content_type"] == "image/png"


def test_handle_attach_command_invalid():
    client = MockClient("default", "KEY", "section", True, False)
    pending_data = []

    # Case: Empty path
    res = client._handle_command("/attach  ", None, pending_data)
    assert res is True
    assert len(pending_data) == 0

    # Case: Process fails
    with patch.object(
        client, "_process_single_source"
    ) as mock_process:
        mock_process.json_return_value = None
        mock_process.return_value = None
        res = client._handle_command("/attach invalid.path", None, pending_data)
        assert res is True
        assert len(pending_data) == 0
