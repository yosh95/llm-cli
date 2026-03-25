# llm_cli/clients/gemini.py

import mimetypes
from pathlib import Path
from typing import Any, cast

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

from .gemini_parser import parse_generate_content_response


class GeminiClient(BaseLlmClient):
    """Client for interacting with Google's Gemini API."""

    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta"
    UPLOAD_API_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    UPLOAD_TIMEOUT = 3600
    UPLOAD_START_TIMEOUT = 20
    PDF_FILE_API_THRESHOLD = 10 * 1024 * 1024  # 10MB

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key", config_section="google", pdf_as_base64=True
            ),
            **kwargs,
        )

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        return super()._handle_command(user_input, sources, pending_data)

    def _process_single_source(self, source: str) -> DataSource | None:
        """Override to handle Gemini-specific File API uploads."""
        if source.startswith("https://generativelanguage.googleapis.com/"):
            return DataSource(
                content=None,
                content_type="image/jpeg",
                is_file_or_url=True,
                metadata={"file_uri": source},
            )

        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            import filetype

            kind = filetype.guess(str(path))
            mime = kind.mime if kind else mimetypes.guess_type(path)[0] or ""
            file_size = path.stat().st_size
            use_file_api = (
                mime.startswith("audio/")
                or mime.startswith("video/")
                or (
                    mime == "application/pdf"
                    and file_size > self.PDF_FILE_API_THRESHOLD
                )
            )

            if use_file_api:
                from .gemini_handlers import upload_file

                upload_res = upload_file(self, path, mime_type=mime)
                if upload_res:
                    uri, mime_type = upload_res
                    return DataSource(
                        content=None,
                        content_type=mime_type,
                        is_file_or_url=True,
                        metadata={"file_uri": uri},
                    )
        return super()._process_single_source(source)

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        contents = self._build_contents(data)
        payload = self._build_request_payload(contents, "image" in self.model.lower())

        try:
            res_json = self._call_generate_content_api(payload)
            model_msg = parse_generate_content_response(res_json)
            self._update_local_state(data, model_msg, res_json)

            display_text, thought_text = model_msg.get_text(), ""
            last_saved_image_path = None

            for part in model_msg.parts:
                if isinstance(part, ContentPart):
                    if part.thought:
                        thought_text += part.thought
                    if part.inline_data:
                        hint = next(
                            (
                                up.text[:100]
                                for m in reversed(self.conversation)
                                if m.role == Role.USER
                                for up in m.parts
                                if isinstance(up, ContentPart) and up.text
                            ),
                            "",
                        )
                        log, saved_path = self._save_inline_media_and_get_log_entry(
                            part.inline_data, hint_text=hint
                        )
                        if log:
                            display_text += str(log)
                        if saved_path:
                            last_saved_image_path = saved_path

            if last_saved_image_path:
                for part in model_msg.parts:
                    if (
                        isinstance(part, ContentPart)
                        and part.function_call
                        and part.function_call.get("name") == "read_image_file"
                    ):
                        part.function_call["args"]["path"] = str(last_saved_image_path)

            return (display_text.strip(), thought_text.strip()), self.last_usage
        except Exception as e:
            self._report_error("Gemini", e)
            return (None, None), None

    def _build_contents(self, data: list[DataSource]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        responded_tool_ids = {
            p.function_response.get("id")
            for msg in self.conversation
            if msg.role == Role.TOOL
            for p in msg.parts
            if isinstance(p, ContentPart) and p.function_response
        }

        for msg in self.conversation:
            if msg.role == Role.TOOL:
                tool_parts = [
                    {
                        "functionResponse": {
                            "id": p.function_response.get("id"),
                            "name": p.function_response.get("name"),
                            "response": {
                                "result": str(
                                    p.function_response.get("response", {}).get(
                                        "result", ""
                                    )
                                )
                            },
                        }
                    }
                    for p in msg.parts
                    if isinstance(p, ContentPart)
                    and p.function_response
                    and p.function_response.get("id") in responded_tool_ids
                ]
                if tool_parts:
                    contents.append({"role": "user", "parts": tool_parts})
            else:
                msg_parts: list[dict[str, Any]] = []
                for p in msg.parts:
                    if isinstance(p, str):
                        msg_parts.append({"text": p})
                    elif isinstance(p, ContentPart):
                        thought_sig = p.thought_signature
                        if p.thought:
                            part_dict = {"thought": True, "text": p.thought}
                            if thought_sig:
                                part_dict["thoughtSignature"] = thought_sig
                            msg_parts.append(part_dict)
                        if p.text and p.text.strip():
                            part_dict = {"text": p.text}
                            if thought_sig and not p.thought:
                                part_dict["thoughtSignature"] = thought_sig
                            msg_parts.append(part_dict)
                        if p.inline_data:
                            part_dict = {
                                "inlineData": {
                                    "mimeType": p.inline_data.get("mimeType", ""),
                                    "data": p.inline_data.get("data", ""),
                                }
                            }
                            if thought_sig:
                                part_dict["thoughtSignature"] = thought_sig
                            msg_parts.append(part_dict)
                        if (
                            p.function_call
                            and p.function_call.get("id") in responded_tool_ids
                        ):
                            part_dict = {
                                "functionCall": {
                                    "id": p.function_call["id"],
                                    "name": p.function_call.get("name", "unknown"),
                                    "args": p.function_call.get("args", {}),
                                }
                            }
                            if thought_sig:
                                part_dict["thoughtSignature"] = thought_sig
                            msg_parts.append(part_dict)
                if msg_parts:
                    contents.append(
                        {
                            "role": "model" if msg.role == Role.MODEL else "user",
                            "parts": msg_parts,
                        }
                    )

        user_parts: list[dict[str, Any]] = []
        for item in data:
            if item.metadata.get("file_uri"):
                user_parts.append(
                    {
                        "fileData": {
                            "mimeType": item.content_type,
                            "fileUri": item.metadata["file_uri"],
                        }
                    }
                )
            elif any(
                item.content_type.startswith(t)
                for t in ["image/", "audio/", "video/", "application/pdf"]
            ):
                user_parts.append(
                    {
                        "inlineData": {
                            "mimeType": item.content_type,
                            "data": item.content,
                        }
                    }
                )
            else:
                user_parts.append({"text": str(item.content)})

        if user_parts:
            contents.append({"role": "user", "parts": user_parts})
        return contents

    def _build_request_payload(
        self, contents: list[dict[str, Any]], is_image_model: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"contents": contents}
        if self.system_prompt and self.system_prompt_enabled:
            payload["system_instruction"] = {"parts": [{"text": self.system_prompt}]}
        if is_image_model:
            payload["generation_config"] = {"response_modalities": ["IMAGE", "TEXT"]}
        if self.active_tools and self.tools_enabled:
            spec = registry.get_gemini_spec(
                self.active_tools, provider=self.config_section
            )
            if spec:
                payload["tools"] = spec
                payload["tool_config"] = {"include_server_side_tool_invocations": True}
        return payload

    def _call_generate_content_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.BASE_API_URL}/models/{self.model}:generateContent"
        response = self._post(
            url,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json_data=payload,
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    def _update_local_state(
        self, data: list[DataSource], model_msg: Message, res_json: dict[str, Any]
    ) -> None:
        if data:
            parts: list[str | ContentPart] = []
            for item in data:
                if item.metadata.get("file_uri"):
                    parts.append(
                        ContentPart(text=f"[File: {item.metadata['file_uri']}]")
                    )
                elif any(
                    item.content_type.startswith(t)
                    for t in ["image/", "audio/", "video/", "application/pdf"]
                ):
                    parts.append(
                        ContentPart(
                            inline_data={
                                "mimeType": item.content_type,
                                "data": item.content,
                            }
                        )
                    )
                else:
                    parts.append(ContentPart(text=str(item.content)))
            self.conversation.append(Message(role=Role.USER, parts=parts))
        self.conversation.append(model_msg)
        self.last_usage = res_json.get("usageMetadata") or res_json.get("usage")

    def utility_send(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        }
        if json_mode:
            payload["generationConfig"] = {"responseMimeType": "application/json"}

        res_json = self._call_generate_content_api(payload)
        model_msg = parse_generate_content_response(res_json)
        return model_msg.get_text().strip()
