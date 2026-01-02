# tests/test_attachment.py

import pytest
from pathlib import Path
from llm_cli.modules.tools.media import attach_file
from llm_cli.clients.base import BaseLlmClient

# BaseLlmClient is abstract, creating a minimal mock for testing
class MockClient(BaseLlmClient):
    def _load_model_aliases(self):
        self.available_models = {"default": "mock-model"}
    def _send(self, data):
        return "response", {}

@pytest.fixture
def temp_files(tmp_path):
    """Fixture to create dummy files for testing."""
    img_path = tmp_path / "test.png"
    # Minimal PNG header
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")
    
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("hello world", encoding="utf-8")
    
    return {"image": img_path, "text": txt_path}

def test_attach_file_tool_success(temp_files):
    """Test if attach_file correctly encodes image to Base64."""
    result = attach_file(str(temp_files["image"]))
    
    assert "result" in result
    assert "Successfully attached" in result["result"]
    assert "__llm_cli_data__" in result
    assert result["__llm_cli_data__"]["content_type"] == "image/png"
    assert len(result["__llm_cli_data__"]["content"]) > 0

def test_attach_file_tool_not_found():
    """Test error handling for non-existent files."""
    result = attach_file("non_existent_file.jpg")
    assert "Error" in result["result"]

def test_attach_file_tool_text_file(temp_files):
    """Test warning when attach_file is used on a text file."""
    result = attach_file(str(temp_files["text"]))
    assert "Notice" in result["result"]
    assert "__llm_cli_data__" not in result

def test_handle_attach_command(temp_files):
    """Test if /attach command adds data to pending_data buffer."""
    client = MockClient(
        initial_model_alias="default",
        api_key_name="dummy",
        config_section="test",
        pdf_as_base64=True,
        stdout=True
    )
    
    pending_data = []
    user_input = f"/attach {temp_files['image']}"
    
    # Execute the command
    handled = client._handle_command(user_input, sources=[], pending_data=pending_data)
    
    assert handled is True
    assert len(pending_data) == 1
    assert pending_data[0]["content_type"] == "image/png"
    assert "is_file_or_url" in pending_data[0]

def test_handle_attach_command_invalid():
    """Test if /attach command correctly skips non-existent paths."""
    client = MockClient("default", "dummy", "test", True, True)
    pending_data = []
    
    handled = client._handle_command("/attach invalid_path.xyz", [], pending_data)
    
    assert handled is True
    assert len(pending_data) == 0
