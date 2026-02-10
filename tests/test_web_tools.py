# tests/test_web_tools.py

from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.web import read_html_from_url, read_pdf_from_url, search_web


def test_read_pdf_from_url_success(mock_cloudscraper):
    """Test read_pdf_from_url returns base64 content."""
    mock_cloudscraper.get.return_value.headers = {"Content-Type": "application/pdf"}
    mock_cloudscraper.get.return_value.content = b"fake pdf content"

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_pdf_from_url("https://example.com/doc.pdf")

    assert isinstance(result, dict)
    assert "Successfully fetched PDF" in result["result"]
    assert result["__llm_cli_data__"]["content_type"] == "application/pdf"
    # "fake pdf content" base64 encoded is "ZmFrZSBwZGYgY29udGVudA=="
    assert result["__llm_cli_data__"]["content"] == "ZmFrZSBwZGYgY29udGVudA=="
    assert result["__llm_cli_data__"]["is_file_or_url"] is True


def test_read_pdf_from_url_not_pdf(mock_cloudscraper):
    """Test read_pdf_from_url handles non-pdf content type."""
    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.content = b"<html></html>"

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_pdf_from_url("https://example.com/doc.html")

    assert isinstance(result, str)
    assert "Error: Expected PDF but got" in result


def test_read_pdf_from_url_fetch_error(mock_cloudscraper):
    """Test read_pdf_from_url handles fetch errors."""
    mock_cloudscraper.get.side_effect = Exception("Fetch failed")

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_pdf_from_url("https://example.com/doc.pdf")

    assert isinstance(result, str)
    assert "Error: Failed to fetch content" in result


def test_read_html_from_url_basic(mock_cloudscraper):
    """Test read_html_from_url extracts content and converts to markdown."""
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
    mock_cloudscraper.get.return_value.headers = {
        "Content-Type": "text/html; charset=utf-8"
    }
    mock_cloudscraper.get.return_value.text = html_content

    # We expect markdownify to handle the conversion.
    result = read_html_from_url("https://example.com")

    # Check for markdown elements
    # Both ATX headings and link preservation should be handled by markdownify
    # but both should produce something readable.
    assert "Main Title" in result
    # Check if link is preserved
    assert "Link Text" in result
    assert "https://example.com/link" in result

    # Check that unwanted content is removed
    assert "console.log" not in result
    assert ".css" not in result
    assert "<html>" not in result


def test_read_html_from_url_truncation(mock_cloudscraper):
    """Test read_html_from_url truncates output."""
    long_text = "word " * 10000  # Approx 50000 chars
    html_content = f"<html><body>{long_text}</body></html>"

    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.text = html_content

    # Use a small limit to ensure truncation occurs
    result = read_html_from_url("https://example.com", max_length=1000)

    assert "... (Truncated" in result
    assert len(result) <= 1200  # 1000 + extra message chars


def test_read_html_from_url_no_limit(mock_cloudscraper):
    """Test read_html_from_url with no limit (max_length=0)."""
    long_text = "word " * 11000  # Approx 55000 chars
    html_content = f"<html><body>{long_text}</body></html>"

    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.text = html_content

    # Set limit to 0 (no limit)
    result = read_html_from_url("https://example.com", max_length=0)

    # Should NOT be truncated
    assert "... (Truncated" not in result
    # Content should be > 50000 chars
    assert len(result) >= 50000


def test_read_html_from_url_error(mock_cloudscraper):
    """Test error handling in read_html_from_url."""
    mock_cloudscraper.get.side_effect = Exception("Connection error")

    result = read_html_from_url("https://example.com")
    assert "Error fetching or parsing" in result
    assert "Connection error" in result


def test_search_web_success(mock_config):
    """Test search_web success scenario."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"title": "Result 1", "link": "https://r1.com", "snippet": "Snippet 1"},
            {"title": "Result 2", "link": "https://r2.com", "snippet": "Snippet 2"},
        ]
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        result = search_web(query="test query")

        # Check API call
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "test query"
        assert kwargs["params"]["num"] == 10

        # Check result formatting
        assert "### Results for: test query" in result
        assert "Title: Result 1" in result
        assert "URL: https://r2.com" in result


def test_search_web_no_results(mock_config):
    """Test search_web when no items are returned."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # No "items"

    with patch("requests.get", return_value=mock_response):
        result = search_web(query="empty")
        assert "No results." in result


def test_search_web_auth_error(monkeypatch):
    """Test search_web when credentials are missing."""
    # Patch the module-level variables directly since they are read at import time
    monkeypatch.setattr("llm_cli.modules.tools.web._google_api_key", None)
    monkeypatch.setattr("llm_cli.modules.tools.web._google_cse_id", None)

    # We mock requests to ensure no network call happens
    with patch("requests.get") as mock_get:
        result = search_web(query="test")
        mock_get.assert_not_called()

    assert "Error: Web Search configuration missing." in result
