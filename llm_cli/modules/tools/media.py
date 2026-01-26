# llm_cli/modules/tools/media.py

from pathlib import Path
from typing import Dict, Union

from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool


def _process_and_return(path: str, expected_types: tuple = None) -> Union[str, Dict]:
    """Helper to process file and return LLM-compatible structure."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: File not found: {path}"

        # process_file returns {content, content_type, [file_uri]}
        # pdf_as_base64=True ensures we get base64 content for PDFs
        res = process_file(p, pdf_as_base64=True)
        if not res:
            return f"Error: Failed to process file: {path}"

        content_type = res.get("content_type", "")

        # Validation if specific types are expected
        if expected_types:
            if not any(content_type.startswith(t) for t in expected_types):
                return (
                    f"Error: File '{path}' has type '{content_type}', "
                    f"but expected one of {expected_types}. "
                    "Please use the correct tool for this file type."
                )

        return {
            "result": f"Successfully read {path} ({content_type})",
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": res["content_type"],
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_pdf_file",
    desc="Read a PDF file and add it to the context.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file."}
        },
        "required": ["path"],
    },
)
def read_pdf_file(path: str) -> Union[str, Dict]:
    return _process_and_return(path, expected_types=("application/pdf",))


@tool(
    name="read_image_file",
    desc="Read an image file (PNG, JPG, WEBP, etc.) and add it to the context.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the image file."}
        },
        "required": ["path"],
    },
)
def read_image_file(path: str) -> Union[str, Dict]:
    return _process_and_return(path, expected_types=("image/",))


@tool(
    name="read_media_file",
    desc="Read an audio or video file and add it to the context.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the audio/video file."}
        },
        "required": ["path"],
    },
)
def read_media_file(path: str) -> Union[str, Dict]:
    return _process_and_return(path, expected_types=("audio/", "video/"))
