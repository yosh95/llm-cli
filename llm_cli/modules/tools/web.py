# llm_cli/modules/tools/web.py

import requests

from llm_cli.clients.config import config_manager
from llm_cli.modules.tool_registry import tool

# Check for Brave Search configuration
_brave_api_key = config_manager.get("brave", "api_key")


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
def search_web(query: str) -> str:
    api_key = config_manager.get("brave", "api_key")
    if not api_key:
        return "Error: Brave Search API key required (BRAVE_SEARCH_API_KEY)."

    try:
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
    except Exception as e:
        return f"Error searching '{query}' with Brave Search: {e}"


@tool(
    name="read_url_content",
    description=(
        "Fetch a web page URL or PDF URL and convert the content to Markdown or text. "
        "For PDFs, text content will be extracted."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target URL."}},
        "required": ["url"],
    },
)
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
