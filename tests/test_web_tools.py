# tests/test_web_tools.py

from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.web import fetch_web_markdown, web_search


def test_fetch_web_markdown_basic(mock_cloudscraper):
    """Test fetch_web_markdown extracts content and converts to markdown."""
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

    # We mock markdownify if it exists, but the test should pass with fallback too.
    # To test the fallback logic explicitly, we could mock markdownify as None,
    # but here we just check the output structure.
    result = fetch_web_markdown("https://example.com")

    # Check for markdown elements
    # Note: Exact output depends on markdownify vs fallback,
    # but both should produce something readable.
    assert "Main Title" in result
    # Check if link is preserved
    assert "Link Text" in result
    assert "https://example.com/link" in result

    # Check that unwanted content is removed
    assert "console.log" not in result
    assert ".css" not in result
    assert "<html>" not in result


def test_fetch_web_markdown_truncation(mock_cloudscraper):
    """Test fetch_web_markdown truncates output."""
    long_text = "word " * 10000
    html_content = f"<html><body>{long_text}</body></html>"

    mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
    mock_cloudscraper.get.return_value.text = html_content

    result = fetch_web_markdown("https://example.com")

    assert "... (Truncated" in result
    assert len(result) <= 20200  # 20000 + extra message chars


def test_fetch_web_markdown_error(mock_cloudscraper):
    """Test error handling in fetch_web_markdown."""
    mock_cloudscraper.get.side_effect = Exception("Connection error")

    result = fetch_web_markdown("https://example.com")
    assert "Error fetching or parsing" in result
    assert "Connection error" in result


def test_web_search_success(mock_config):
    """Test web_search success scenario."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"title": "Result 1", "link": "https://r1.com", "snippet": "Snippet 1"},
            {"title": "Result 2", "link": "https://r2.com", "snippet": "Snippet 2"},
        ]
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        result = web_search(query="test query")

        # Check API call
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "test query"
        assert kwargs["params"]["num"] == 10

        # Check result formatting
        assert "### Results for: test query" in result
        assert "Title: Result 1" in result
        assert "URL: https://r2.com" in result


def test_web_search_no_results(mock_config):
    """Test web_search when no items are returned."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # No "items"

    with patch("requests.get", return_value=mock_response):
        result = web_search(query="empty")
        assert "No results." in result


def test_web_search_auth_error(monkeypatch):
    """Test web_search when credentials are missing."""
    # Force get_setting to return None for google
    monkeypatch.setattr("llm_cli.modules.tools.web.get_setting", lambda k, s: None)

    result = web_search(query="test")
    assert "Error: Web Search (Google) is not configured." in result
    assert "llm-cli-config" in result
