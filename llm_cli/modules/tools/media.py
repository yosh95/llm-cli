# llm_cli/modules/tools/media.py

from pathlib import Path
from llm_cli.modules.tool_registry import tool
from llm_cli.modules.media_utils import process_file

@tool(
    name="attach_file",
    description="Attach a media file (PDF, image, video, audio) to the conversation context.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the media file."}
        },
        "required": ["path"]
    }
)
def attach_file(path: str) -> dict:
    try:
        p = Path(path)
        if not p.is_file():
            return {"result": f"Error: {path} is not a file."}

        res = process_file(p, pdf_as_base64=True)
        if not res:
            return {"result": f"Error: Could not process {path}."}

        mime = res["content_type"]
        if mime == "text/plain":
            return {"result": f"Notice: {path} is a text file. Use read_file instead."}

        return {
            "result": f"Successfully attached {mime} file: {path}.",
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": mime,
                "is_file_or_url": True
            }
        }
    except Exception as e:
        return {"result": f"Error attaching file: {e}"}
