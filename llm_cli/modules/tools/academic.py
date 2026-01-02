# llm_cli/modules/tools/academic.py

import requests
import xml.etree.ElementTree as ET
from llm_cli.modules.tool_registry import tool


@tool(
    name="search_arxiv",
    description="Search for academic papers on arXiv. Returns titles, summaries, and PDF links.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'Large Language Models')."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return.",
                "default": 5
            }
        },
        "required": ["query"]
    }
)
def search_arxiv(query: str, max_results: int = 5) -> str:
    base_url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending"
    }

    try:
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)

        if not entries:
            return f"No papers found for query: {query}"

        results = []
        for entry in entries:
            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
            summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
            pdf_link = ""
            for link in entry.findall('atom:link', ns):
                if link.get('title') == 'pdf' or link.get('type') == 'application/pdf':
                    pdf_link = link.get('href')

            published = entry.find('atom:published', ns).text[:10]

            result_str = (
                f"### {title}\n"
                f"- **Published:** {published}\n"
                f"- **PDF Link:** {pdf_link}\n"
                f"- **Summary:** {summary[:500]}..."  # Truncated for efficiency
            )
            results.append(result_str)

        return "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Error searching arXiv: {e}"
