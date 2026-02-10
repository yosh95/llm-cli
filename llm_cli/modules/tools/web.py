# llm_cli/modules/tools/web.py

import re

import cloudscraper
import markdownify
import requests

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import fetch_url_content
from llm_cli.modules.tool_registry import tool

# Check for Google Search configuration
_google_api_key = get_setting("api_key", "google")
_google_cse_id = get_setting("cse_id", "google")


if _google_api_key and _google_cse_id:

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
        if not _google_api_key or not _google_cse_id:
            return "Error: Web Search configuration missing."

        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": _google_api_key,
                    "cx": _google_cse_id,
                    "q": query,
                    "num": 10,
                },
                headers={"Connection": "close"},
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
    name="read_html_from_url",
    description=(
        "Fetch a web page URL and convert the HTML content to Markdown text. "
        "Use this for reading articles, blog posts, or documentation pages. "
        "If the URL points to a PDF, use 'read_pdf_from_url' instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL."},
            "max_length": {
                "type": "integer",
                "description": (
                    "Maximum number of characters to return (default: 50000). "
                    "Set to 0 for no limit."
                ),
            },
            "explanation": {"type": "string", "description": "Reason for fetching."},
        },
        "required": ["url"],
    },
)
def read_html_from_url(url: str, max_length: int = 50000) -> str:
    try:
        resp = cloudscraper.create_scraper().get(
            url, headers={"Connection": "close"}, timeout=30
        )
        ctype = resp.headers.get("Content-Type", "").lower()

        if "text/html" not in ctype:
            return (
                f"Error: URL returned {ctype}, expected text/html. "
                "Use 'read_pdf_from_url' for PDFs or 'read_image_from_url' for images."
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
        if max_length > 0 and len(content) > max_length:
            content = (
                content[:max_length]
                + f"\n... (Truncated. Total length: {len(content)} chars. "
                "Use max_length parameter to retrieve more.)"
            )

        return content
    except Exception as e:
        return f"Error fetching or parsing {url}: {e}"


@tool(
    name="read_pdf_from_url",
    description=(
        "Download and extract text from a PDF URL. "
        "Use this specifically for online PDF documents, research papers, or manuals."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target PDF URL."}},
        "required": ["url"],
    },
)
def read_pdf_from_url(url: str) -> str:
    # Use fetch_url_content with pdf_as_base64=False to get text
    content, ctype = fetch_url_content(url, pdf_as_base64=False)

    if content is None or ctype is None:
        return "Error: Failed to fetch content or invalid URL."

    if "application/pdf" not in ctype and "text/plain" not in ctype:
        return f"Error: Expected PDF but got {ctype}. Content might not be a PDF."

    if not content.strip():
        return (
            "Error: Extracted text is empty. The PDF might be scanned images "
            "without text (OCR is not supported)."
        )

    return content


@tool(
    name="read_image_from_url",
    description="Fetch an image from a URL and return it for visual processing.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target Image URL."}},
        "required": ["url"],
    },
)
def read_image_from_url(url: str) -> str | dict:
    # Use fetch_url_content with pdf_as_base64=True (default) to get base64
    content, ctype = fetch_url_content(url, pdf_as_base64=True)

    if content is None or ctype is None:
        return "Error: Failed to fetch content or invalid URL."

    if not ctype.startswith("image/"):
        return f"Error: URL returned {ctype}, expected an image type."

    return {
        "result": f"Successfully fetched image from {url}",
        "__llm_cli_data__": {
            "content": content,
            "content_type": ctype,
            "is_file_or_url": True,
        },
    }
