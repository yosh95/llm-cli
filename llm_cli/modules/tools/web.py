# llm_cli/modules/tools/web.py

import requests
import base64
import cloudscraper
import filetype
from llm_cli.modules.tool_registry import tool
from llm_cli.clients.config import get_setting


@tool(
    name="google_search",
    description="Perform a Google Search.",
    parameters={
        "type": "object",
        "properties": {
            "queries": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["queries"]
    }
)
def google_search(queries: list[str]) -> str:
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")
    if not api_key or not cse_id:
        return "Error: Google API credentials not configured."

    all_results = []
    for q in queries:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cse_id, "q": q},
                timeout=15
            )
            items = resp.json().get("items", [])
            results = [
                f"Title: {i.get('title')}\n"
                f"URL: {i.get('link')}\n"
                f"Snippet: {i.get('snippet')}\n"
                for i in items
            ]
            all_results.append(
                f"### Results for: {q}\n" +
                ("\n".join(results) or "No results.")
            )
        except Exception as e:
            all_results.append(f"Error searching '{q}': {e}")
    return "\n\n---\n\n".join(all_results)


@tool(
    name="fetch_url",
    description="Fetch content from a URL.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL."}
        },
        "required": ["url"]
    }
)
def fetch_url(url: str) -> dict | str:
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        ctype = resp.headers.get('Content-Type', '')
        if any(t in ctype for t in ['pdf', 'image/', 'audio/']):
            kind = filetype.guess(resp.content)
            mime = kind.mime if kind else ctype.split(';')[0]
            b64 = base64.b64encode(resp.content).decode('utf-8')
            return {
                "result": f"Fetched {mime} from {url}. Added to context.",
                "__llm_cli_data__": {
                    "content": b64,
                    "content_type": mime,
                    "is_file_or_url": True
                }
            }
        return resp.text[:20000]
    except Exception as e:
        return f"Error fetching {url}: {e}"
