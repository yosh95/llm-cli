# llm_cli/clients/ollama.py

import json
from typing import Any

from llm_cli.clients.base import ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.clients.openai_base import OpenAICompatibleClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "http://localhost:11434/v1/chat/completions"


class OllamaClient(OpenAICompatibleClient):
    """
    Client for interacting with Ollama via its OpenAI-compatible API.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Ollama client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="ollama",
                pdf_as_base64=False,
            ),
            **kwargs,
        )
        config_url = config_manager.get("ollama", "api_url")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import config_manager

        self.available_models = config_manager.get_model_aliases("ollama")

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the conversation history and new data to Ollama."""
        messages = self._build_messages(data)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if self.active_tools and self.tools_enabled:
            # Note: Not all Ollama models support tool calling.
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._post(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            res = response.json()

            choice = res["choices"][0]["message"]
            content = choice.get("content", "")
            thought_text = choice.get("reasoning_content", "")
            model_parts: list[str | ContentPart] = []

            if thought_text:
                model_parts.append(ContentPart(thought=thought_text))

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
            self._report_error("Ollama", e)
            return (None, None), None

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal history to Ollama (OpenAI-compatible) format."""
        return self._build_openai_compatible_messages(data)
