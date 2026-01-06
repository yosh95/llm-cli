# llm_cli/modules/tools/media.py

import base64
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool

# Default integrated image generation model as requested by the user
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"


@tool(
    name="attach_file",
    description="Attach a file (image, PDF, audio, video, text) to context.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path to the file."}},
        "required": ["path"],
    },
)
def attach_file(path: str) -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"result": f"Error: File not found: {path}"}

        # process_file returns {content, content_type, [file_uri]}
        res = process_file(p, pdf_as_base64=True)
        if not res:
            return {"result": f"Error: Failed to process file: {path}"}

        return {
            "result": f"Successfully attached {path} ({res.get('content_type')})",
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": res["content_type"],
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return {"result": f"Error: {e}"}


@tool(
    name="generate_image",
    description=(
        "Generate an image based on a detailed prompt and save it to the local "
        "filesystem. Currently only available for Google/Gemini provider where "
        "image generation is integrated. Use this when the user asks to create "
        "an image, slide, or visual."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "A detailed description of the image to generate.",
            },
            "output_path": {
                "type": "string",
                "description": (
                    "The local path to save the image (e.g., 'images/my_slide.png'). "
                    "If not provided, it will be saved to the 'images/' directory "
                    "with a timestamped name."
                ),
            },
        },
        "required": ["prompt"],
    },
    supported_providers=["google"],
)
def generate_image(prompt: str, output_path: Optional[str] = None) -> dict:
    """
    Generates an image using Gemini's integrated image generation (generateContent).
    """
    api_key = get_setting("api_key", "google")
    image_model = get_setting("image_model", "google") or DEFAULT_IMAGE_MODEL

    if not api_key:
        return {
            "result": (
                "Error: Image generation is currently only supported via the "
                "Google/Gemini provider, and no Google API key was found in config."
            )
        }

    # Default to 'images' directory in the current project
    if not output_path:
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(images_dir / f"generated_{now}_{uuid.uuid4().hex[:4]}.png")

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Integrated image generation uses the standard generateContent endpoint
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{image_model}:generateContent"
    )

    try:
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        # Payload for integrated image generation via generateContent
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"Generate an image based on this prompt: {prompt}"}
                    ]
                }
            ]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=90)

        if response.status_code == 404:
            return {
                "result": (
                    f"Error: Model '{image_model}' not found. "
                    "Please check 'image_model' in your config."
                )
            }

        response.raise_for_status()
        data = response.json()

        # Extract image data from the response candidates
        if "candidates" not in data or not data["candidates"]:
            return {"result": f"Error: No candidates returned. Response: {data}"}

        found_image = None
        for candidate in data["candidates"]:
            for part in candidate.get("content", {}).get("parts", []):
                if "inlineData" in part:
                    inline_data = part["inlineData"]
                    if inline_data.get("mimeType", "").startswith("image/"):
                        found_image = inline_data
                        break
            if found_image:
                break

        if not found_image:
            # Fallback check for text response that might explain why generation failed
            text_resp = ""
            for candidate in data["candidates"]:
                for part in candidate.get("content", {}).get("parts", []):
                    if "text" in part:
                        text_resp += part["text"]

            error_msg = "Error: Model did not return an image."
            if text_resp:
                error_msg += f" Response text: {text_resp}"
            return {"result": error_msg}

        # Save to local file
        b64_data = found_image["data"]
        mime_type = found_image["mimeType"]
        img_bytes = base64.b64decode(b64_data)

        # Adjust extension if necessary based on mime_type
        if mime_type == "image/jpeg" and out_p.suffix.lower() == ".png":
            out_p = out_p.with_suffix(".jpg")

        out_p.write_bytes(img_bytes)

        abs_path = out_p.absolute()
        return {
            "result": f"Image successfully generated and saved locally to: {abs_path}",
            "__llm_cli_data__": {
                "content": b64_data,
                "content_type": mime_type,
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return {"result": f"Error during image generation with {image_model}: {e}"}
