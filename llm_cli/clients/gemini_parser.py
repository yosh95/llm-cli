# llm_cli/clients/gemini_parser.py

from typing import Any
from urllib.parse import urlparse

from llm_cli.modules.models import ContentPart, Message, Role


def parse_generate_content_response(response_json: dict[str, Any]) -> Message:
    """Parses generateContent API response into internal Message format."""
    candidates = response_json.get("candidates", [])
    if not candidates:
        return Message(role=Role.MODEL, parts=[ContentPart(text="[No output from model]")])

    candidate = candidates[0]
    content = candidate.get("content", {})
    raw_parts = content.get("parts", [])

    grounding_metadata = (
        candidate.get("groundingMetadata")
        or candidate.get("grounding_metadata")
        or response_json.get("groundingMetadata")
        or response_json.get("ground_metadata")
    )

    model_parts: list[str | ContentPart] = []
    for part in raw_parts:
        thought_sig: str | None = part.get("thoughtSignature") or part.get("thought_signature")

        if part.get("thought"):
            model_parts.append(
                ContentPart(
                    thought=part.get("text", ""),
                    thought_signature=thought_sig,
                )
            )

        elif "text" in part:
            model_parts.append(ContentPart(text=part["text"], thought_signature=thought_sig))

        elif "functionCall" in part or "function_call" in part:
            fc = part.get("functionCall") or part.get("function_call")
            if fc:
                model_parts.append(
                    ContentPart(
                        function_call={
                            "id": fc.get("id", fc.get("name")),
                            "name": fc.get("name"),
                            "args": fc.get("args", {}),
                        },
                        thought_signature=thought_sig,
                    )
                )

        elif "toolCall" in part or "tool_call" in part:
            tc = part.get("toolCall") or part.get("tool_call")
            if tc:
                tool_type = tc.get("toolType", tc.get("tool_type", "unknown"))
                model_parts.append(
                    ContentPart(
                        text=f"[Built-in Tool Call: {tool_type}]",
                        thought_signature=thought_sig,
                        is_diagnostic=True,
                    )
                )

        elif "toolResponse" in part or "tool_response" in part:
            tr = part.get("toolResponse") or part.get("tool_response")
            if tr:
                tool_type = tr.get("toolType", tr.get("tool_type", "unknown"))
                model_parts.append(
                    ContentPart(
                        text=f"[Built-in Tool Response: {tool_type}]",
                        thought_signature=thought_sig,
                        is_diagnostic=True,
                    )
                )

        elif "inlineData" in part or "inline_data" in part:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline:
                model_parts.append(
                    ContentPart(
                        inline_data={
                            "mimeType": inline.get(
                                "mimeType", inline.get("mime_type", "image/png")
                            ),
                            "data": inline.get("data"),
                        },
                        thought_signature=thought_sig,
                    )
                )

    if grounding_metadata:
        model_parts.append(
            ContentPart(
                text=_format_grounding_metadata(grounding_metadata),
                is_diagnostic=False,  # Shown as part of output
            )
        )

    return Message(role=Role.MODEL, parts=model_parts)


def _format_grounding_metadata(metadata: dict[str, Any]) -> str:
    """Formats grounding metadata (sources) into a readable string."""
    chunks = metadata.get("groundingChunks") or metadata.get("grounding_chunks", [])
    if not chunks:
        return ""

    sources_text = "\n\n---\n\n**Sources:**\n"
    num_sources = 0
    for chunk in chunks:
        web = chunk.get("web") or chunk.get("web_metadata", {})
        uri = web.get("uri") or web.get("url")
        if uri:
            num_sources += 1
            title = web.get("title", "")
            if not title or title.startswith("Source ") or title.isdigit():
                domain = urlparse(uri).netloc
                title = domain.replace("www.", "") if domain else f"Source {num_sources}"
            sources_text += f"{num_sources}. [{title}]({uri})\n"

    return sources_text if num_sources > 0 else ""
