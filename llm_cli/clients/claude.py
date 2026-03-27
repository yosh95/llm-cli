# llm_cli/clients/claude.py

from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


class ClaudeClient(BaseLlmClient):
    """Client for the Anthropic Claude Messages API.

    Supports vision, tool calling, and extended thinking modes.

    Extended thinking allows Claude to reason through complex problems before
    responding.  Claude 4 models return summarised thinking content; Claude
    Sonnet 4.6 returns the full thinking output.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="anthropic",
                # PDFs are sent as base64-encoded ``document`` blocks; the
                # MediaManager must decode/encode the file before sending.
                pdf_as_base64=True,
            ),
            **kwargs,
        )

    def _build_claude_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        for m in self.conversation:
            if m.role == Role.TOOL:
                tool_content: list[dict[str, Any]] = []
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        fr = p.function_response
                        tool_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": fr.get("call_id") or fr.get("id"),
                                "content": str(
                                    fr.get("response", {}).get("result", "")
                                ),
                            }
                        )
                if tool_content:
                    msgs.append({"role": "user", "content": tool_content})
                continue

            role = "assistant" if m.role == Role.MODEL else "user"
            content: list[dict[str, Any]] = []
            for p in m.parts:
                if isinstance(p, str):
                    content.append({"type": "text", "text": p})
                elif isinstance(p, ContentPart):
                    if p.text:
                        content.append({"type": "text", "text": p.text})
                    if p.thought:
                        content.append(
                            {
                                "type": "thinking",
                                "thinking": p.thought,
                                "signature": p.thought_signature,
                            }
                        )
                    if p.inline_data:
                        mime = p.inline_data.get("mimeType", "")
                        if mime.startswith("image/"):
                            content.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": p.inline_data["data"],
                                    },
                                }
                            )
                        elif mime == "application/pdf":
                            content.append(
                                {
                                    "type": "document",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": p.inline_data["data"],
                                    },
                                }
                            )
                    if p.function_call:
                        # Use call_id if present (Grok/OpenAI Responses API),
                        # otherwise fall back to id.  This must match the
                        # tool_use_id used in the corresponding tool_result block.
                        tool_use_id = p.function_call.get(
                            "call_id"
                        ) or p.function_call.get("id")
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tool_use_id,
                                "name": p.function_call.get("name"),
                                "input": p.function_call.get("args", {}),
                            }
                        )
            if content:
                msgs.append({"role": role, "content": content})

        new_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                new_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                new_content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": d.content_type,
                            "data": d.content,
                        },
                    }
                )
            elif d.content_type == "application/pdf":
                new_content.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": d.content_type,
                            "data": d.content,
                        },
                    }
                )

        if new_content:
            msgs.append({"role": "user", "content": new_content})

        return msgs

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Send conversation history + *data* to the Claude Messages API."""
        from llm_cli.clients.config import config_manager

        messages = self._build_claude_messages(data)
        max_tokens = int(config_manager.get("anthropic", "max_tokens") or 8192)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        }

        try:
            if self.system_prompt and self.system_prompt_enabled:
                payload["system"] = [
                    {
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

            if self.active_tools and self.tools_enabled:
                payload["tools"] = registry.get_anthropic_spec(
                    self.active_tools, provider=self.config_section
                )

            # Always enable Prompt Caching
            payload["cache_control"] = {"type": "ephemeral"}

            response = self._post(
                self.API_URL,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            res = response.json()

            model_parts: list[str | ContentPart] = []
            full_text = ""
            thought_text = ""
            sources = []

            for block in res.get("content", []):
                if block["type"] == "text":
                    text_content = block["text"]
                    # Handle citations if present
                    if "citations" in block:
                        for cit in block["citations"]:
                            cit_type = cit.get("type")
                            if cit_type == "web_search_result_location":
                                title = cit.get("title", "source")
                                url = cit.get("url", "")
                                sources.append({"title": title, "url": url})
                    full_text += text_content
                    model_parts.append(ContentPart(text=text_content))
                elif block["type"] == "thinking":
                    thought = block["thinking"]
                    thought_text += thought
                    signature = block.get("signature")
                    model_parts.append(
                        ContentPart(thought=thought, thought_signature=signature)
                    )
                elif block["type"] == "tool_use":
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": block["id"],
                                "name": block["name"],
                                "args": block["input"],
                            }
                        )
                    )
                elif block["type"] == "server_tool_use":
                    model_parts.append(
                        ContentPart(
                            text=(
                                f"[Server Tool Use: {block.get('name')} "
                                f"(ID: {block.get('id')})]"
                            ),
                            is_diagnostic=True,
                        )
                    )
                elif block["type"] == "web_search_tool_result":
                    content = block.get("content", [])
                    for item in content:
                        if item.get("type") == "web_search_result":
                            sources.append(
                                {
                                    "title": item.get("title", "source"),
                                    "url": item.get("url", ""),
                                }
                            )
                    model_parts.append(
                        ContentPart(
                            text=f"[Web Search Tool Result: {len(content)} results]",
                            is_diagnostic=True,
                        )
                    )

            # Add sources legend if any were collected
            if sources:
                unique_sources = {}
                from urllib.parse import urlparse

                for s in sources:
                    u = s["url"]
                    if not u:
                        continue
                    if u not in unique_sources:
                        title = s["title"]
                        # If title is just a digit string, try to get domain
                        if title.isdigit() or title == "source":
                            domain = urlparse(u).netloc
                            if domain:
                                title = domain.replace("www.", "")
                        unique_sources[u] = title

                if unique_sources:
                    legend = "\n\n---\n\n**Sources:**\n"
                    for i, (url, title) in enumerate(unique_sources.items(), 1):
                        legend += f"{i}. [{title}]({url})\n"
                    full_text += legend
                    # Also append to the last text part for history persistence
                    for p in reversed(model_parts):
                        if isinstance(p, ContentPart) and p.text:
                            p.text += legend
                            break

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self._update_history(data, model_msg)

            return (model_msg.get_text().strip(), thought_text.strip()), res.get(
                "usage"
            )

        except Exception as e:
            self._report_error("Claude", e)
            return (None, None), None

    def utility_send(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if json_mode:
            # Force JSON via prompt as Claude doesn't have a strict json_mode yet
            payload["system"] += "\nRespond ONLY with a JSON object."

        response = self._post(self.API_URL, headers=headers, json_data=payload)
        response.raise_for_status()
        res = response.json()
        text = ""
        for block in res.get("content", []):
            if block["type"] == "text":
                text += block["text"]
        return text.strip()
