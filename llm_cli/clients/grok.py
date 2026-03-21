# llm_cli/clients/grok.py

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.x.ai/v1/chat/completions"
IMAGE_API_URL = "https://api.x.ai/v1/images/generations"
VIDEO_GENERATION_URL = "https://api.x.ai/v1/videos/generations"
VIDEO_RESULT_URL_TEMPLATE = "https://api.x.ai/v1/videos/{}"


class GrokClient(BaseLlmClient):
    """
    Client for interacting with the xAI Grok API.

    Compatible with OpenAI-style chat completions.

    Note: Grok 4 performs internal reasoning but does NOT expose reasoning
    content via the API. The reasoning_content field is not returned even
    though reasoning tokens are billed. This is a limitation of the xAI API.
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
        return "image" in m and "video" not in m

    def _is_video_model(self) -> bool:
        """Determines if the current model is a video generation model."""
        m = self.model.lower()
        return "video" in m

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Sends the conversation history and new data to Grok."""
        # Check if we should use image generation path
        # If tools are enabled or there are images in the input, we might want the
        # chat path instead, but if the model is strictly an image model,
        # we stay on this path.
        if self._is_image_model():
            return self._send_image_generation(data)
        if self._is_video_model():
            return self._send_video_generation(data)

        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "messages": messages,
        }

        # Note: Grok 4 does NOT return reasoning_content via API.
        # We don't add any reasoning configuration as it has no effect
        # on the response format (reasoning tokens are still billed).

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

            choice = res["choices"][0]["message"]
            content = choice.get("content", "")
            thought_text = ""
            model_parts: list[str | ContentPart] = []

            # Note: reasoning_content is NOT returned by Grok 4 API
            # even though the model performs internal reasoning.
            # This code is kept for potential future API updates.
            reasoning = choice.get("reasoning_content")
            if reasoning:
                model_parts.append(ContentPart(thought=reasoning))
                thought_text += reasoning

            if content:
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

            return (content.strip(), thought_text.strip()), res.get("usage")
        except Exception as e:
            self._report_error("Grok", e)
            return (None, None), None

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

    def _send_video_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Handles video generation via Grok API (deferred)."""
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
            start_url=VIDEO_GENERATION_URL,
            payload=payload,
            headers=headers,
            provider_name="Grok Video",
            poll_url_template=VIDEO_RESULT_URL_TEMPLATE,
            data=data,
            status_key="status",
            completed_value="completed",
        )

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal history to Grok (OpenAI-compatible) format."""
        msgs: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        for m, responded_tool_ids in self._iter_history():
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if self._is_valid_tool_id(tool_id, responded_tool_ids):
                            result = func_resp.get("response", {}).get("result", "")
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(tool_id),
                                    "content": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else m.role.value
                content_parts: list[dict[str, Any]] = []
                tool_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        content_parts.append({"type": "text", "text": p})
                    elif isinstance(p, ContentPart):
                        if p.text:
                            content_parts.append({"type": "text", "text": p.text})
                        # Note: We don't include p.thought in history for Grok
                        # as Grok 4 doesn't return reasoning_content anyway

                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            if mime.startswith("image/"):
                                content_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{mime};base64,"
                                            f"{p.inline_data.get('data', '')}"
                                        },
                                    }
                                )

                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if self._is_valid_tool_id(tool_id, responded_tool_ids):
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

                if content_parts or tool_calls:
                    # If content_parts is just text, we can use simple format or array
                    # Grok supports array content format like OpenAI
                    msg: dict[str, Any] = {
                        "role": role,
                        "content": content_parts or None,
                    }
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        user_content: list[dict[str, Any]] = []
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
            from typing import cast

            msgs.append(cast(dict[str, Any], {"role": "user", "content": user_content}))

        return msgs
