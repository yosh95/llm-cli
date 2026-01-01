# llm_cli/apps/gemini.py

import requests
import mimetypes
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from llm_cli.clients.base import BaseLlmClient, DataSource, console
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "gemini-flash-lite-latest"


class GeminiClient(BaseLlmClient):
    """A client for interacting with the Google Gemini API."""
    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta"
    UPLOAD_API_URL = (
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
    )
    REQUEST_TIMEOUT = 120
    # Increase upload timeout to 1 hour to support large files
    UPLOAD_TIMEOUT = 360
    UPLOAD_START_TIMEOUT = 20
    # PDF size threshold for using File API instead of inline base64
    PDF_FILE_API_THRESHOLD = 10 * 1024 * 1024  # 10MB

    def __init__(self, initial_model_alias="default", **kwargs):
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="google",
            pdf_as_base64=True,
            **kwargs
        )

    def _load_model_aliases(self):
        from llm_cli.clients.config import get_model_aliases
        self.available_models = get_model_aliases("google")
        if 'default' not in self.available_models:
            self.available_models['default'] = FALLBACK_MODEL

    def _process_single_source(self, source: str) -> Optional[DataSource]:
        """Override to handle Gemini-specific File API uploads for media."""
        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            import filetype
            kind = filetype.guess(str(path))
            mime = kind.mime if kind else mimetypes.guess_type(path)[0] or ""
            file_size = path.stat().st_size

            # Determine if we should use the File API
            # Videos and Audios ALWAYS use File API in this client
            # PDFs use File API if they are large
            use_file_api = (
                mime.startswith('audio/') or
                mime.startswith('video/') or
                (mime == 'application/pdf' and
                 file_size > self.PDF_FILE_API_THRESHOLD)
            )

            if use_file_api:
                upload_res = self._upload_file(path, mime_type=mime)
                if upload_res:
                    uri, mime_type = upload_res
                    return {
                        "file_uri": uri,
                        "content_type": mime_type,
                        "is_file_or_url": True
                    }
                else:
                    # If File API upload failed, we don't fall back for media
                    return None

        return super()._process_single_source(source)

    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        new_parts = []
        for item in data:
            if item.get("file_uri"):
                new_parts.append({
                    "file_data": {
                        "mime_type": item["content_type"],
                        "file_uri": item["file_uri"]
                    }
                })
            elif any(
                item["content_type"].startswith(t)
                for t in ["image/", "application/pdf"]
            ):
                new_parts.append({
                    "inlineData": {
                        "mimeType": item["content_type"],
                        "data": item["content"]
                    }
                })
            else:
                new_parts.append({"text": item["content"]})

        payload = self._to_provider_request_format(
            self.conversation, {}, new_parts
        )
        api_url = (
            f"{self.BASE_API_URL}/models/{self.model}:generateContent"
        )

        try:
            response = requests.post(
                api_url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=self.REQUEST_TIMEOUT
            )
            self._log_debug(response_obj=response)
            response.raise_for_status()
            res_json = response.json()

            model_msg, _ = self._from_provider_response_format(res_json)
            if new_parts:
                self.conversation.append({"role": "user", "parts": new_parts})
            self.conversation.append(model_msg)

            self.last_usage = res_json.get('usageMetadata')

            text = ""
            for p in model_msg["parts"]:
                if "text" in p:
                    text += p["text"]
                elif "thought" in p:
                    text += f"\n> **Thought:** {p['thought']}\n\n"
                elif "inlineData" in p:
                    log = self._save_inline_image_and_get_log_entry(
                        p["inlineData"]
                    )
                    if log:
                        text += log

            return text, self.last_usage
        except Exception as e:
            self._report_error("Gemini", e)
            return None, None

    def _to_provider_request_format(self, history, context, new_parts):
        contents = [{"role": m["role"], "parts": m["parts"]} for m in history]
        if new_parts:
            contents.append({"role": "user", "parts": new_parts})

        payload = {"contents": contents}
        if self.system_prompt and self.system_prompt_enabled:
            payload["system_instruction"] = {
                "parts": [{"text": self.system_prompt}]
            }

        if self.active_tools:
            payload["tools"] = registry.get_gemini_spec(self.active_tools)

        return payload

    def _from_provider_response_format(self, response_json):
        if not response_json.get('candidates'):
            return {
                "role": "model",
                "parts": [{"text": "[No response candidates]"}]
            }, {}
        candidate = response_json['candidates'][0]
        parts = candidate.get('content', {}).get('parts', [])
        return {"role": "model", "parts": parts}, {}

    def _upload_file(
        self, path: Path, mime_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(path)
        if not mime_type:
            return None
        file_size = path.stat().st_size

        # Step 1: Initiate resumable upload
        headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            console.print(
                f"[dim]Initiating upload for {path.name} "
                f"({file_size / 1024 / 1024:.2f} MB)...[/dim]"
            )
            start_response = requests.post(
                self.UPLOAD_API_URL,
                headers=headers,
                json={"file": {"display_name": path.name}},
                timeout=self.UPLOAD_START_TIMEOUT
            )
            start_response.raise_for_status()
            upload_url = start_response.headers["X-Goog-Upload-URL"]

            # Step 2: Upload the actual data
            console.print(f"[dim]Uploading {path.name}...[/dim]")
            with path.open("rb") as f:
                upload_response = requests.post(
                    upload_url,
                    data=f,
                    headers={
                        "Content-Length": str(file_size),
                        "X-Goog-Upload-Offset": "0",
                        "X-Goog-Upload-Command": "upload,finalize"
                    },
                    timeout=self.UPLOAD_TIMEOUT
                )
                upload_response.raise_for_status()
                file_info = upload_response.json()["file"]

            # Step 3: Wait for file to be ACTIVE (especially for video)
            if not self._wait_for_file_active(file_info["name"]):
                return None

            return file_info["uri"], mime_type
        except Exception as e:
            self._report_error("Upload", e)
            return None

    def _wait_for_file_active(self, file_name: str) -> bool:
        """Polls the file status until it is ACTIVE."""
        console.print("[dim]Waiting for remote file processing...[/dim]")
        url = f"{self.BASE_API_URL}/{file_name}?key={self.api_key}"

        # Poll for up to 10 minutes (120 * 5s)
        # Video processing can take significant time
        for i in range(120):
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                info = r.json()
                state = info.get("state")

                if state == "ACTIVE":
                    console.print("[green]File is now active.[/green]")
                    return True
                elif state == "FAILED":
                    error_msg = info.get("error", {}).get(
                        "message", "Unknown error"
                    )
                    console.print(
                        f"[red]Remote file processing failed: "
                        f"{error_msg}[/red]"
                    )
                    return False

                # PROCESSING or other state
                if i % 2 == 0:
                    console.print(
                        f"[dim]State: {state or 'UNKNOWN'} (polling...)[/dim]"
                    )
                time.sleep(5)
            except Exception as e:
                console.print(
                    f"[dim red]Error checking file status: {e}[/dim red]"
                )
                time.sleep(5)

        console.print("[red]Timeout waiting for file to become active.[/red]")
        return False
