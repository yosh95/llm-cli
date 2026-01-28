# llm_cli/modules/tools/web.py

import re

import cloudscraper
import requests
from bs4 import BeautifulSoup, Comment

try:
    import markdownify
except ImportError:
    markdownify = None

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool


@tool(
    name="web_search",
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
def web_search(query: str) -> str:
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


def _convert_to_markdown_fallback(html_content: str) -> str:
    """Fallback Markdown converter using BeautifulSoup if markdownify is missing."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove unwanted tags
    for tag in soup(["script", "style", "meta", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Convert headers
    for i in range(1, 7):
        for h in soup.find_all(f"h{i}"):
            text = h.get_text().strip()
            if text:
                h.string = f"\n{'#' * i} {text}\n"
                h.unwrap()

    # Convert links
    for a in soup.find_all("a", href=True):
        text = a.get_text().strip()
        if text:
            a.string = f"[{text}]({a['href']})"
            a.unwrap()

    # Convert code blocks (pre)
    for pre in soup.find_all("pre"):
        code = pre.get_text()
        pre.string = f"\n```\n{code}\n```\n"
        pre.unwrap()

    # Convert lists (very simple approximation)
    for ul in soup.find_all("ul"):
        for li in ul.find_all("li", recursive=False):
            li.string = f"- {li.get_text().strip()}\n"
            li.unwrap()
        ul.unwrap()

    for ol in soup.find_all("ol"):
        for i, li in enumerate(ol.find_all("li", recursive=False)):
            li.string = f"{i+1}. {li.get_text().strip()}\n"
            li.unwrap()
        ol.unwrap()

    # Get text with separator
    text = soup.get_text(separator="\n")

    # Clean up excessive newlines
    lines = [line.strip() for line in text.splitlines()]
    clean_text = "\n".join(line for line in lines if line)

    return clean_text


@tool(
    name="fetch_web_markdown",
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
def fetch_web_markdown(url: str) -> str:
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        ctype = resp.headers.get("Content-Type", "").lower()

        if "text/html" not in ctype:
            return (
                f"Error: URL returned {ctype}, expected text/html. "
                "Use 'read_pdf_file' if it is a PDF."
            )

        if markdownify:
            # Configure markdownify to strip unwanted tags but keep structure
            content = markdownify.markdownify(
                resp.text, heading_style="ATX", strip=["script", "style"]
            )
            # Post-processing to remove excessive newlines
            content = re.sub(r"\n{3,}", "\n\n", content).strip()
        else:
            content = _convert_to_markdown_fallback(resp.text)

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
