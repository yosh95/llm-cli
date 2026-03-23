# llm_cli/modules/tools/web.py

import functools
from collections.abc import Callable
from typing import Any

import requests

from llm_cli.clients.config import config_manager
from llm_cli.clients.exceptions import ConfigurationError
from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES
from llm_cli.modules.tool_registry import tool
from llm_cli.security.pqc import sign_tool_result

# --- Decorator ---


def web_tool_handler(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """
    Decorator to handle common web tool logic:
    1. Exception Handling
    2. PQC Signature Signing for consistent security
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
            # Apply PQC signing to the result (if it's a string)
            return sign_tool_result(result) if isinstance(result, str) else result
        except Exception as e:
            return sign_tool_result(f"Error: {e}")

    return wrapper


# --- Tools ---


# Check for Brave Search configuration
@tool(
    name="search_web",
    description=(
        "Search the web using Brave Search to find information on the internet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query (keywords or question).",
            },
        },
        "required": ["query"],
    },
)
@web_tool_handler
def search_web(query: str) -> str:
    api_key = config_manager.get("brave", "api_key")
    if not api_key:
        raise ConfigurationError(
            "Brave Search API key required (BRAVE_SEARCH_API_KEY)."
        )

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return f"### Search Results for: {query}\n\nNo results found."

    output = [f"### Search Results for: {query}\n"]
    for i, res in enumerate(results[:10], 1):
        title = res.get("title", "No Title")
        link = res.get("url", "#")
        snippet = res.get("description", "No description available.")
        output.append(f"{i}. **[{title}]({link})**")
        output.append(f"   {snippet}\n")

    return "\n".join(output)


@tool(
    name="read_url_content",
    desc=(
        "Fetch a web page URL or PDF URL and convert the content to Markdown or text. "
        "For PDFs, text content will be extracted. "
        f"IMPORTANT: This tool can read up to {MAX_OUTPUT_LINES} lines or "
        f"{MAX_OUTPUT_CHARS} characters at once. "
        "If the content is longer, the tail will be omitted."
    ),
    params={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target URL."}},
        "required": ["url"],
    },
)
@web_tool_handler
def read_url_content(url: str) -> str:
    from llm_cli.modules.media_utils import fetch_url_content

    content, ctype = fetch_url_content(url, pdf_as_base64=False)

    if content is None or ctype is None:
        return f"Error: Failed to fetch content from {url} or invalid URL."

    # fetch_url_content returns 'text/plain' for both raw text and extracted PDF text
    if "text/html" not in ctype and "text/plain" not in ctype:
        return (
            f"Error: URL returned {ctype}, expected text/html, text/plain or "
            "application/pdf."
        )

    return content
