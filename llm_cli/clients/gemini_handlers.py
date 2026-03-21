# llm_cli/clients/gemini_handlers.py

import mimetypes
import time
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from llm_cli.ui import console

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient


def upload_file(
    client: "BaseLlmClient", path: Path, mime_type: str | None = None
) -> tuple[str, str] | None:
    """Handles resumable upload to Gemini File API."""
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(path)
    if not mime_type:
        return None
    file_size = path.stat().st_size

    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
        "x-goog-api-key": client.api_key,
    }

    try:
        console.print(
            f"[dim]Initiating upload for {path.name} "
            f"({file_size / 1024 / 1024:.2f} MB)...[/dim]"
        )
        # Type hint for client methods if needed, but we assume it has these.
        # client is BaseLlmClient, which should have _post and _get.
        start_response = client._post(  # type: ignore
            client.UPLOAD_API_URL,  # type: ignore
            headers=headers,
            json_data={"file": {"display_name": path.name}},
            timeout=client.UPLOAD_START_TIMEOUT,  # type: ignore
        )
        start_response.raise_for_status()
        upload_url = start_response.headers["X-Goog-Upload-URL"]

        console.print(f"[dim]Uploading {path.name}...[/dim]")
        with path.open("rb") as f:
            upload_response = requests.post(
                upload_url,
                data=f,
                headers={
                    "Connection": "close",
                    "Content-Length": str(file_size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload,finalize",
                },
                timeout=client.UPLOAD_TIMEOUT,  # type: ignore
            )
            upload_response.raise_for_status()
            file_info = upload_response.json()["file"]

        if not wait_for_file_active(client, file_info["name"]):
            return None

        return file_info["uri"], mime_type
    except Exception as e:
        client._report_error("Upload", e)  # type: ignore
        return None


def wait_for_file_active(client: "BaseLlmClient", file_name: str) -> bool:
    """Polls the file status until it is ACTIVE."""
    console.print("[dim]Waiting for remote file processing...[/dim]")
    url = f"{client.BASE_API_URL}/{file_name}?key={client.api_key}"  # type: ignore

    for _i in range(120):
        try:
            r = client._get(url, timeout=10)  # type: ignore
            r.raise_for_status()
            info = r.json()
            state = info.get("state")

            if state == "ACTIVE":
                console.print("[dim]File is active.[/dim]")
                return True
            if state == "FAILED":
                console.print("[red]File processing failed.[/red]")
                return False

            time.sleep(5)
        except Exception as e:
            console.print(f"[dim red]Polling failed: {e}. Retrying...[/dim red]")
            time.sleep(5)

    console.print("[red]File processing timed out.[/red]")
    return False
