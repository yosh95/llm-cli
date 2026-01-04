# tests/test_web_tools.py

from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.web import fetch_url, fetch_web_text


def test_fetch_url_html(mock_cloudscraper):
    """Test fetch_url returns raw HTML."""
    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.text = "<html><body><h1>Hello</h1></body></html>"

    result = fetch_url("https://example.com")
    assert "<html><body><h1>Hello</h1></body></html>" in result


def test_fetch_url_binary(mock_cloudscraper):
    """Test fetch_url handles binary content like PDF."""
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.content = b"%PDF-1.4 mock content"
    mock_cloudscraper.get.return_value = mock_response

    with patch("filetype.guess") as mock_guess:
        mock_guess.return_value.mime = "application/pdf"
        result = fetch_url("https://example.com/test.pdf")

        assert isinstance(result, dict)
        assert "__llm_cli_data__" in result
        assert result["__llm_cli_data__"]["content_type"] == "application/pdf"


def test_fetch_web_text_basic(mock_cloudscraper):
    """Test fetch_web_text extracts text and removes tags."""
    html_content = """
    <html>
        <head><style>.css { color: red; }</style></head>
        <body>
            <script>console.log('test');</script>
            <h1>Main Title</h1>
            <p>This is a <b>paragraph</b>.</p>
            <div>
                <span>Nested text</span>
            </div>
        </body>
    </html>
    """
    mock_cloudscraper.get.return_value.headers = {
        "Content-Type": "text/html; charset=utf-8"
    }
    mock_cloudscraper.get.return_value.text = html_content

    result = fetch_web_text("https://example.com")

    # Check that main content is present
    assert "Main Title" in result
    assert "This is a" in result
    assert "paragraph" in result
    assert "Nested text" in result

    # Check that unwanted content is removed
    assert "console.log" not in result
    assert ".css" not in result
    assert "<html>" not in result


def test_fetch_web_text_truncation(mock_cloudscraper):
    """Test fetch_web_text truncates output at 20000 chars."""
    long_text = "word " * 10000  # 50000 chars
    html_content = f"<html><body>{long_text}</body></html>"

    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.text = html_content

    result = fetch_web_text("https://example.com")
    assert len(result) == 20000


def test_fetch_web_text_error(mock_cloudscraper):
    """Test error handling in fetch_web_text."""
    mock_cloudscraper.get.side_effect = Exception("Connection error")

    result = fetch_web_text("https://example.com")
    assert "Error fetching or parsing" in result
    assert "Connection error" in result
