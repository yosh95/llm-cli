# llm_cli/clients/openai.py

from typing import Any

from llm_cli.clients.base import ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.clients.openai_base import OpenAICompatibleClient
from llm_cli.modules.models import DataSource
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.openai.com/v1/responses"
IMAGE_API_URL = "https://api.openai.com/v1/images/generations"


class OpenAIClient(OpenAICompatibleClient):
    """Client for OpenAI Responses API and Images API."""

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key", config_section="openai", pdf_as_base64=True
            ),
            **kwargs,
        )
        self.api_url = config_manager.get("openai", "api_url") or DEFAULT_API_URL

    def _is_image_model(self) -> bool:
        return "dall-e" in self.model.lower() or "image" in self.model.lower()

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        if self._is_image_model():
            return self._send_image_generation(data)

        tools = (
            registry.get_openai_spec(self.active_tools, provider=self.config_section)
            if self.active_tools and self.tools_enabled
            else None
        )
        payload = self._build_openai_payload(
            data, self.api_url, tools=tools, tools_enabled=self.tools_enabled
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
            (txt, thought), model_msg = self._parse_openai_response(res)
            self._update_history(data, model_msg)
            return (txt, thought), res.get("usage")
        except Exception as e:
            self._report_error("OpenAI", e)
            return (None, None), None

    def _send_image_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
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
