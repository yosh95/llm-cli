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

    Uses the standard generateContent API with full conversation history
    sent on every request (stateless — no server-side session IDs).
    """

    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta"
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

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the request to Gemini using the generateContent API."""
        is_image_model = self._is_image_model()
        contents = self._build_contents(data)
        payload = self._build_request_payload(contents, is_image_model)

        try:
            res_json = self._call_generate_content_api(payload)
            model_msg = self._parse_generate_content_response(res_json)
            self._update_local_state(data, model_msg, res_json)

            display_text = model_msg.get_text()
            thought_text = ""
            last_saved_image_path = None

            for part in model_msg.parts:
                if isinstance(part, ContentPart):
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

    def _build_contents(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """
        Builds the ``contents`` array for the generateContent API.

        The full conversation history (self.conversation) is serialised on
        every request so no server-side session state is required.
        """
        contents: list[dict[str, Any]] = []

        # Pre-calculate tool IDs with responses to ensure tool-calling validity
        responded_tool_ids = set()
        for msg in self.conversation:
            if msg.role == Role.TOOL:
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        tid = part.function_response.get("id")
                        if tid:
                            responded_tool_ids.add(tid)

        for msg in self.conversation:
            if msg.role == Role.TOOL:
                # Tool results → role "user" with function_response parts
                tool_parts: list[dict[str, Any]] = []
                for p in msg.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        fr = p.function_response
                        tool_id = fr.get("id")
                        if tool_id and tool_id in responded_tool_ids:
                            result = fr.get("response", {}).get("result", "")
                            tool_parts.append(
                                {
                                    "functionResponse": {
                                        "id": tool_id,
                                        "name": fr.get("name"),
                                        "response": {"result": str(result)},
                                    }
                                }
                            )
                if tool_parts:
                    contents.append({"role": "user", "parts": tool_parts})
            else:
                role = "model" if msg.role == Role.MODEL else "user"
                msg_parts: list[dict[str, Any]] = []
                for p in msg.parts:
                    if isinstance(p, str):
                        msg_parts.append({"text": p})
                    elif isinstance(p, ContentPart):
                        if p.thought:
                            # thoughtSignature is a part-level sibling field
                            thought_part: dict[str, Any] = {
                                "thought": True,
                                "text": p.thought,
                            }
                            if p.thought_signature:
                                thought_part["thoughtSignature"] = p.thought_signature
                            msg_parts.append(thought_part)
                        if p.text and p.text.strip():
                            text_part: dict[str, Any] = {"text": p.text}
                            if p.thought_signature and not p.thought:
                                # Signature on a plain-text part (non-FC response)
                                text_part["thoughtSignature"] = p.thought_signature
                            msg_parts.append(text_part)
                        if p.inline_data:
                            inline_part: dict[str, Any] = {
                                "inlineData": {
                                    "mimeType": p.inline_data.get("mimeType", ""),
                                    "data": p.inline_data.get("data", ""),
                                }
                            }
                            if p.thought_signature:
                                inline_part["thoughtSignature"] = p.thought_signature
                            msg_parts.append(inline_part)
                        if p.function_call:
                            fc = p.function_call
                            tool_id = fc.get("id")
                            if tool_id and tool_id in responded_tool_ids:
                                # thoughtSignature is a part-level sibling of
                                # functionCall — must be echoed back exactly as
                                # received to satisfy Gemini 3 validation.
                                fc_part: dict[str, Any] = {
                                    "functionCall": {
                                        "id": tool_id,
                                        "name": fc.get("name", "unknown"),
                                        "args": fc.get("args", {}),
                                    }
                                }
                                if p.thought_signature:
                                    fc_part["thoughtSignature"] = p.thought_signature
                                msg_parts.append(fc_part)
                if msg_parts:
                    contents.append({"role": role, "parts": msg_parts})

        # Append the incoming user turn
        user_parts: list[dict[str, Any]] = []
        for item in data:
            file_uri = item.metadata.get("file_uri")
            if file_uri:
                user_parts.append(
                    {
                        "fileData": {
                            "mimeType": item.content_type,
                            "fileUri": file_uri,
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
        """Constructs the full request payload for generateContent."""
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
                # Support context circulation for built-in and custom tool combinations
                payload["tool_config"] = {"include_server_side_tool_invocations": True}

        return payload

    def _call_generate_content_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls the generateContent API."""
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

    def _parse_generate_content_response(
        self, response_json: dict[str, Any]
    ) -> Message:
        """Parses generateContent API response into internal Message format.

        ``thoughtSignature`` is a part-level field (sibling of ``functionCall``
        / ``text`` inside each element of the ``parts`` array).  It must be
        preserved verbatim and echoed back in the next request so that Gemini 3
        thinking models can validate the function-calling chain.
        """
        candidates = response_json.get("candidates", [])
        if not candidates:
            return Message(
                role=Role.MODEL, parts=[ContentPart(text="[No output from model]")]
            )

        candidate = candidates[0]
        content = candidate.get("content", {})
        raw_parts = content.get("parts", [])
        grounding_metadata = candidate.get("groundingMetadata")

        model_parts: list[str | ContentPart] = []
        for part in raw_parts:
            # thoughtSignature is a sibling field at the part level.
            # Capture it once and attach it to whichever ContentPart we build.
            thought_sig: str | None = part.get("thoughtSignature")

            # Thinking / reasoning blocks  (part["thought"] == True)
            if part.get("thought"):
                model_parts.append(
                    ContentPart(
                        thought=part.get("text", ""),
                        thought_signature=thought_sig,
                    )
                )

            # Plain text
            elif "text" in part:
                text = part["text"]
                # Apply grounding citations if available
                if grounding_metadata:
                    text = self._apply_grounding(text, grounding_metadata)
                model_parts.append(
                    ContentPart(text=text, thought_signature=thought_sig)
                )

            # Function / tool call
            elif "functionCall" in part:
                fc = part["functionCall"]
                model_parts.append(
                    ContentPart(
                        function_call={
                            "id": fc.get("id", fc.get("name")),
                            "name": fc.get("name"),
                            "args": fc.get("args", {}),
                        },
                        thought_signature=thought_sig,
                    )
                )

            # Built-in Tool Call (e.g. Google Search)
            elif "toolCall" in part:
                tc = part["toolCall"]
                model_parts.append(
                    ContentPart(
                        text=f"[Built-in Tool Call: {tc.get('toolType', 'unknown')}]",
                        thought_signature=thought_sig,
                        is_diagnostic=True,
                    )
                )

            # Built-in Tool Response (e.g. Google Search results)
            elif "toolResponse" in part:
                tr = part["toolResponse"]
                model_parts.append(
                    ContentPart(
                        text=f"[Built-in Tool Response: "
                        f"{tr.get('toolType', 'unknown')}]",
                        thought_signature=thought_sig,
                        is_diagnostic=True,
                    )
                )

            # Inline media (e.g. generated images)
            elif "inlineData" in part:
                inline = part["inlineData"]
                model_parts.append(
                    ContentPart(
                        inline_data={
                            "mimeType": inline.get("mimeType", "image/png"),
                            "data": inline.get("data"),
                        },
                        thought_signature=thought_sig,
                    )
                )

        # Append source links as a legend at the end of the text parts
        if grounding_metadata and grounding_metadata.get("groundingChunks"):
            chunks = grounding_metadata.get("groundingChunks", [])
            sources_text = "\n\n---\n\n**Sources:**\n"
            from urllib.parse import urlparse

            for i, chunk in enumerate(chunks):
                web = chunk.get("web", {})
                uri = web.get("uri")
                if uri:
                    title = web.get("title", "")
                    # If title is empty, or just a generic placeholder, use domain
                    if not title or title.startswith("Source ") or title.isdigit():
                        domain = urlparse(uri).netloc
                        if domain:
                            title = domain.replace("www.", "")
                    if not title:
                        title = f"Source {i + 1}"
                    sources_text += f"{i + 1}. [{title}]({uri})\n"

            # Find the last text part and append the legend
            for p in reversed(model_parts):
                if isinstance(p, ContentPart) and p.text:
                    p.text += sources_text
                    break

        return Message(role=Role.MODEL, parts=model_parts)

    def _apply_grounding(self, text: str, metadata: dict[str, Any]) -> str:
        """Applies inline citations from groundingMetadata to the response text."""
        chunks = metadata.get("groundingChunks", [])
        supports = metadata.get("groundingSupports", [])
        if not chunks or not supports:
            return text

        # Dictionary to store unique indices for each insertion point
        insertions: dict[int, set[int]] = {}

        for s in supports:
            end_idx = s.get("segment", {}).get("endIndex")
            indices = s.get("groundingChunkIndices", [])
            if end_idx is not None and indices:
                if end_idx not in insertions:
                    insertions[end_idx] = set()
                for i in indices:
                    if 0 <= i < len(chunks):
                        insertions[end_idx].add(i + 1)

        # Sort insertion points in descending order
        sorted_indices = sorted(insertions.keys(), reverse=True)

        for end_idx in sorted_indices:
            unique_ids = sorted(insertions[end_idx])
            if unique_ids:
                # Format: [1, 2, 3]
                cit_str = " [" + ", ".join(map(str, unique_ids)) + "]"
                text = text[:end_idx] + cit_str + text[end_idx:]
        return text

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
