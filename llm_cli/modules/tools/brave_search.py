import time

from curl_cffi import requests as curl_requests

from llm_cli.clients.config import config_manager
from llm_cli.modules.tool_registry import tool
from llm_cli.modules.tools.web import web_tool_handler


@web_tool_handler
def web_search(query: str, count: int = 10) -> str:
    """
    Search the web using Brave Search API.
    """
    api_key = config_manager.get("brave", "api_key")
    if not api_key:
        return (
            "Error: Brave API key is not configured. Please set the BRAVE_API_KEY environment "
            "variable or 'api_key' in the [brave] section of your config file."
        )

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": min(count, 20)}

    # Brave Search API endpoint
    url = "https://api.search.brave.com/res/v1/web/search"

    # Implement retry logic for transient network errors (e.g. DNS resolution)
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = curl_requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30,
                impersonate="chrome",
            )
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            # Retry on DNS resolution failure (curl error 6) or other transient errors
            if attempt < max_retries - 1 and (
                "curl: (6)" in str(e) or "Could not resolve host" in str(e) or "timed out" in str(e)
            ):
                time.sleep(1.5 * (attempt + 1))  # Exponential-ish backoff
                continue
            raise

    # Extract web search results
    results = data.get("web", {}).get("results", [])
    if not results:
        return "No search results found."

    output = []
    for res in results:
        title = res.get("title", "No Title")
        link = res.get("url", "No URL")
        description = res.get("description", "No description available.")
        output.append(f"Title: {title}\nURL: {link}\nSnippet: {description}\n")

    return "\n---\n".join(output)


# Condition to register the tool in the AI agent's toolbelt.
# This ensures it's only "loaded" when the API key is available.
if config_manager.get("brave", "api_key"):
    tool(
        name="brave_search",
        desc=(
            "Search the web for current information using the Brave Search API. "
            "Returns a list of relevant search results including titles, snippets, and URLs. "
            "Use this tool when you need to find information from the internet."
        ),
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query to execute."},
                "count": {
                    "type": "integer",
                    "description": "Number of results to return (max 20).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    )(web_search)
