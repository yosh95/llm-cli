# tests/test_web_tools.py

from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.web import fetch_url, fetch_web_text, google_search


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
    """Test fetch_web_text truncates output and adds helper message."""
    with patch("llm_cli.modules.tools.web.get_setting") as mock_get:
        mock_get.return_value = None  # Force use of default max_length

        # "word " is 5 chars. 10000 * 5 = 50000 chars
        long_text = "word " * 10000
        html_content = f"<html><body>{long_text}</body></html>"

        mock_cloudscraper.get.return_value.headers = {"Content-Type": "text/html"}
        mock_cloudscraper.get.return_value.text = html_content

        # Default max_length is 10000
        result = fetch_web_text("https://example.com", max_length=10000)

        # Should contain the truncation message
        assert "... (Output truncated" in result
        assert "Use start_offset=10000" in result

        # The content part should be length 10000
        content_part = result.split("\n... (Output truncated")[0]
        assert len(content_part) == 10000


def test_fetch_web_text_error(mock_cloudscraper):
    """Test error handling in fetch_web_text."""
    mock_cloudscraper.get.side_effect = Exception("Connection error")

    result = fetch_web_text("https://example.com")
    assert "Error fetching or parsing" in result
    assert "Connection error" in result


def test_google_search_success(mock_config):
    """Test google_search success scenario."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"title": "Result 1", "link": "https://r1.com", "snippet": "Snippet 1"},
            {"title": "Result 2", "link": "https://r2.com", "snippet": "Snippet 2"},
        ]
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        result = google_search(queries=["test query"], num=2)

        # Check API call
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "test query"
        assert kwargs["params"]["num"] == 2

        # Check result formatting
        assert "### Results for: test query" in result
        assert "Title: Result 1" in result
        assert "URL: https://r2.com" in result


def test_google_search_multiple_queries(mock_config):
    """Test google_search with multiple queries."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"items": [{"title": "Hit"}]}

    with patch("requests.get", return_value=mock_response):
        result = google_search(queries=["q1", "q2"])
        assert "Results for: q1" in result
        assert "Results for: q2" in result


def test_google_search_no_results(mock_config):
    """Test google_search when no items are returned."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # No "items"

    with patch("requests.get", return_value=mock_response):
        result = google_search(queries=["empty"])
        assert "No results." in result


def test_google_search_auth_error(monkeypatch):
    """Test google_search when credentials are missing."""
    # Force get_setting to return None for google
    monkeypatch.setattr("llm_cli.modules.tools.web.get_setting", lambda k, s: None)

    result = google_search(queries=["test"])
    assert "Error: Google Search is not configured." in result
    assert "llm-cli-config" in result
