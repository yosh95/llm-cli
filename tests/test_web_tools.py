# tests/test_web_tools.py

from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.web import (
    read_html_from_url,
    read_image_from_url,
    read_pdf_from_url,
    search_web,
)


def test_read_pdf_from_url_success(mock_cloudscraper):
    """Test read_pdf_from_url returns base64 content."""
    mock_cloudscraper.get.return_value.headers = {"Content-Type": "application/pdf"}
    mock_cloudscraper.get.return_value.content = b"fake pdf content"

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_pdf_from_url("https://example.com/doc.pdf")

    assert isinstance(result, dict)
    assert "Successfully fetched PDF" in result["result"]
    assert "content has been added to the conversation context" in result["result"]
    assert result["__llm_cli_data__"]["content_type"] == "application/pdf"
    # "fake pdf content" base64 encoded is "ZmFrZSBwZGYgY29udGVudA=="
    assert result["__llm_cli_data__"]["content"] == "ZmFrZSBwZGYgY29udGVudA=="
    assert result["__llm_cli_data__"]["is_file_or_url"] is True


def test_read_image_from_url_success(mock_cloudscraper):
    """Test read_image_from_url returns base64 content."""
    mock_cloudscraper.get.return_value.headers = {"Content-Type": "image/jpeg"}
    mock_cloudscraper.get.return_value.content = b"fake image content"

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_image_from_url("https://example.com/image.jpg")

    assert isinstance(result, dict)
    assert "Successfully fetched image" in result["result"]
    assert "content has been added to the conversation context" in result["result"]
    assert result["__llm_cli_data__"]["content_type"] == "image/jpeg"
    # "fake image content" base64 encoded is "ZmFrZSBpbWFnZSBjb250ZW50"
    assert result["__llm_cli_data__"]["content"] == "ZmFrZSBpbWFnZSBjb250ZW50"
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
    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
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


def test_read_html_from_url_error(mock_cloudscraper):
    """Test error handling in read_html_from_url."""
    mock_cloudscraper.get.side_effect = Exception("Connection error")

    with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
        result = read_html_from_url("https://example.com")

    assert "Error: Failed to fetch content" in result


def test_search_web_success(mock_config):
    """Test search_web success scenario."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "This is a summary of the search results."}]
                },
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://r1.com", "title": "Result 1"}},
                        {"web": {"uri": "https://r2.com", "title": "Result 2"}},
                    ]
                },
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = search_web(query="test query")

        # Check API call
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["contents"][0]["parts"][0]["text"].endswith(
            "Query: test query"
        )
        assert "googleSearch" in kwargs["json"]["tools"][0]

        # Check result formatting
        assert "### Search Results for: test query" in result
        assert "This is a summary of the search results." in result
        assert "- [Result 1](https://r1.com)" in result
        assert "- [Result 2](https://r2.com)" in result


def test_search_web_no_results(mock_config):
    """Test search_web when no items are returned."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # No "candidates"

    with patch("requests.post", return_value=mock_response):
        result = search_web(query="empty")
        assert "No results found." in result


def test_search_web_auth_error(monkeypatch):
    """Test search_web when credentials are missing."""
    # Patch the module-level variables directly since they are read at import time
    monkeypatch.setattr("llm_cli.modules.tools.web._google_api_key", None)

    # We mock requests to ensure no network call happens
    with patch("requests.post") as mock_post:
        result = search_web(query="test")
        mock_post.assert_not_called()

    assert "Error: Web Search configuration missing" in result
