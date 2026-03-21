# llm_cli/clients/openai.py

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.clients.mixins import OpenAICompatibleMixin
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

# OpenAI Chat Completions API endpoint
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
IMAGE_API_URL = "https://api.openai.com/v1/images/generations"


class OpenAIClient(BaseLlmClient, OpenAICompatibleMixin):
    """
    Client for interacting with OpenAI's Chat Completions API and Images API.

    Supports vision, tool calling, and image generation.

    Uses the Chat Completions API (/v1/chat/completions) so that no conversation
    data is persisted server-side.  The full conversation history is managed
    locally and sent with every request.
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

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """
        Sends the conversation history and new data to OpenAI Chat Completions API.
        """
        if self._is_image_model():
            return self._send_image_generation(data)

        messages = self._build_openai_compatible_messages(data)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        # Add tools if enabled
        if self.active_tools and self.tools_enabled:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )
            payload["tool_choice"] = "auto"

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

            choice = res["choices"][0]
            message = choice["message"]

            model_parts: list[str | ContentPart] = []
            full_text = message.get("content") or ""
            if full_text:
                model_parts.append(ContentPart(text=full_text))

            # Parse tool calls
            for tc in message.get("tool_calls") or []:
                if tc.get("type") == "function":
                    f = tc["function"]
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": tc.get("id"),
                                "name": f.get("name"),
                                "args": json.loads(f.get("arguments", "{}")),
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self._update_history(data, model_msg)
            return (full_text.strip(), ""), res.get("usage")
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
