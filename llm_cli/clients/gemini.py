# llm_cli/clients/gemini.py

import mimetypes
from pathlib import Path
from typing import Any, cast

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


class GeminiClient(BaseLlmClient):
    """
    Client for interacting with Google's Gemini API.

    Supports multimodal inputs (images, video, audio, PDF) using both
    inline base64 and the Gemini File API for larger files.
    """

    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta"
    INTERACTIONS_API_URL = (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    UPLOAD_API_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    # Increase upload timeout to 1 hour to support large files
    UPLOAD_TIMEOUT = 3600
    UPLOAD_START_TIMEOUT = 20
    # PDF size threshold for using File API instead of inline base64
    PDF_FILE_API_THRESHOLD = 10 * 1024 * 1024  # 10MB

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Gemini client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="google",
                pdf_as_base64=True,
            ),
            **kwargs,
        )
        self.last_interaction_id: str | None = None

    def _handle_command(
        self,
        user_input: str,
        sources: list[str] | None,
        pending_data: list[DataSource] | None = None,
    ) -> bool:
        """Handles Gemini-specific slash commands."""
        if super()._handle_command(user_input, sources, pending_data):
            return True

        return False

    def clear_history(self) -> None:
        """Clears history and resets Gemini interaction ID."""
        super().clear_history()
        self.last_interaction_id = None

    def get_conversation_state(self) -> dict[str, Any]:
        """Returns the conversation state including Gemini's interaction ID."""
        state = super().get_conversation_state()
        state["last_interaction_id"] = self.last_interaction_id
        return state

    def set_conversation_state(self, state: dict[str, Any]) -> None:
        """Restores the conversation state including Gemini's interaction ID."""
        super().set_conversation_state(state)
        self.last_interaction_id = state.get("last_interaction_id")

    def set_model(self, alias: str) -> bool:
        """Resets interaction ID when model changes."""
        old_model = self.model
        if super().set_model(alias):
            if self.model != old_model:
                self.last_interaction_id = None
            return True
        return False

    def set_custom_model(self, model_name: str) -> None:
        """Resets interaction ID when model changes."""
        if model_name != self.model:
            self.last_interaction_id = None
        super().set_custom_model(model_name)

    def _process_single_source(self, source: str) -> DataSource | None:
        """Override to handle Gemini-specific File API uploads for media."""
        # 1. Handle Gemini File API URIs directly
        if source.startswith("https://generativelanguage.googleapis.com/"):
            return DataSource(
                content=None,
                content_type="image/jpeg",  # Default
                is_file_or_url=True,
                metadata={"file_uri": source},
            )

        # 2. Handle local files that need uploading
        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            import filetype

            kind = filetype.guess(str(path))
            mime = kind.mime if kind else mimetypes.guess_type(path)[0] or ""
            file_size = path.stat().st_size

            # Determine if we should use the File API
            # Videos and Audios ALWAYS use File API in this client
            use_file_api = (
                mime.startswith("audio/")
                or mime.startswith("video/")
                or (
                    mime == "application/pdf"
                    and file_size > self.PDF_FILE_API_THRESHOLD
                )
            )

            if use_file_api:
                upload_res = self._upload_file(path, mime_type=mime)
                if upload_res:
                    uri, mime_type = upload_res
                    return DataSource(
                        content=None,
                        content_type=mime_type,
                        is_file_or_url=True,
                        metadata={"file_uri": uri},
                    )
                else:
                    return None

        return super()._process_single_source(source)

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        return "image" in self.model.lower() or "imagen" in self.model.lower()

    @staticmethod
    def _mime_to_interaction_type(mime: str) -> str:
        """Converts MIME type to Gemini Interactions API input type."""
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
        if mime == "application/pdf":
            return "document"
        return "image"

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the request to Gemini using the Interactions API."""
        if not self.conversation:
            self.last_interaction_id = None

        interaction_input = self._prepare_interaction_input(data)
        is_image_model = self._is_image_model()
        payload = self._build_request_payload(interaction_input, is_image_model)

        try:
            res_json = self._call_interactions_api(payload)
            self.last_interaction_id = res_json.get("id")
            model_msg = self._parse_interaction_response(res_json)
            self._update_local_state(data, model_msg, res_json)

            display_text = ""
            thought_text = ""
            last_saved_image_path = None

            for part in model_msg.parts:
                if isinstance(part, ContentPart):
                    if part.text:
                        display_text += part.text
                    if part.thought:
                        thought_text += part.thought

                    # Handle inline data (e.g. generated images)
                    if part.inline_data:
                        hint = ""
                        # Use last user text as hint
                        for m in reversed(self.conversation):
                            if m.role == Role.USER:
                                for up in m.parts:
                                    if isinstance(up, ContentPart) and up.text:
                                        hint = up.text[:100]
                                        break
                                if hint:
                                    break

                        log, saved_path = self._save_inline_media_and_get_log_entry(
                            part.inline_data, hint_text=hint
                        )
                        if log:
                            display_text += str(log)
                        if saved_path:
                            last_saved_image_path = saved_path

            # Fix image path in function calls if needed
            if last_saved_image_path:
                for part in model_msg.parts:
                    if isinstance(part, ContentPart) and part.function_call:
                        if part.function_call.get("name") == "read_image_file":
                            part.function_call["args"]["path"] = str(
                                last_saved_image_path
                            )

            return (display_text.strip(), thought_text.strip()), self.last_usage
        except Exception as e:
            self._report_error("Gemini", e)
            return (None, None), None

    def _prepare_interaction_input(
        self, data: list[DataSource]
    ) -> list[dict[str, Any]]:
        """Prepares input list for Interactions API."""
        interaction_input: list[dict[str, Any]] = []

        if self.conversation and self.conversation[-1].role == Role.TOOL:
            for part in self.conversation[-1].parts:
                if isinstance(part, ContentPart) and part.function_response:
                    fr = part.function_response
                    interaction_input.append(
                        {
                            "type": "function_result",
                            "name": fr.get("name"),
                            "call_id": fr.get("id"),
                            "result": fr.get("response", {}).get("result"),
                        }
                    )

        for item in data:
            file_uri = item.metadata.get("file_uri")
            if file_uri:
                interaction_input.append(
                    {
                        "type": self._mime_to_interaction_type(item.content_type),
                        "uri": file_uri,
                        "mime_type": item.content_type,
                    }
                )
            elif any(
                item.content_type.startswith(t)
                for t in ["image/", "audio/", "video/", "application/pdf"]
            ):
                interaction_input.append(
                    {
                        "type": self._mime_to_interaction_type(item.content_type),
                        "data": item.content,
                        "mime_type": item.content_type,
                    }
                )
            else:
                interaction_input.append({"type": "text", "text": str(item.content)})
        return interaction_input

    def _build_request_payload(
        self, interaction_input: list[dict[str, Any]], is_image_model: bool
    ) -> dict[str, Any]:
        """Constructs the full request payload."""
        if is_image_model:
            text_parts = [
                inp.get("text", "")
                for inp in interaction_input
                if inp.get("type") == "text"
            ]
            other_parts = [
                inp for inp in interaction_input if inp.get("type") != "text"
            ]
            if text_parts:
                interaction_input = [
                    {"type": "text", "text": " ".join(text_parts).strip()}
                ] + other_parts

        payload: dict[str, Any] = {"model": self.model, "input": interaction_input}
        if self.system_prompt and self.system_prompt_enabled:
            payload["system_instruction"] = self.system_prompt

        if self.last_interaction_id:
            payload["previous_interaction_id"] = self.last_interaction_id
        elif not is_image_model or len(interaction_input) > 1:
            context = self._build_context_text()
            if context:
                payload["input"].insert(0, {"type": "text", "text": context})

        if is_image_model:
            payload["response_modalities"] = ["IMAGE"]
            payload.pop("generation_config", None)

        if self.active_tools and self.tools_enabled:
            spec = registry.get_gemini_interactions_spec(
                self.active_tools, provider=self.config_section
            )
            if spec:
                payload["tools"] = spec
        return payload

    def _build_context_text(self) -> str | None:
        """Builds context string from history."""
        parts = []
        for msg in self.conversation:
            role = msg.role.upper()
            txt = "".join(
                p.text
                if isinstance(p, ContentPart) and p.text
                else (p if isinstance(p, str) else "")
                for p in msg.parts
            )
            if txt:
                parts.append(f"[{role}]: {txt}")
        return "\n\n".join(parts) if parts else None

    def _call_interactions_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls the Interactions API."""
        response = self._post(
            self.INTERACTIONS_API_URL,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json_data=payload,
            timeout=self.request_timeout,
        )
        self._log_debug(response_obj=response, request_payload=payload)
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    def _update_local_state(
        self, data: list[DataSource], model_msg: Message, res_json: dict[str, Any]
    ) -> None:
        """Updates internal conversation history and usage."""
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

    def _parse_interaction_response(self, response_json: dict[str, Any]) -> Message:
        """Parses Gemini Interactions API response into internal Message format."""
        outputs = response_json.get("outputs", [])
        if not outputs:
            return Message(
                role=Role.MODEL, parts=[ContentPart(text="[No output from model]")]
            )

        model_parts: list[str | ContentPart] = []
        for output in outputs:
            type_ = output.get("type")

            # Thought handling (Not strictly defined in API docs yet)
            # Or maybe it comes as text?
            # API docs show 'text', 'function_call', 'image', 'audio'.
            # Thinking/Reasoning might be just text with a specific flag?
            # For now, treat text as text.

            if type_ == "text":
                text = output.get("text", "")
                model_parts.append(ContentPart(text=text))

            elif type_ == "function_call":
                # API: {"type": "function_call", "name": "...", "id": ...}
                fc = {
                    "name": output.get("name"),
                    "args": output.get("arguments"),
                    "id": output.get("id"),  # Interactions API returns 'id' for call_id
                }
                model_parts.append(ContentPart(function_call=fc))

            elif type_ == "image":
                # API: {"type": "image", "data": "BASE64...", "mime_type": "..."}
                mime_type = output.get("mime_type") or "image/png"
                inline = {
                    "mimeType": mime_type,
                    "data": output.get("data"),
                }
                model_parts.append(ContentPart(inline_data=inline))

        return Message(role=Role.MODEL, parts=model_parts)

    def _upload_file(
        self, path: Path, mime_type: str | None = None
    ) -> tuple[str, str] | None:
        """Handles resumable upload to Gemini File API."""
        from llm_cli.clients.gemini_handlers import upload_file

        return upload_file(self, path, mime_type)

    def _wait_for_file_active(self, file_name: str) -> bool:
        """Polls the file status until it is ACTIVE."""
        from llm_cli.clients.gemini_handlers import wait_for_file_active

        return wait_for_file_active(self, file_name)

    def _print_help(self) -> None:
        super()._print_help()
