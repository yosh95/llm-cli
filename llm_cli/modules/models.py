# llm_cli/modules/models.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class Role(str, Enum):
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

    text: Optional[str] = None
    inline_data: Optional[Dict[str, Any]] = None
    function_call: Optional[Dict[str, Any]] = None
    function_response: Optional[Dict[str, Any]] = None
    thought: Optional[str] = None
    thought_signature: Optional[str] = None


@dataclass
class Message:
    """A single message in a conversation."""

    role: Role
    parts: List[Union[str, ContentPart]]

    def get_text(self) -> str:
        """Helper to extract all text content from parts."""
        text_parts = []
        for p in self.parts:
            if isinstance(p, str):
                text_parts.append(p)
            elif isinstance(p, ContentPart) and p.text:
                text_parts.append(p.text)
        return "".join(text_parts)


@dataclass
class DataSource:
    """Input data sourced from files, URLs, or direct text."""

    content: Any
    content_type: str = "text/plain"
    is_file_or_url: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    conversation: List[Message] = field(default_factory=list)
    tools_enabled: bool = True
    system_prompt_enabled: bool = True
