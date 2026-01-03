# llm_cli/apps/ollama.py

import requests
from typing import Dict, List, Optional, Tuple

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "llama3"


class OllamaClient(BaseLlmClient):
    """A client for interacting with the Ollama API."""

    def __init__(self, initial_model_alias="default", **kwargs):
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="ollama",
            pdf_as_base64=False,
            **kwargs
        )
        self.host = self.api_key or "http://localhost:11434"

    def _load_model_aliases(self):
        from llm_cli.clients.config import get_model_aliases
        self.available_models = get_model_aliases("ollama")
        if 'default' not in self.available_models:
            self.available_models['default'] = FALLBACK_MODEL

    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        messages = []
        if self.system_prompt and self.system_prompt_enabled:
            messages.append({"role": "system", "content": self.system_prompt})

        for msg in self.conversation:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            content = ""
            for p in msg.get("parts", []):
                if "text" in p:
                    content += p["text"]
            messages.append({"role": role, "content": content})

        user_content = ""
        for item in data:
            user_content += item["content"]

        if user_content:
            messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        if not self.tools_enabled and self.active_tools:
            payload["tools"] = registry.get_openai_spec(self.active_tools)

        api_url = f"{self.host}/api/chat"

        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=120
            )
            self._log_debug(response_obj=response)
            response.raise_for_status()
            res_json = response.json()

            message = res_json.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            model_parts = []
            if content:
                model_parts.append({"text": content})

            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    model_parts.append({
                        "functionCall": {
                            "name": fn.get("name"),
                            "args": fn.get("arguments")
                        }
                    })

            if user_content:
                self.conversation.append({
                    "role": "user",
                    "parts": [{"text": user_content}]
                })

            model_msg = {"role": "model", "parts": model_parts}
            self.conversation.append(model_msg)

            return content, {}
        except Exception as e:
            self._report_error("Ollama", e)
            return None, None
