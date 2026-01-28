# llm_cli/modules/tools/web.py


import cloudscraper
import requests
from bs4 import BeautifulSoup

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool


@tool(
    name="google_search",
    description="Perform a Google Search.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
        },
        "required": ["query"],
    },
)
def google_search(query: str) -> str:
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")
    if not api_key or not cse_id:
        return (
            "Error: Google Search is not configured. "
            "Please ensure both 'api_key' and 'cse_id' are set in the [google] section "
            "of your config.toml. You can use 'llm-cli-config' to set them."
        )

    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cse_id, "q": query, "num": 10},
            timeout=15,
        )
        items = resp.json().get("items", [])
        if not items:
            return f"### Results for: {query}\nNo results."

        results = [
            f"Title: {i.get('title')}\n"
            f"URL: {i.get('link')}\n"
            f"Snippet: {i.get('snippet')}\n"
            for i in items
        ]
        return f"### Results for: {query}\n" + "\n".join(results)
    except Exception as e:
        return f"Error searching '{query}': {e}"


@tool(
    name="fetch_web_text",
    description=(
        "Fetch a URL and extract only the main text content, excluding "
        "HTML tags, scripts, and styles. This is the preferred tool for "
        "general information gathering to save tokens."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL."},
            "start_offset": {
                "type": "integer",
                "description": "Start character index for pagination.",
                "default": 0,
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return.",
                "default": 10000,
            },
        },
        "required": ["url"],
    },
)
def fetch_web_text(url: str, start_offset: int = 0, max_length: int = 10000) -> str:
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        ctype = resp.headers.get("Content-Type", "").lower()

        if "text/html" not in ctype:
            full_text = resp.text
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script and style elements
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()

            # Get text with a separator
            text = soup.get_text(separator="\n")

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            full_text = "\n".join(chunk for chunk in chunks if chunk)

        start = max(0, start_offset)
        end = start + max_length
        content = full_text[start:end]

        if len(full_text) > end:
            content += (
                f"\n... (Output truncated. Total chars: {len(full_text)}. "
                f"Use start_offset={end} to read more)"
            )

        return content
    except Exception as e:
        return f"Error fetching or parsing {url}: {e}"
