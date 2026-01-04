# llm_cli/modules/tools/media.py

from pathlib import Path

from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool


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
            "result": f"Successfully attached {path} " f"({res.get('content_type')})",
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": res["content_type"],
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return {"result": f"Error: {e}"}
