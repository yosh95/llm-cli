# llm_cli/clients/grok.py

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.clients.mixins import OpenAICompatibleMixin
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.x.ai/v1/responses"
IMAGE_API_URL = "https://api.x.ai/v1/images/generations"


class GrokClient(BaseLlmClient, OpenAICompatibleMixin):
    """
    Client for interacting with the xAI Grok API.

    Uses the Responses API (/v1/responses) to leverage built-in tools
    like web_search and x_search.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Grok client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="xai",
                pdf_as_base64=False,
            ),
            **kwargs,
        )
        config_url = config_manager.get("xai", "api_url")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import config_manager

        self.available_models = config_manager.get_model_aliases("xai")

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        m = self.model.lower()
        return "image" in m

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Sends the conversation history and new data to Grok via Responses API."""
        if self._is_image_model():
            return self._send_image_generation(data)

        # Grok Responses API follows the same input structure as OpenAI Responses API
        input_messages = self._build_responses_messages(data)

        payload = {
            "model": self.model,
            "input": input_messages,
        }

        if self.active_tools and self.tools_enabled:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            # Parse Responses API response structure
            model_parts: list[str | ContentPart] = []
            full_text = ""
            thought_text = ""
            sources = []

            for block in res.get("output", []):
                b_type = block.get("type")

                if b_type == "message":
                    # New style Responses API message block
                    for part in block.get("content", []):
                        p_type = part.get("type")
                        if p_type == "output_text":
                            text_content = part.get("text", "")
                            # Collect citations from annotations
                            for ann in part.get("annotations", []):
                                if ann.get("type") == "url_citation":
                                    sources.append(
                                        {
                                            "title": ann.get("title", "source"),
                                            "url": ann.get("url", ""),
                                        }
                                    )
                            full_text += text_content
                            model_parts.append(ContentPart(text=text_content))
                        elif p_type == "thought":
                            thought = part.get("text", "")
                            thought_text += thought
                            model_parts.append(ContentPart(thought=thought))

                elif b_type == "text":
                    text_content = block.get("text", "")
                    # Grok Responses API also supports citations in the text block
                    if "citations" in block:
                        for cit in block["citations"]:
                            title = cit.get("title", "source")
                            url = cit.get("url", "")
                            sources.append({"title": title, "url": url})
                    full_text += text_content
                    model_parts.append(ContentPart(text=text_content))

                elif b_type == "reasoning":
                    # Responses API might return reasoning block separately
                    thought = block.get("text", "")
                    thought_text += thought
                    model_parts.append(ContentPart(thought=thought))

                elif b_type == "web_search_call":
                    model_parts.append(
                        ContentPart(
                            text=f"[Built-in Tool Call: web_search "
                            f"(ID: {block.get('id')})]",
                            is_diagnostic=True,
                        )
                    )

                elif b_type == "web_search_response":
                    model_parts.append(
                        ContentPart(
                            text=f"[Built-in Tool Response: web_search "
                            f"(ID: {block.get('tool_call_id')})]",
                            is_diagnostic=True,
                        )
                    )

                elif b_type == "tool_call":
                    tc_type = block.get("tool_type")
                    if tc_type == "function":
                        f = block.get("function", {})
                        model_parts.append(
                            ContentPart(
                                function_call={
                                    "id": block.get("id"),
                                    "name": f.get("name"),
                                    "args": json.loads(f.get("arguments", "{}")),
                                }
                            )
                        )
                    else:
                        model_parts.append(
                            ContentPart(
                                text=f"[Built-in Tool Call: {tc_type} "
                                f"(ID: {block.get('id')})]",
                                is_diagnostic=True,
                            )
                        )

                elif b_type == "tool_response":
                    tr_type = block.get("tool_type")
                    model_parts.append(
                        ContentPart(
                            text=f"[Built-in Tool Response: {tr_type} "
                            f"(ID: {block.get('tool_call_id')})]",
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
            self._report_error("Grok (Responses API)", e)
            return (None, None), None

    def _build_responses_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Custom message builder for Grok Responses API."""
        # Use the same logic as OpenAI Responses API
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": self.system_prompt}],
                }
            )

        for m in self.conversation:
            role = "assistant" if m.role == Role.MODEL else m.role.value
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        fr = p.function_response
                        msgs.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": str(
                                            fr.get("response", {}).get("result", "")
                                        ),
                                    }
                                ],
                            }
                        )
                continue

            content_parts: list[dict[str, Any]] = []
            for p in m.parts:
                if isinstance(p, str):
                    p_type = "output_text" if role == "assistant" else "input_text"
                    content_parts.append({"type": p_type, "text": p})
                elif isinstance(p, ContentPart):
                    if p.text:
                        p_type = "output_text" if role == "assistant" else "input_text"
                        content_parts.append({"type": p_type, "text": p.text})
                    if p.inline_data and role == "user":
                        mime = p.inline_data.get("mimeType", "")
                        if mime.startswith("image/"):
                            content_parts.append(
                                {
                                    "type": "input_image",
                                    "input_image": {
                                        "data": p.inline_data.get("data", "")
                                    },
                                }
                            )
                        elif mime == "application/pdf":
                            content_parts.append(
                                {
                                    "type": "input_file",
                                    "input_file": {
                                        "filename": p.inline_data.get(
                                            "filename", "document.pdf"
                                        ),
                                        "file_data": (
                                            f"data:{mime};base64,"
                                            f"{p.inline_data.get('data', '')}"
                                        ),
                                    },
                                }
                            )
                    if p.thought and role == "assistant":
                        # Grok uses 'thought' (reasoning) block in content too
                        content_parts.append({"type": "thought", "text": p.thought})

            if content_parts:
                msgs.append({"role": role, "content": content_parts})

        new_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                new_content.append({"type": "input_text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                new_content.append(
                    {"type": "input_image", "input_image": {"data": d.content}}
                )
            elif d.content_type == "application/pdf":
                new_content.append(
                    {
                        "type": "input_file",
                        "input_file": {
                            "filename": d.metadata.get("filename", "document.pdf"),
                            "file_data": (f"data:{d.content_type};base64,{d.content}"),
                        },
                    }
                )

        if new_content:
            msgs.append({"role": "user", "content": new_content})
        return msgs

    def _send_image_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Handles image generation via Grok API."""
        full_prompt = self._build_prompt_from_history(data)
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "n": 1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post(
                IMAGE_API_URL,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            return self._handle_image_generation_response(
                response.json(), full_prompt, data, "Grok"
            )
        except Exception as e:
            self._report_error("Grok Image", e)
            return (None, None), None

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal history to Grok (OpenAI-compatible) format."""
        return self._build_openai_compatible_messages(data)
