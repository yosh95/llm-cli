# llm_cli/clients/claude.py

from typing import Dict, List, Optional, Tuple

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.modules.tool_registry import registry


class ClaudeClient(BaseLlmClient):
    """A client for interacting with the Anthropic Claude API."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, initial_model_alias="default", **kwargs):
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="anthropic",
            pdf_as_base64=True,
            **kwargs,
        )

    def _load_model_aliases(self):
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("anthropic")

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if self.system_prompt and self.system_prompt_enabled:
            payload["system"] = self.system_prompt

        if self.active_tools:
            payload["tools"] = registry.get_anthropic_spec(
                self.active_tools, provider=self.config_section
            )

        # Enable extended thinking for Claude 3.7+
        # Note: budget_tokens is mandatory for Anthropic when thinking is enabled.
        if self.reasoning_enabled and "3-7" in self.model:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 1024}
            # max_tokens must be greater than budget_tokens
            if payload["max_tokens"] <= 1024:
                payload["max_tokens"] = 2048

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            response = self._post_with_retry(
                self.API_URL, headers=headers, json_data=payload, timeout=120
            )
            self._log_debug(response_obj=response)
            response.raise_for_status()
            res = response.json()

            model_parts = []
            full_text = ""
            for block in res.get("content", []):
                if block["type"] == "text":
                    full_text += block["text"]
                    model_parts.append({"text": block["text"]})
                elif block["type"] == "thinking":
                    thought = block["thinking"]
                    model_parts.append({"thought": thought})
                    full_text += f"\n> **Reasoning:** {thought}\n\n"
                elif block["type"] == "tool_use":
                    model_parts.append(
                        {
                            "functionCall": {
                                "id": block["id"],
                                "name": block["name"],
                                "args": block["input"],
                            }
                        }
                    )

            model_msg = {"role": "model", "parts": model_parts}
            self._update_history(data, model_msg)

            return full_text.strip(), res.get("usage")
        except Exception as e:
            self._report_error("Claude", e)
            return None, None

    def _update_history(self, data: List[DataSource], model_msg: Dict):
        user_parts = []
        for d in data:
            if d["content_type"] == "text/plain":
                user_parts.append({"text": d["content"]})
            else:
                user_parts.append(
                    {
                        "inlineData": {
                            "mimeType": d["content_type"],
                            "data": d["content"],
                        }
                    }
                )

        if user_parts:
            self.conversation.append({"role": "user", "parts": user_parts})
        self.conversation.append(model_msg)

    def _build_messages(self, data):
        msgs = []

        # Track tool_use_ids that have responses
        responded_tool_ids = set()
        for m in self.conversation:
            if m["role"] == "function":
                for p in m["parts"]:
                    if "functionResponse" in p:
                        func_resp = p["functionResponse"]
                        tool_id = func_resp.get("id")
                        if tool_id and tool_id != "unknown":
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m["role"] == "function":
                content = []
                for p in m["parts"]:
                    if "functionResponse" in p:
                        func_resp = p["functionResponse"]
                        tool_id = func_resp.get("id")
                        # Only include tool results that have corresponding tool uses
                        if (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        ):
                            result = func_resp.get("response", {}).get("result", "")
                            content.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(result),
                                }
                            )
                if content:
                    msgs.append({"role": "user", "content": content})
            else:
                role = "assistant" if m["role"] == "model" else m["role"]
                content = []
                for p in m["parts"]:
                    if "text" in p:
                        # Skip empty text blocks (Claude API requires non-empty text)
                        if p["text"].strip():
                            content.append({"type": "text", "text": p["text"]})
                    elif "functionCall" in p:
                        func_call = p["functionCall"]
                        tool_id = func_call.get("id")
                        # Only include tool uses that have responses
                        if (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        ):
                            content.append(
                                {
                                    "type": "tool_use",
                                    "id": tool_id,
                                    "name": func_call.get("name", "unknown"),
                                    "input": func_call.get("args", {}),
                                }
                            )
                if content:
                    msgs.append({"role": role, "content": content})

        user_content = []
        for d in data:
            if d["content_type"] == "text/plain":
                user_content.append({"type": "text", "text": d["content"]})
            elif d["content_type"].startswith("image/"):
                user_content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": d["content_type"],
                            "data": d["content"],
                        },
                    }
                )
            elif d["content_type"] == "application/pdf":
                user_content.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": d["content_type"],
                            "data": d["content"],
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})
        return msgs
