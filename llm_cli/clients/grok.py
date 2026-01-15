# llm_cli/clients/grok.py

import json
from typing import Any, Dict, List, Optional, Tuple

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.x.ai/v1/chat/completions"
IMAGE_API_URL = "https://api.x.ai/v1/images/generations"


class GrokClient(BaseLlmClient):
    """
    Client for interacting with the xAI Grok API.

    Compatible with OpenAI-style chat completions.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs):
        """Initializes the Grok client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="xai",
            pdf_as_base64=False,
            **kwargs,
        )
        config_url = get_setting("api_url", "xai")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("xai")

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        m = self.model.lower()
        return "image" in m

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        """Sends the conversation history and new data to Grok."""
        if self._is_image_model():
            return self._send_image_generation(data)

        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "messages": messages,
        }

        # Enable reasoning if requested (compatible with Grok-3+)
        if self.reasoning_enabled:
            payload["reasoning_format"] = "raw"

        if self.active_tools and self.tools_enabled:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post_with_retry(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            choice = res["choices"][0]["message"]
            full_text = ""
            model_parts: List[ContentPart] = []

            # Extract reasoning/thought if present
            reasoning = choice.get("reasoning_content")
            if reasoning:
                model_parts.append(ContentPart(thought=reasoning))
                if self.reasoning_enabled:
                    full_text += f"\n> **Reasoning:** {reasoning}\n\n"

            content = choice.get("content", "")
            if content:
                full_text += content
                model_parts.append(ContentPart(text=content))

            if choice.get("tool_calls"):
                for tc in choice["tool_calls"]:
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "args": json.loads(tc["function"]["arguments"]),
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self._update_history(data, model_msg)

            return full_text.strip(), res.get("usage")
        except Exception as e:
            self._report_error("Grok", e)
            return None, None

    def _send_image_generation(
        self, data: List[DataSource]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Handles image generation via Grok API."""
        # Extract prompt from conversation and new data
        prompt_parts = []
        for m in self.conversation:
            for p in m.parts:
                if isinstance(p, ContentPart) and p.text:
                    prompt_parts.append(p.text)
                elif isinstance(p, str):
                    prompt_parts.append(p)
        for d in data:
            if d.content_type == "text/plain":
                prompt_parts.append(str(d.content))

        full_prompt = "\n".join(prompt_parts)
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
            response = self._post_with_retry(
                IMAGE_API_URL,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            data_item = res["data"][0]
            revised_prompt = data_item.get("revised_prompt", "")
            img_data = None
            mime_type = "image/png"  # Default

            # Handle both URL and Base64 response formats
            if "b64_json" in data_item:
                img_data = data_item["b64_json"]
            elif "url" in data_item:
                img_url = data_item["url"]
                from llm_cli.modules.media_utils import fetch_url_content

                img_data, fetched_mime = fetch_url_content(img_url)
                if fetched_mime:
                    mime_type = fetched_mime

            if not img_data:
                return "Failed to retrieve image data from the response.", None

            # Use shared media saving logic from BaseLlmClient
            display_text = self._save_inline_image_and_get_log_entry(
                {"mimeType": mime_type, "data": img_data}, hint_text=full_prompt[:100]
            )
            if not display_text:
                display_text = (
                    "Successfully generated image, but failed to save it locally."
                )

            if revised_prompt:
                display_text += f"\n**Revised Prompt:** {revised_prompt}"

            # Update history with the image data (base64)
            model_msg = Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(text=display_text),
                    ContentPart(
                        inline_data={"mimeType": mime_type, "data": img_data}
                    ),
                ],
            )
            self._update_history(data, model_msg)

            return display_text.strip(), None
        except Exception as e:
            self._report_error("Grok Image", e)
            return None, None

    def _update_history(self, data: List[DataSource], model_msg: Message):
        """Updates internal history."""
        user_parts: List[ContentPart] = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                user_parts.append(
                    ContentPart(
                        inline_data={
                            "mimeType": d.content_type,
                            "data": d.content,
                        }
                    )
                )

        if user_parts:
            self.conversation.append(Message(role=Role.USER, parts=user_parts))
        self.conversation.append(model_msg)

    def _build_messages(self, data: List[DataSource]) -> List[Dict[str, Any]]:
        """Converts internal history to Grok (OpenAI-compatible) format."""
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        responded_tool_ids = set()
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        tool_id = p.function_response.get("id")
                        if tool_id and tool_id != "unknown":
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        is_responded = (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        )
                        if is_responded:
                            result = func_resp.get("response", {}).get("result", "")
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "content": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else m.role.value
                msg_content = ""
                reasoning_content = None
                tool_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        msg_content += p
                    elif isinstance(p, ContentPart):
                        if p.text:
                            msg_content += p.text
                        if p.thought:
                            reasoning_content = p.thought
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            is_responded = (
                                tool_id
                                and tool_id != "unknown"
                                and tool_id in responded_tool_ids
                            )
                            if is_responded:
                                tool_calls.append(
                                    {
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": func_call.get("name", "unknown"),
                                            "arguments": json.dumps(
                                                func_call.get("args", {})
                                            ),
                                        },
                                    }
                                )

                if msg_content or reasoning_content or tool_calls:
                    msg = {"role": role, "content": msg_content or None}
                    if reasoning_content:
                        msg["reasoning_content"] = reasoning_content
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        user_content = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{d.content_type};base64,{d.content}"
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs
