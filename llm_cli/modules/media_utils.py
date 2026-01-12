# llm_cli/modules/media_utils.py

import base64
import datetime
import ipaddress
import re
import urllib.parse
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cloudscraper
import filetype
from bs4 import BeautifulSoup
from pypdf import PdfReader

scraper = cloudscraper.create_scraper()


def validate_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                return False
        except ValueError:
            pass
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


def read_pdf_text(source: Union[Path, BytesIO]) -> str:
    try:
        reader = PdfReader(source)
        return "\n".join(
            page.extract_text() for page in reader.pages if page.extract_text()
        )
    except Exception:
        return ""


def encode_file_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def fetch_url_content(
    url: str, pdf_as_base64: bool = True
) -> Tuple[Optional[str], Optional[str]]:
    if not validate_url(url):
        return None, None
    try:
        response = scraper.get(url, timeout=30)
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
            soup = BeautifulSoup(response.content, "html.parser")
            return soup.get_text(" ", strip=True), "text/plain"

        if content_type.startswith("text/"):
            return response.text, "text/plain"

        if any(t in content_type for t in ["image/", "audio/", "video/"]):
            return (base64.b64encode(response.content).decode("utf-8"), content_type)

        return None, None
    except Exception:
        return None, None


def process_file(path: Path, pdf_as_base64: bool = True) -> Optional[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None

    kind = filetype.guess(str(path))
    mime = kind.mime if kind else "application/octet-stream"

    try:
        if mime == "application/pdf":
            if pdf_as_base64:
                return {"content": encode_file_base64(path), "content_type": mime}
            else:
                return {"content": read_pdf_text(path), "content_type": "text/plain"}

        if any(mime.startswith(t) for t in ["image/", "audio/", "video/"]):
            return {"content": encode_file_base64(path), "content_type": mime}

        # Default to text
        return {
            "content": path.read_text(encoding="utf-8", errors="ignore"),
            "content_type": "text/plain",
        }
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
