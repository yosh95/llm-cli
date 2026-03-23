# tests/test_web_tools.py

from unittest.mock import patch

from llm_cli.modules.tools.web import read_url_content


def _get_result_text(result: str | dict) -> str:
    """Extract the plain text from a tool result.

    Tools (search_web, read_url_content) now return a signed
    dict when PQC keys are available, or a plain str as a fallback.
    """
    if isinstance(result, dict):
        return str(result.get("result", result.get("response", "")))
    return result


def test_read_url_content_basic(mock_curl_requests):
    """Test read_url_content extracts content and converts to markdown."""
    html_content = """
    <html>
        <head><style>.css { color: red; }</style></head>
        <body>
            <script>console.log('test');</script>
            <h1>Main Title</h1>
            <p>This is a <b>paragraph</b>.</p>
            <a href="https://example.com/link">Link Text</a>
        </body>
    </html>
    """
    mock_curl_requests.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_curl_requests.text = html_content

    # We expect markdownify to handle the conversion.
    result = _get_result_text(read_url_content("https://example.com"))

    # Check for markdown elements
    assert "Main Title" in result
    # Check if link is preserved
    assert "Link Text" in result
    assert "https://example.com/link" in result

    # Check that unwanted content is removed
    assert "console.log" not in result
    assert ".css" not in result
    assert "<html>" not in result


def test_read_url_content_error(mock_curl_requests):
    """Test error handling in read_url_content."""
    with patch("curl_cffi.requests.get", side_effect=Exception("Connection error")):
        result = _get_result_text(read_url_content("https://example.com"))

    assert "Error: Failed to fetch content" in result
