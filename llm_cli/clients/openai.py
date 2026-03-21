# llm_cli/clients/openai.py

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

# OpenAI Responses API endpoint (recommended for reasoning models)
DEFAULT_API_URL = "https://api.openai.com/v1/responses"
IMAGE_API_URL = "https://api.openai.com/v1/images/generations"


class OpenAIClient(BaseLlmClient):
    """
    Client for interacting with OpenAI's Responses API and Images API.

    Supports vision, tool calling, reasoning modes with summary output,
    and chat gpt image generation.

    Note: This client uses the Responses API (not Chat Completions) for better
    support of reasoning models like GPT-5 and o-series. Reasoning tokens are
    not directly visible, but a summary can be retrieved via reasoning.summary.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the OpenAI client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="openai",
                pdf_as_base64=True,
            ),
            **kwargs,
        )
        # Load custom API URL if provided, otherwise use default
        config_url = config_manager.get("openai", "api_url")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        m = self.model.lower()
        return "dall-e" in m or "image" in m

    def _is_video_model(self) -> bool:
        """Determines if the current model is a video generation model."""
        m = self.model.lower()
        return "sora" in m

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """
        Sends the conversation history and new data to OpenAI Responses API.
        """
        if self._is_image_model():
            return self._send_image_generation(data)
        if self._is_video_model():
            return self._send_video_generation(data)

        input_items = self._build_input_items(data)
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
        }

        # Add system instructions if enabled
        if self.system_prompt and self.system_prompt_enabled:
            payload["instructions"] = self.system_prompt

        # Add tools if enabled
        if self.active_tools and self.tools_enabled:
            standard_tools = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )
            # Transform for Responses API: Move function fields to top level
            transformed_tools = []
            for t in standard_tools:
                if t.get("type") == "function" and "function" in t:
                    f = t["function"]
                    transformed_tools.append(
                        {
                            "type": "function",
                            "name": f.get("name"),
                            "description": f.get("description"),
                            "parameters": f.get("parameters"),
                        }
                    )
                else:
                    transformed_tools.append(t)
            payload["tools"] = transformed_tools

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

            model_parts: list[str | ContentPart] = []
            full_text = ""
            thought_text = ""

            # Parse Responses API output array
            for item in res.get("output", []):
                item_type = item.get("type")

                if item_type == "reasoning":
                    # Extract reasoning summary if available
                    summaries = item.get("summary", [])
                    for summary in summaries:
                        if summary.get("type") == "summary_text":
                            reasoning_text = summary.get("text", "")
                            if reasoning_text:
                                thought_text += reasoning_text
                                model_parts.append(ContentPart(thought=reasoning_text))

                elif item_type == "message":
                    # Extract text content from message
                    for content_block in item.get("content", []):
                        if content_block.get("type") == "output_text":
                            text_content = content_block.get("text", "")
                            if text_content:
                                full_text += text_content
                                model_parts.append(ContentPart(text=text_content))

                elif item_type == "function_call":
                    # Handle function/tool calls
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": item.get("call_id", item.get("id")),
                                "name": item.get("name"),
                                "args": json.loads(item.get("arguments", "{}")),
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)

            self._update_history(data, model_msg)
            return (full_text.strip(), thought_text.strip()), res.get("usage")
        except Exception as e:
            self._report_error("OpenAI", e)
            return (None, None), None

    def _send_image_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Handles image generation via OpenAI's Images API."""
        full_prompt = self._build_prompt_from_history(data)
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "n": 1,
            "size": "1024x1024",
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
                response.json(), full_prompt, data, "OpenAI"
            )
        except Exception as e:
            self._report_error("OpenAI Image", e)
            return (None, None), None

    def _send_video_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Handles video generation via OpenAI Sora API."""
        full_prompt = self._build_prompt_from_history(data)
        payload = {
            "model": self.model,
            "prompt": full_prompt,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return self._send_deferred_generation(
            start_url="https://api.openai.com/v1/videos",
            payload=payload,
            headers=headers,
            provider_name="OpenAI Sora",
            poll_url_template="https://api.openai.com/v1/videos/{}",
            data=data,
            status_key="status",
            completed_value="completed",
        )

    def _build_input_items(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts the internal conversation history to OpenAI Responses API format."""
        items = []

        for m, responded_tool_ids in self._iter_history():
            if m.role == Role.TOOL:
                # Add function call outputs
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if self._is_valid_tool_id(tool_id, responded_tool_ids):
                            result = func_resp.get("response", {}).get("result", "")
                            items.append(
                                {
                                    "type": "function_call_output",
                                    "call_id": tool_id,
                                    "output": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else "user"
                content_parts = []
                function_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        content_parts.append({"type": "input_text", "text": p})
                    elif isinstance(p, ContentPart):
                        if p.text:
                            text_type = (
                                "output_text" if role == "assistant" else "input_text"
                            )
                            content_parts.append({"type": text_type, "text": p.text})
                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            if mime.startswith("image/"):
                                content_parts.append(
                                    {
                                        "type": "input_image",
                                        "image_url": (
                                            f"data:{mime};base64,"
                                            f"{p.inline_data.get('data', '')}"
                                        ),
                                    }
                                )
                            elif mime == "application/pdf":
                                part: dict[str, Any] = {
                                    "type": "input_file",
                                    "file_data": (
                                        f"data:{mime};base64,"
                                        f"{p.inline_data.get('data', '')}"
                                    ),
                                    "filename": p.inline_data.get(
                                        "filename", "attachment.pdf"
                                    ),
                                }
                                content_parts.append(part)

                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if self._is_valid_tool_id(tool_id, responded_tool_ids):
                                function_calls.append(
                                    {
                                        "type": "function_call",
                                        "call_id": tool_id,
                                        "name": func_call.get("name", "unknown"),
                                        "arguments": json.dumps(
                                            func_call.get("args", {})
                                        ),
                                    }
                                )

                # Add message item
                if content_parts:
                    items.append(
                        {
                            "type": "message",
                            "role": role,
                            "content": content_parts,
                        }
                    )

                # Add function calls separately
                for fc in function_calls:
                    items.append(fc)

        # Append incoming data for the next user message
        user_content = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "input_text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{d.content_type};base64,{d.content}",
                    }
                )
            elif d.content_type == "application/pdf":
                part = {
                    "type": "input_file",
                    "file_data": f"data:{d.content_type};base64,{d.content}",
                }
                if "filename" in d.metadata:
                    part["filename"] = d.metadata["filename"]
                user_content.append(part)

        if user_content:
            items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": user_content,
                }
            )

        return items
