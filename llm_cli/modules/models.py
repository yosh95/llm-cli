# llm_cli/modules/models.py

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    MODEL = "model"
    TOOL = "tool"


@dataclass
class ContentPart:
    """
    A part of a message, which can be text or other data.
    Aligns with Gemini/OpenAI/Anthropic mixed content formats.
    """

    text: str | None = None
    inline_data: dict[str, Any] | None = None
    function_call: dict[str, Any] | None = None
    function_response: dict[str, Any] | None = None
    thought: str | None = None
    thought_signature: str | None = None
    # If true, this text is for diagnostic/internal use and should be hidden from UI
    is_diagnostic: bool = False


@dataclass
class Message:
    """A single message in a conversation."""

    role: Role
    parts: list[str | ContentPart]

    def get_text(self, include_diagnostic: bool = False) -> str:
        """Helper to extract all text content from parts."""
        text_parts = []
        for p in self.parts:
            if isinstance(p, str):
                text_parts.append(p)
            elif isinstance(p, ContentPart) and p.text:
                if not p.is_diagnostic or include_diagnostic:
                    text_parts.append(p.text)
        return "".join(text_parts)


@dataclass
class DataSource:
    """Input data sourced from files, URLs, or direct text."""

    content: Any
    content_type: str = "text/plain"
    is_file_or_url: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """Token usage tracking."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ClientState:
    """Current state of an LLM client session."""

    model: str
    provider: str
    conversation: list[Message] = field(default_factory=list)
    tools_enabled: bool = True
    system_prompt_enabled: bool = True
