from unittest.mock import MagicMock, patch

from llm_cli.modules.tools.brave_search import web_search


def test_web_search_success():
    # Mocking the response from Brave Search API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Example Title 1",
                    "url": "https://example.com/1",
                    "description": "This is the first example snippet.",
                },
                {
                    "title": "Example Title 2",
                    "url": "https://example.com/2",
                    "description": "This is the second example snippet.",
                },
            ]
        }
    }

    with patch("curl_cffi.requests.get", return_value=mock_response):
        # We need to bypass the PQC signing for simple assertion, or just check if it contains the expected text.
        # web_tool_handler returns signed result (dict or string with signature)
        result = web_search(query="test query")

        # If signed, it might be a dict with 'result' field
        if isinstance(result, dict):
            content = result.get("result", "")
        else:
            content = result

        assert "Example Title 1" in content
        assert "https://example.com/1" in content
        assert "This is the first example snippet." in content
        assert "Example Title 2" in content
        assert "---" in content


def test_web_search_no_results():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"web": {"results": []}}

    with patch("curl_cffi.requests.get", return_value=mock_response):
        result = web_search(query="empty query")

        if isinstance(result, dict):
            content = result.get("result", "")
        else:
            content = result

        assert "No search results found." in content


def test_web_search_error():
    with patch("curl_cffi.requests.get", side_effect=Exception("API Error")):
        result = web_search(query="error query")

        if isinstance(result, dict):
            content = result.get("result", "")
        else:
            content = result

        assert "Error:" in content
        assert "API Error" in content
