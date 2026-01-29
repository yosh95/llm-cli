# llm_cli/modules/tools/web.py

import re

import cloudscraper
import markdownify
import requests

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool


@tool(
    name="search_web",
    description=(
        "Perform a web search using Google to find information on the internet. "
        "Use this to answer questions about current events, documentation, "
        "or public data."
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
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")
    if not api_key or not cse_id:
        return (
            "Error: Web Search (Google) is not configured. "
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
    name="fetch_web_page",
    description=(
        "Fetch a URL and convert the content to Markdown. "
        "Preserves code blocks, headers, and links. "
        "Preferred over raw text for technical documentation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL."},
            "explanation": {"type": "string", "description": "Reason for fetching."},
        },
        "required": ["url"],
    },
)
def fetch_web_page(url: str) -> str:
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        ctype = resp.headers.get("Content-Type", "").lower()

        if "text/html" not in ctype:
            return (
                f"Error: URL returned {ctype}, expected text/html. "
                "Use 'read_pdf_content' if it is a PDF."
            )

        # Remove script and style tags via regex before processing
        # markdownify's 'strip' option only removes tags but keeps content
        html_content = re.sub(r"(?is)<script.*?>.*?</script>", "", resp.text)
        html_content = re.sub(r"(?is)<style.*?>.*?</style>", "", html_content)

        # Configure markdownify to strip unwanted tags but keep structure
        content = markdownify.markdownify(html_content, heading_style="ATX")
        # Post-processing to remove excessive newlines
        content = re.sub(r"\n{3,}", "\n\n", content).strip()

        # Truncate if too long (rough safety limit)
        max_len = 20000
        if len(content) > max_len:
            content = (
                content[:max_len]
                + f"\n... (Truncated. Total length: {len(content)} chars)"
            )

        return content
    except Exception as e:
        return f"Error fetching or parsing {url}: {e}"
