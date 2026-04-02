"""Shared test fixtures and configuration for pytest."""

import base64
import os
import pathlib
import tempfile
from unittest.mock import Mock

import pytest

import llm_cli.clients.config
from llm_cli import consts
from llm_cli.clients.config import config_manager

# Redirect CONFIG_FILE_PATH to a non-existent path in a temporary directory
# to prevent leakage of real configuration during tests.
consts.LLM_CLI_BASE_DIR = pathlib.Path(tempfile.gettempdir()) / f"llm-cli-test-{os.getpid()}"
consts.CONFIG_DIR = consts.LLM_CLI_BASE_DIR
consts.LOG_DIR = consts.LLM_CLI_BASE_DIR / "logs"
consts.KEY_DIR = consts.LLM_CLI_BASE_DIR / "keys"
consts.CONFIG_FILE_PATH = consts.CONFIG_DIR / "config.toml"
consts.AUDIT_LOG_PATH = consts.LOG_DIR / "audit.jsonl"
llm_cli.clients.config.CONFIG_FILE_PATH = consts.CONFIG_FILE_PATH

# Inject dummy configuration
config_manager._config_cache = {
    "google": {
        "api_key": "dummy_test_key",
        "cse_id": "dummy_test_cse_id",
    },
    "openai": {"api_key": "dummy_openai_key"},
    "anthropic": {"api_key": "dummy_anthropic_key"},
    "security": {
        "allowed_paths": ["."],
        "blocked_paths": [
            "/etc",
            "/var",
            "/root",
            "/bin",
            "/sbin",
            "/usr",
            "/dev",
            "/proc",
            "/sys",
            "/boot",
            "~/.ssh",
        ],
    },
}


@pytest.fixture(autouse=True)
def prevent_magicmock_directories(monkeypatch):
    """
    Prevent 'MagicMock/' directories from being created during tests.
    """
    from llm_cli.clients.session import ChatSession

    original_setup = ChatSession._setup_from_client

    def patched_setup(self):
        # Force history_path to be a temporary one or None if it's a Mock
        if hasattr(self.client, "history_path"):
            h = self.client.history_path
            if hasattr(h, "assert_called") or "Mock" in str(h):
                self.client.history_path = None
        if hasattr(self.client, "chat_log_path"):
            c = self.client.chat_log_path
            if hasattr(c, "assert_called") or "Mock" in str(c):
                self.client.chat_log_path = None
        return original_setup(self)

    monkeypatch.setattr(ChatSession, "_setup_from_client", patched_setup)


@pytest.fixture
def mock_api_key():
    """Provide a mock API key for testing."""
    return "test_api_key_1234567890"


@pytest.fixture
def sample_text_content():
    """Provide sample text content for testing."""
    return "This is sample text content for testing."


@pytest.fixture
def sample_pdf_content():
    """Provide a simple PDF binary content for testing."""
    # Minimal valid PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000214 00000 n
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
308
%%EOF
"""
    return pdf_content


@pytest.fixture
def sample_pdf_base64(sample_pdf_content):
    """Provide base64-encoded PDF content."""
    return base64.b64encode(sample_pdf_content).decode("utf-8")


@pytest.fixture
def sample_image_base64():
    """Provide a minimal base64-encoded image (1x1 PNG)."""
    # 1x1 transparent PNG
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    png_bytes = base64.b64decode(png_b64)
    return base64.b64encode(png_bytes).decode("utf-8")


@pytest.fixture
def temp_pdf_file(tmp_path, sample_pdf_content):
    """Create a temporary PDF file for testing."""
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(sample_pdf_content)
    return pdf_file


@pytest.fixture
def temp_text_file(tmp_path, sample_text_content):
    """Create a temporary text file for testing."""
    text_file = tmp_path / "test.txt"
    text_file.write_text(sample_text_content, encoding="utf-8")
    return text_file


@pytest.fixture
def temp_empty_file(tmp_path):
    """Create a temporary empty file for testing."""
    empty_file = tmp_path / "empty.txt"
    empty_file.touch()
    return empty_file


@pytest.fixture
def mock_config(monkeypatch, mock_api_key, tmp_path):
    """Mock the config_manager to return test values."""

    def mock_get(section, key):
        if key == "image_save_path":
            return str(tmp_path)

        config = {
            "google": {
                "api_key": mock_api_key,
                "cse_id": "test_cse_id",
                "system_prompt": "You are a helpful AI assistant.",
            },
            "openai": {
                "api_key": mock_api_key,
                "system_prompt": "You are a helpful AI assistant.",
            },
            "anthropic": {
                "api_key": mock_api_key,
                "system_prompt": "You are a helpful AI assistant.",
            },
            "general": {
                "unified_default_provider": "google",
            },
        }
        return config.get(section, {}).get(key)

    def mock_get_model_aliases(section):
        return {
            "default": "test-model",
            "pro": "test-model-pro",
            "gemini-flash": "gemini-1.5-flash",
        }

    from llm_cli.clients.config import config_manager

    # Patch the config_manager instance methods
    monkeypatch.setattr(config_manager, "get", mock_get)
    monkeypatch.setattr(config_manager, "get_bool", lambda s, k, d=False: bool(mock_get(s, k) or d))
    monkeypatch.setattr(config_manager, "get_model_aliases", mock_get_model_aliases)


@pytest.fixture
def mock_requests_success(monkeypatch):
    """Mock successful HTTP requests."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.text = "<html><body>Test content</body></html>"
    mock_response.content = b"Test content"
    mock_response.json.return_value = {"result": "success"}
    mock_response.raise_for_status = Mock()

    def mock_get(*args, **kwargs):
        return mock_response

    def mock_post(*args, **kwargs):
        return mock_response

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)
    return mock_response


@pytest.fixture
def mock_curl_requests(monkeypatch, mock_requests_success):
    """Mock curl_cffi.requests to return successful responses."""
    # We want curl_cffi.requests.get to BE a mock that returns mock_requests_success
    mock_get = Mock(return_value=mock_requests_success)
    monkeypatch.setattr("curl_cffi.requests.get", mock_get)
    return mock_requests_success
