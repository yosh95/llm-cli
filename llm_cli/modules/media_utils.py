# llm_cli/modules/media_utils.py

import base64
import datetime
import ipaddress
import logging
import re
import socket
import urllib.parse
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import filetype
import markdownify
import pdfplumber
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)


def validate_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve all IPs for the hostname to prevent DNS rebinding and
        # numeric IP bypass
        try:
            for _, _, _, _, sockaddr in socket.getaddrinfo(
                hostname, None, proto=socket.IPPROTO_TCP
            ):
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_multicast
                    or ip_str == "0.0.0.0"
                ):
                    return False
        except (socket.gaierror, ValueError):
            return False

        return True
    except Exception:
        return False


def read_pdf_text(source: Path | BytesIO) -> str:
    """Reads PDF text using pdfplumber, prioritizing Japanese text continuity."""
    try:
        with pdfplumber.open(source) as pdf:
            text_list = []
            for page in pdf.pages:
                # Use x_tolerance=1.5 (default 3 too large for LaTeX/arXiv PDFs)
                # y_tolerance=3. use_text_flow=True helps multi-column papers.
                text = page.extract_text(x_tolerance=1.5, y_tolerance=3, use_text_flow=True)
                if text:
                    # Simple heuristic to join lines for better Japanese continuity.
                    lines = text.splitlines()
                    joined_lines = []
                    current = ""
                    for line in lines:
                        line = line.strip()
                        if not line:
                            if current:
                                joined_lines.append(current)
                                current = ""
                            continue
                        if current:
                            # Join lines that don't end with sentence-ending
                            # punctuation.
                            if re.search(r"[。！？」』）\)\!\?]$", current):
                                joined_lines.append(current)
                                current = line
                            else:
                                # Join without space if Japanese characters
                                # are detected.
                                if re.search(
                                    r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]",
                                    current + line,
                                ):
                                    current += line
                                else:
                                    current += " " + line
                        else:
                            current = line
                    if current:
                        joined_lines.append(current)
                    text_list.append("\n".join(joined_lines))
            return "\n".join(text_list)
    except Exception as e:
        logger.debug(f"PDF extraction failed for {source}: {e}")
        return ""


def encode_file_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def fetch_url_content(url: str, pdf_as_base64: bool = True) -> tuple[str | None, str | None]:
    if not validate_url(url):
        return None, None
    try:
        # Disable automatic redirect following so we can validate every hop.
        # Without this, a redirect from a public URL to an internal address
        # (e.g. http://169.254.169.254/) would bypass the validate_url() check
        # performed above — a classic SSRF via open redirect.
        response = curl_requests.get(
            url,
            impersonate="chrome",
            headers={"Connection": "close"},
            timeout=30,
            allow_redirects=False,
        )

        # If the server issues a redirect, re-validate the destination before
        # following it.  We follow at most one level manually; deeper chains
        # are refused to prevent redirect-loop abuse.
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "").strip()
            if not location or not validate_url(location):
                logger.warning(f"SSRF guard: redirect from '{url}' to '{location}' blocked.")
                return None, None
            response = curl_requests.get(
                location,
                impersonate="chrome",
                headers={"Connection": "close"},
                timeout=30,
                allow_redirects=False,  # no further hops
            )
            # A second redirect is refused outright.
            if response.status_code in (301, 302, 303, 307, 308):
                logger.warning(f"SSRF guard: chained redirect from '{location}' refused.")
                return None, None

        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0]

        if content_type == "application/pdf":
            if pdf_as_base64:
                return (
                    base64.b64encode(response.content).decode("utf-8"),
                    content_type,
                )
            else:
                return read_pdf_text(BytesIO(response.content)), "text/plain"

        if "text/html" in content_type:
            # Using markdownify to convert HTML to Markdown text
            html_content = re.sub(r"(?is)<script.*?>.*?</script>", "", response.text)
            html_content = re.sub(r"(?is)<style.*?>.*?</style>", "", html_content)
            text = markdownify.markdownify(html_content, heading_style="ATX")
            return text, "text/plain"

        if content_type.startswith("text/"):
            return response.text, "text/plain"

        if any(t in content_type for t in ["image/", "audio/", "video/"]):
            return (base64.b64encode(response.content).decode("utf-8"), content_type)

        return None, None
    except Exception as e:
        logger.warning(f"Failed to fetch URL content from {url}: {e}")
        return None, None


def process_file(path: Path, pdf_as_base64: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        return None

    kind = filetype.guess(str(path))
    mime = kind.mime if kind else "application/octet-stream"

    try:
        res: dict[str, Any] = {"content_type": mime, "filename": path.name}
        if mime == "application/pdf":
            if pdf_as_base64:
                res["content"] = encode_file_base64(path)
                return res
            else:
                res["content"] = read_pdf_text(path)
                res["content_type"] = "text/plain"
                return res

        if any(mime.startswith(t) for t in ["image/", "audio/", "video/"]):
            res["content"] = encode_file_base64(path)
            return res

        # Default to text
        res["content"] = path.read_text(encoding="utf-8", errors="ignore")
        res["content_type"] = "text/plain"
        return res
    except Exception:
        return None


def generate_safe_filename(
    text: str, prefix: str = "output", ext: str = "png", max_len: int = 50
) -> str:
    """Generates a safe and descriptive filename from text."""
    # Remove non-alphanumeric chars, replace with underscores
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    clean = re.sub(r"[-\s]+", "_", clean).strip("_")

    # Truncate
    if len(clean) > max_len:
        clean = clean[:max_len].rsplit("_", 1)[0]

    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    rand_id = uuid.uuid4().hex[:4]

    if not clean:
        return f"{prefix}_{now_str}_{rand_id}.{ext}"

    return f"{clean}_{now_str}_{rand_id}.{ext}"
