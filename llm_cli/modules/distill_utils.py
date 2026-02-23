import json
from pathlib import Path
from typing import Any

from llm_cli.modules.models import ContentPart, Message


def serialize_conversation_for_distill(conversation: list[Message]) -> dict[str, Any]:
    """
    Converts a conversation history into a format suitable for Mamba SFT.
    """
    serialized_conv = []
    for msg in conversation:
        content = ""
        for p in msg.parts:
            if isinstance(p, str):
                content += p
            elif isinstance(p, ContentPart):
                if p.text:
                    content += p.text
                if p.thought:
                    # Capture the reasoning process as well,
                    # as it's valuable for distillation.
                    content = f"<thought>{p.thought}</thought>\n" + content
                if p.function_call:
                    call_str = json.dumps(p.function_call)
                    content += f"\n<tool_call>{call_str}</tool_call>"
                if p.function_response:
                    resp_str = json.dumps(p.function_response)
                    content += f"\n<tool_response>{resp_str}</tool_response>"

        serialized_conv.append({"role": msg.role.value, "content": content})

    return {"messages": serialized_conv}


def append_to_distill_data(output_path: Path, conversation: list[Message]) -> None:
    """Appends a single conversation to the distill data JSONL file."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = serialize_conversation_for_distill(conversation)

        with output_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        # We don't want to crash the main app if logging fails
        print(f"Failed to save distill data: {e}")
