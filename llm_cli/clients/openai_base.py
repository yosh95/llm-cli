# llm_cli/clients/openai_base.py

from __future__ import annotations

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class OpenAICompatibleClient(BaseLlmClient):
    """
    Base class for LLM clients that use the OpenAI Chat Completions
    or Responses API format. Used by OpenAI, Ollama, and others.
    """

    def _build_openai_payload(
        self,
        data: list[DataSource],
        api_url: str,
        tools: list[dict[str, Any]] | None = None,
        tools_enabled: bool = True,
    ) -> dict[str, Any]:
        is_responses = api_url.endswith("/responses")
        if is_responses:
            payload = {"model": self.model, "input": self._build_responses_items(data)}
        else:
            payload = {"model": self.model, "messages": self._build_chat_messages(data)}

        if tools and tools_enabled:
            payload["tools"] = tools
            if not is_responses:
                payload["tool_choice"] = "auto"
        return payload

    def _parse_openai_response(self, res: dict[str, Any]) -> tuple[tuple[str, str], Message]:
        model_parts: list[str | ContentPart] = []
        full_text, thought_text = "", ""

        if "choices" in res:
            msg = res["choices"][0].get("message", {})
            if content := msg.get("content"):
                full_text = content
                model_parts.append(ContentPart(text=content))
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    f = tc.get("function", {})
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": tc.get("id"),
                                "name": f.get("name"),
                                "args": json.loads(f.get("arguments", "{}")),
                            }
                        )
                    )
        elif "output" in res:
            for block in res["output"]:
                b_type = block.get("type")
                if b_type == "message":
                    for part in block.get("content", []):
                        p_type = part.get("type")
                        if p_type == "output_text":
                            txt = part.get("text", "")
                            full_text += txt
                            model_parts.append(ContentPart(text=txt))
                            if ann := part.get("annotations"):
                                self._process_ann(ann, model_parts)
                        elif p_type == "thought":
                            th = part.get("text", "")
                            thought_text += th
                            model_parts.append(ContentPart(thought=th))
                elif b_type in ("text", "thought", "reasoning"):
                    txt = block.get("text", "")
                    if b_type == "text":
                        full_text += txt
                        model_parts.append(ContentPart(text=txt))
                        if cit := block.get("citations"):
                            self._process_ann(cit, model_parts)
                    else:
                        thought_text += txt
                        model_parts.append(ContentPart(thought=txt))
                elif b_type in ("tool_call", "function_call"):
                    f = block.get("function", {}) if b_type == "tool_call" else block
                    args = f.get("arguments", "{}")
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": block.get("id"),
                                "call_id": block.get("call_id"),
                                "name": f.get("name"),
                                "args": (json.loads(args) if isinstance(args, str) else args),
                            }
                        )
                    )
        return (full_text.strip(), thought_text.strip()), Message(
            role=Role.MODEL, parts=model_parts
        )

    def _process_ann(self, ann: list[dict[str, Any]], parts: list[str | ContentPart]) -> None:
        for a in ann:
            if "url" in a:
                parts.append(
                    ContentPart(
                        text=f"\n- [{a.get('title', 'Source')}]({a.get('url')})",
                        is_diagnostic=True,
                    )
                )

    def _build_openai_compatible_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Compatibility alias for standard chat format."""
        return self._build_chat_messages(data)

    def _build_chat_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        fr = p.function_response
                        msgs.append(
                            {
                                "role": "tool",
                                "tool_call_id": fr.get("call_id") or fr.get("id"),
                                "content": str(fr.get("response", {}).get("result", "")),
                            }
                        )
                continue
            role = "assistant" if m.role == Role.MODEL else m.role.value
            content: list[dict[str, Any]] = []
            tool_calls = []
            for p in m.parts:
                if isinstance(p, str):
                    content.append({"type": "text", "text": p})
                elif isinstance(p, ContentPart):
                    if p.text:
                        content.append({"type": "text", "text": p.text})
                    if p.thought:
                        content.append(
                            {
                                "type": "text",
                                "text": f"<thought>\n{p.thought}\n</thought>",
                            }
                        )
                    if p.inline_data:
                        mime = p.inline_data.get("mimeType", "")
                        b64 = p.inline_data.get("data", "")
                        if mime.startswith("image/"):
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                }
                            )
                        elif mime == "application/pdf":
                            content.append(
                                {
                                    "type": "file",
                                    "file": {
                                        "filename": p.inline_data.get("filename", "doc.pdf"),
                                        "file_data": f"data:{mime};base64,{b64}",
                                    },
                                }
                            )
                    if p.function_call:
                        tool_calls.append(
                            {
                                "id": p.function_call.get("id"),
                                "type": "function",
                                "function": {
                                    "name": p.function_call.get("name"),
                                    "arguments": json.dumps(p.function_call.get("args", {})),
                                },
                            }
                        )
            msg = {"role": role, "content": content}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            msgs.append(msg)

        new_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                new_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                new_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{d.content_type};base64,{d.content}"},
                    }
                )
            elif d.content_type == "application/pdf":
                new_content.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": d.metadata.get("filename", "doc.pdf"),
                            "file_data": f"data:{d.content_type};base64,{d.content}",
                        },
                    }
                )
        if new_content:
            msgs.append({"role": "user", "content": new_content})
        return msgs

    def _build_responses_items(self, data: list[DataSource]) -> list[dict[str, Any]]:
        # Pre-scan: collect call_ids that have a matching function_call_output
        # in the very next TOOL message.  Any call_id NOT in this set will be
        # skipped when building the payload so orphaned function_call items
        # (e.g. tool calls whose result was never recorded because the user
        # switched provider mid-ReAct loop) don't cause a 422 from the API.
        resolved_call_ids: set[str] = set()
        for idx, m in enumerate(self.conversation):
            if m.role != Role.MODEL:
                continue
            next_m = self.conversation[idx + 1] if idx + 1 < len(self.conversation) else None
            if next_m and next_m.role == Role.TOOL:
                for p in next_m.parts:
                    if not isinstance(p, ContentPart):
                        continue
                    fr = p.function_response
                    if fr is None:
                        continue
                    uid = fr.get("call_id") or fr.get("id")
                    if uid:
                        resolved_call_ids.add(uid)

        items: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            items.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": self.system_prompt}],
                }
            )
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in [
                    pt for pt in m.parts if isinstance(pt, ContentPart) and pt.function_response
                ]:
                    fr = p.function_response
                    if fr:
                        items.append(
                            {
                                "type": "function_call_output",
                                "call_id": fr.get("call_id") or fr.get("id"),
                                "output": str(fr.get("response", {}).get("result", "")),
                            }
                        )
                continue
            role = "assistant" if m.role == Role.MODEL else m.role.value
            parts: list[dict[str, Any]] = []
            for part in m.parts:
                if isinstance(part, str):
                    parts.append(
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": part,
                        }
                    )
                elif isinstance(part, ContentPart):
                    if part.text:
                        parts.append(
                            {
                                "type": "input_text" if role == "user" else "output_text",
                                "text": part.text,
                            }
                        )
                    if part.thought:
                        parts.append({"type": "thought", "text": part.thought})
                    if part.function_call and role == "assistant":
                        fc = part.function_call
                        call_id = fc.get("call_id") or fc.get("id")
                        # Skip orphaned function_calls (no matching output)
                        if call_id and call_id not in resolved_call_ids:
                            continue
                        if parts:
                            self._merge(items, role, parts)
                            parts = []
                        items.append(
                            {
                                "type": "function_call",
                                "id": fc.get("id"),
                                "call_id": fc.get("call_id"),
                                "name": fc.get("name"),
                                "arguments": json.dumps(fc.get("args", {})),
                                "status": "completed",
                            }
                        )
            if parts:
                self._merge(items, role, parts)
        new_p: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                new_p.append({"type": "input_text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                new_p.append({"type": "input_image", "input_image": {"data": d.content}})
            elif d.content_type == "application/pdf":
                new_p.append(
                    {
                        "type": "input_file",
                        "input_file": {
                            "filename": d.metadata.get("filename", "doc.pdf"),
                            "file_data": f"data:{d.content_type};base64,{d.content}",
                        },
                    }
                )
        if new_p:
            self._merge(items, "user", new_p)
        return items

    def _merge(self, items: list[dict[str, Any]], role: str, content: list[dict[str, Any]]) -> None:
        if items and items[-1].get("role") == role:
            items[-1]["content"].extend(content)
        else:
            items.append({"role": role, "content": content})

    def utility_send(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        # Check if the provider uses Responses API (OpenAI)
        # We assume subclasses set api_url or similar if needed.
        # Here we use a generic POST if we can find the URL.
        url = getattr(self, "api_url", "")
        # Adjust URL for utility completion if it's Responses API
        if "responses" in url:
            url = url.replace("/responses", "/chat/completions")

        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "local_bypass":
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            # Special case for Ollama
            if "ollama" in self.config_section.lower():
                payload["format"] = "json"
            else:
                payload["response_format"] = {"type": "json_object"}

        response = self._post(url, headers=headers, json_data=payload)
        response.raise_for_status()
        res_json = response.json()
        (text, _), _ = self._parse_openai_response(res_json)
        return text
