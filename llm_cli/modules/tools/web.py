# llm_cli/modules/tools/web.py

import base64

import cloudscraper
import filetype
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
            "queries": {"type": "array", "items": {"type": "string"}},
            "num": {
                "type": "integer",
                "description": (
                    "Number of results to return per query (1-10). Default is 10."
                ),
                "default": 10,
            },
        },
        "required": ["queries"],
    },
)
def google_search(queries: list[str], num: int = 10) -> str:
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")
    if not api_key or not cse_id:
        return (
            "Error: Google Search is not configured. "
            "Please ensure both 'api_key' and 'cse_id' are set in the [google] section "
            "of your config.toml. You can use 'llm-cli-config' to set them."
        )

    # Clamp num to the valid range for Google Custom Search API (1-10)
    num = max(1, min(10, num))

    all_results = []
    for q in queries:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cse_id, "q": q, "num": num},
                timeout=15,
            )
            items = resp.json().get("items", [])
            results = [
                f"Title: {i.get('title')}\n"
                f"URL: {i.get('link')}\n"
                f"Snippet: {i.get('snippet')}\n"
                for i in items
            ]
            all_results.append(
                f"### Results for: {q}\n" + ("\n".join(results) or "No results.")
            )
        except Exception as e:
            all_results.append(f"Error searching '{q}': {e}")
    return "\n\n---\n\n".join(all_results)


@tool(
    name="fetch_url",
    description=(
        "Fetch content from a URL. Returns raw HTML for web pages. "
        "Use this only when you need the exact HTML structure or tags."
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
def fetch_url(
    url: str, start_offset: int = 0, max_length: int = 10000
) -> dict | str:
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        ctype = resp.headers.get("Content-Type", "")
        if any(t in ctype for t in ["pdf", "image/", "audio/"]):
            kind = filetype.guess(resp.content)
            mime = kind.mime if kind else ctype.split(";")[0]
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return {
                "result": f"Fetched {mime} from {url}. Added to context.",
                "__llm_cli_data__": {
                    "content": b64,
                    "content_type": mime,
                    "is_file_or_url": True,
                },
            }

        full_text = resp.text
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
        return f"Error fetching {url}: {e}"


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
def fetch_web_text(
    url: str, start_offset: int = 0, max_length: int = 10000
) -> str:
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
