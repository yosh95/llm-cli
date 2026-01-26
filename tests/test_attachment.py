# tests/test_attachment.py

from unittest.mock import patch

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.tools.media import read_image_file, read_pdf_file


class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        self.available_models = {"default": "model-v1"}

    def _send(self, data):
        return "response", {}


@patch("llm_cli.modules.tools.media.process_file")
@patch("llm_cli.modules.tools.media.Path")
def test_read_image_file_success(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    mock_process.return_value = {"content": "base64data", "content_type": "image/png"}

    res = read_image_file("test.png")

    assert "Successfully read" in res["result"]
    assert res["__llm_cli_data__"]["content"] == "base64data"
    assert res["__llm_cli_data__"]["content_type"] == "image/png"


@patch("llm_cli.modules.tools.media.process_file")
@patch("llm_cli.modules.tools.media.Path")
def test_read_pdf_file_success(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    mock_process.return_value = {
        "content": "pdf_base64",
        "content_type": "application/pdf",
    }

    res = read_pdf_file("doc.pdf")

    assert "Successfully read" in res["result"]
    assert res["__llm_cli_data__"]["content"] == "pdf_base64"
    assert res["__llm_cli_data__"]["content_type"] == "application/pdf"


@patch("llm_cli.modules.tools.media.Path")
def test_media_tool_file_not_found(mock_path):
    mock_path.return_value.exists.return_value = False
    res = read_image_file("missing.png")
    assert "Error: File not found" in res


@patch("llm_cli.modules.tools.media.process_file")
@patch("llm_cli.modules.tools.media.Path")
def test_read_image_file_invalid_type(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    # Simulate a text file being read as an image
    mock_process.return_value = {"content": "hello", "content_type": "text/plain"}

    res = read_image_file("test.txt")
    assert "Error" in res
    assert "has type 'text/plain'" in res
    assert "expected one of ('image/',)" in res


def test_handle_attach_command():
    from llm_cli.modules.models import DataSource

    client = MockClient("default", "KEY", "section", True, False)
    pending_data = []

    with patch.object(client, "_process_single_source") as mock_process:
        mock_process.return_value = DataSource(
            content="data",
            content_type="image/png",
            is_file_or_url=True,
        )
        res = client._handle_command("/attach my.png", None, pending_data)
        assert res is True
        assert len(pending_data) == 1
        assert pending_data[0].content_type == "image/png"


def test_handle_attach_command_invalid():
    client = MockClient("default", "KEY", "section", True, False)
    pending_data = []

    # Case: Empty path
    res = client._handle_command("/attach  ", None, pending_data)
    assert res is True
    assert len(pending_data) == 0

    # Case: Process fails
    with patch.object(client, "_process_single_source") as mock_process:
        mock_process.json_return_value = None
        mock_process.return_value = None
        res = client._handle_command("/attach invalid.path", None, pending_data)
        assert res is True
        assert len(pending_data) == 0
