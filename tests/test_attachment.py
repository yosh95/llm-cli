# tests/test_attachment.py

from unittest.mock import patch

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.tools.file_ops import read_pdf


class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        self.available_models = {"default": "model-v1"}

    def _send(self, _data):
        return "response", {}


@patch("llm_cli.modules.tools.file_ops.process_file")
@patch("llm_cli.modules.tools.file_ops.Path")
def test_read_pdf_success(mock_path, mock_process):
    mock_path.return_value.exists.return_value = True
    # When pdf_as_base64=False, process_file returns text/plain
    mock_process.return_value = {
        "content": "extracted text",
        "content_type": "text/plain",
    }

    res = read_pdf("doc.pdf")

    assert res == "extracted text"


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
