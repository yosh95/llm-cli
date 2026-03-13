# llm_cli/clients/gemini.py

import mimetypes
from pathlib import Path
from typing import Any

from llm_cli.clients.base import BaseLlmClient
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
            api_key_name="api_key",
            config_section="google",
            pdf_as_base64=True,
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

    def _is_video_model(self) -> bool:
        """Determines if the current model is a video generation model."""
        # Check specifically for Veo models
        return "veo" in self.model.lower() and "generate" in self.model.lower()

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        return "image" in self.model.lower() or "imagen" in self.model.lower()

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the request to Gemini using the Interactions API."""
        if not self.conversation:
            self.last_interaction_id = None

        if self._is_video_model():
            return self._send_video_generation(data)

        # Prepare input payload for Interactions API
        interaction_input: list[dict[str, Any]] = []

        # 1. Check for pending tool results in conversation history
        # (These are added by ChatSession but not passed in 'data')
        if self.conversation and self.conversation[-1].role == Role.TOOL:
            for part in self.conversation[-1].parts:
                if isinstance(part, ContentPart) and part.function_response:
                    fr = part.function_response
                    # Convert to Interactions API function_result format
                    interaction_input.append(
                        {
                            "type": "function_result",
                            "name": fr.get("name"),
                            "call_id": fr.get("id"),
                            "result": fr.get("response", {}).get("result"),
                        }
                    )

        # 2. Process new user data
        for item in data:
            file_uri = item.metadata.get("file_uri")
            if file_uri:
                # Interactions API uses 'uri' field and specific type based on mime
                input_type = "image"  # default
                if item.content_type.startswith("audio/"):
                    input_type = "audio"
                elif item.content_type.startswith("video/"):
                    input_type = "video"
                elif item.content_type == "application/pdf":
                    input_type = "document"

                interaction_input.append(
                    {
                        "type": input_type,
                        "uri": file_uri,
                        "mime_type": item.content_type,
                    }
                )
            elif any(
                item.content_type.startswith(t)
                for t in ["image/", "audio/", "video/", "application/pdf"]
            ):
                # Inline base64 data
                input_type = "image"
                if item.content_type.startswith("audio/"):
                    input_type = "audio"
                elif item.content_type.startswith("video/"):
                    input_type = "video"
                elif item.content_type == "application/pdf":
                    input_type = "document"

                interaction_input.append(
                    {
                        "type": input_type,
                        "data": item.content,  # Assuming base64 string
                        "mime_type": item.content_type,
                    }
                )
            else:
                # Text content
                interaction_input.append({"type": "text", "text": str(item.content)})

        is_tts_model = "tts" in self.model.lower()
        is_image_model = self._is_image_model()

        # Construct request payload
        payload: dict[str, Any] = {
            "model": self.model,
            "input": interaction_input,
        }

        # Add system instruction if enabled
        if self.system_prompt and self.system_prompt_enabled and not is_tts_model:
            payload["system_instruction"] = self.system_prompt

        # For image models, consolidate all text input into a single prompt
        # while preserving other media types (e.g. for image-to-image or context)
        if is_image_model:
            new_interaction_input = []
            text_parts = []
            for inp in interaction_input:
                if inp.get("type") == "text":
                    text_parts.append(inp.get("text", ""))
                else:
                    new_interaction_input.append(inp)

            if text_parts:
                new_interaction_input.insert(
                    0, {"type": "text", "text": " ".join(text_parts).strip()}
                )
            interaction_input = new_interaction_input
            payload["input"] = interaction_input

        if self.last_interaction_id and not is_tts_model:
            payload["previous_interaction_id"] = self.last_interaction_id
        elif not is_image_model or len(interaction_input) > 1:
            # No interaction ID (First turn). Inject context.
            # We also inject context if it's an image model but we have
            # multiple inputs (e.g. image + text), as it's likely a vision-related task.
            context_text_parts = []

            if self.conversation:
                for msg in self.conversation:
                    role_str = msg.role.upper()
                    msg_text = ""
                    for p in msg.parts:
                        if isinstance(p, ContentPart):
                            if p.text:
                                msg_text += p.text
                            elif p.function_call:
                                name = p.function_call.get("name")
                                msg_text += f"\n[Function Call: {name}]"
                            elif p.function_response:
                                name = p.function_response.get("name")
                                msg_text += f"\n[Function Result: {name}]"
                        elif isinstance(p, str):
                            msg_text += p

                    if msg_text:
                        context_text_parts.append(f"[{role_str}]: {msg_text}")

            if context_text_parts:
                full_context = "\n\n".join(context_text_parts)
                payload["input"].insert(0, {"type": "text", "text": full_context})

        # Multimodal Output Configuration
        if is_tts_model or is_image_model:
            if is_tts_model:
                payload["response_modalities"] = ["AUDIO"]
                if "generation_config" not in payload:
                    payload["generation_config"] = {}
            elif is_image_model:
                payload["response_modalities"] = ["IMAGE"]
                if "generation_config" in payload:
                    del payload["generation_config"]

        # Tools - Send every time as Interactions API does not persist them
        if self.active_tools and self.tools_enabled and not is_tts_model:
            tools_payload = registry.get_gemini_interactions_spec(
                self.active_tools, provider=self.config_section
            )
            if tools_payload:
                payload["tools"] = tools_payload

        try:
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
            res_json = response.json()

            # Store Interaction ID
            self.last_interaction_id = res_json.get("id")

            # Parse Response
            model_msg = self._parse_interaction_response(res_json)

            # Update history locally (for UI and saving)
            # 1. Add User message (if we sent new data)
            if data:
                # Reconstruct user message parts for history
                history_user_parts: list[str | ContentPart] = []
                for item in data:
                    file_uri = item.metadata.get("file_uri")
                    if file_uri:
                        history_user_parts.append(
                            ContentPart(text=f"[File: {file_uri}]")
                        )
                    elif any(
                        item.content_type.startswith(t)
                        for t in ["image/", "audio/", "video/", "application/pdf"]
                    ):
                        # For inline data, we store slightly different structure
                        # in history to reuse existing rendering logic
                        history_user_parts.append(
                            ContentPart(
                                inline_data={
                                    "mimeType": item.content_type,
                                    "data": item.content,
                                }
                            )
                        )
                    else:
                        history_user_parts.append(ContentPart(text=str(item.content)))

                self.conversation.append(
                    Message(role=Role.USER, parts=history_user_parts)
                )

            # 2. Add Model message
            self.conversation.append(model_msg)
            # Usage metadata is not always returned in Interactions API same way?
            # Assuming it might be there or we skip it.
            # Docs didn't explicitly show usage metadata in response examples.
            self.last_usage = res_json.get("usageMetadata") or res_json.get("usage")

            # Extract display text and thoughts (Copying logic from original _send)
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
            self._report_error("Gemini Interactions", e)
            return (None, None), None

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

            elif type_ in ("image", "audio", "video"):
                # API: {"type": "image", "data": "BASE64...", "mime_type": "..."}
                mime_type = output.get("mime_type")
                if not mime_type:
                    # Fallback for models that don't return mime_type (e.g. Gemini TTS)
                    if type_ == "audio":
                        mime_type = "audio/L16;rate=24000"
                    elif type_ == "image":
                        mime_type = "image/png"
                    elif type_ == "video":
                        mime_type = "video/mp4"

                inline = {
                    "mimeType": mime_type,
                    "data": output.get("data"),
                }
                model_parts.append(ContentPart(inline_data=inline))

        return Message(role=Role.MODEL, parts=model_parts)

    def _send_video_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Handles video generation via Gemini/Veo API."""
        from llm_cli.clients.gemini_handlers import send_video_generation

        return send_video_generation(self, data)

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
