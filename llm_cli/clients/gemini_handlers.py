# llm_cli/clients/gemini_handlers.py

import base64
import mimetypes
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests

from llm_cli.clients.base import console
from llm_cli.modules.models import ContentPart, Message, Role

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient
    from llm_cli.modules.models import DataSource


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


def send_video_generation(
    client: "BaseLlmClient", data: list["DataSource"]
) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
    """Handles video generation via Gemini/Veo API."""
    prompt_parts = []
    # Gather text prompts
    for m in client.conversation:
        for p in m.parts:
            if isinstance(p, ContentPart) and p.text:
                prompt_parts.append(p.text)
            elif isinstance(p, str):
                prompt_parts.append(p)
    for d in data:
        if d.content_type == "text/plain":
            prompt_parts.append(str(d.content))

    full_prompt = "\n".join(prompt_parts)

    # Construct payload for Veo 3.1 (Vertex AI / AI Studio format)
    payload = {
        "instances": [{"prompt": full_prompt}],
        "parameters": {
            "sampleCount": 1,
        },
    }

    api_url = f"{client.BASE_API_URL}/models/{client.model}:predictLongRunning"  # type: ignore

    try:
        # Step 1: Start generation
        console.print(f"[dim]Starting video generation with {client.model}...[/dim]")
        response = client._post(  # type: ignore
            api_url,
            headers={
                "x-goog-api-key": client.api_key,
                "Content-Type": "application/json",
            },
            json_data=payload,
            timeout=client.request_timeout,
        )
        client._log_debug(response_obj=response, request_payload=payload)  # type: ignore
        response.raise_for_status()
        res_json = response.json()

        # response should contain 'name' which is the operation ID
        operation_name = res_json.get("name")
        if not operation_name:
            return ("Failed to get operation name for video generation.", ""), None

        # Step 2: Poll for results
        video_uri = None
        start_time = time.time()
        timeout_seconds = 1800  # 30 minutes

        console.print(
            "[dim]Video generation started. Polling for results... "
            "(this may take a few minutes)[/dim]"
        )

        while time.time() - start_time < timeout_seconds:
            poll_url = f"{client.BASE_API_URL}/{operation_name}"  # type: ignore

            poll_response = client._get(  # type: ignore
                poll_url,
                headers={"x-goog-api-key": client.api_key},
                timeout=client.request_timeout,
            )

            if poll_response.status_code == 200:
                op_res = poll_response.json()
                if op_res.get("done"):
                    if "error" in op_res:
                        err_msg = op_res["error"].get("message", "Unknown error")
                        return (f"Video generation failed: {err_msg}", ""), None

                    # Extract video URI
                    response_body = op_res.get("response", {})

                    # Try known patterns
                    predictions = response_body.get("predictions", [])
                    if predictions:
                        vid = predictions[0].get("video", {})
                        video_uri = vid.get("uri") or vid.get("url")
                        if not video_uri:
                            video_uri = predictions[0].get("url")

                    if not video_uri:
                        vid = response_body.get("result", {}).get("video", {})
                        video_uri = vid.get("uri") or vid.get("url")

                    if not video_uri:
                        gen_resp = response_body.get("generateVideoResponse", {})
                        samples = gen_resp.get("generatedSamples", [])
                        if samples:
                            vid = samples[0].get("video", {})
                            video_uri = vid.get("uri") or vid.get("url")

                    if video_uri:
                        break
                    else:
                        import json

                        debug_dump = json.dumps(op_res, indent=2, ensure_ascii=False)
                        return (
                            "Generation completed but no video URI found in response.\n"
                            f"Response dump:\n{debug_dump}",
                            "",
                        ), None

                time.sleep(5)
            else:
                time.sleep(5)

        if not video_uri:
            return ("Video generation timed out.", ""), None

        display_text = f"Successfully generated video.\n\n**Video URL:** `{video_uri}`"

        # Attempt to download and save locally
        video_data = None
        mime_type = None

        try:
            console.print("[dim]Downloading video content...[/dim]")
            vid_response = client._get(  # type: ignore
                video_uri,
                headers={"x-goog-api-key": client.api_key},
                timeout=client.request_timeout,
            )
            vid_response.raise_for_status()
            if vid_response.status_code == 200:
                video_bytes = vid_response.content
                mime_type = vid_response.headers.get("Content-Type", "video/mp4")
                video_data = base64.b64encode(video_bytes).decode("utf-8")
        except Exception as e:
            console.print(f"[yellow]Failed to download video: {e}[/yellow]")

        if video_data and mime_type:
            # Save inline using shared logic
            hint = full_prompt[:100]
            log, saved_path = client._save_inline_media_and_get_log_entry(  # type: ignore
                {"mimeType": mime_type, "data": video_data}, hint_text=hint
            )
            if log:
                display_text += f"\n\n{log}"

            model_msg = Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(text=display_text),
                    ContentPart(
                        inline_data={"mimeType": mime_type, "data": video_data}
                    ),
                ],
            )
            client.conversation.append(model_msg)
        else:
            client.conversation.append(
                Message(role=Role.MODEL, parts=[ContentPart(text=display_text)])
            )

        return (display_text.strip(), ""), None

    except Exception as e:
        client._report_error("Veo Video", e)  # type: ignore
        return (None, None), None
