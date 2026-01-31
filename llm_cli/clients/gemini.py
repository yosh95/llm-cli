# llm_cli/clients/gemini.py

import mimetypes
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


class GeminiClient(BaseLlmClient):
    """
    Client for interacting with Google's Gemini API.

    Supports multimodal inputs (images, video, audio, PDF) using both
    inline base64 and the Gemini File API for larger files.
    """

    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta"
    UPLOAD_API_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    # Increase upload timeout to 1 hour to support large files
    UPLOAD_TIMEOUT = 3600
    UPLOAD_START_TIMEOUT = 20
    # PDF size threshold for using File API instead of inline base64
    PDF_FILE_API_THRESHOLD = 10 * 1024 * 1024  # 10MB

    def __init__(self, initial_model_alias: str = "default", **kwargs):
        """Initializes the Gemini client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="google",
            pdf_as_base64=True,
            **kwargs,
        )
        self._slash_commands.update({"speech", "tts"})

    def _handle_command(
        self,
        user_input: str,
        sources: Optional[List[str]],
        pending_data: Optional[List[DataSource]] = None,
    ) -> bool:
        """Handles Gemini-specific slash commands."""
        if super()._handle_command(user_input, sources, pending_data):
            return True

        if not user_input.startswith("/"):
            return False

        parts = user_input[1:].split(None, 1)
        cmd = parts[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("speech", "tts"):
            if not args:
                console.print("[red]Usage: /speech <text to generate audio for>[/red]")
                return True

            # Use the current model to generate speech content
            self.generate_speech_content(args)
            return True

        return False

    def generate_speech_content(self, text: str):
        """
        Generates audio from text using the current model with
        responseModalities=['AUDIO'].
        """
        console.print(f"[dim]Generating speech using {self.model}...[/dim]")

        # Construct a one-off payload
        # Note: TTS models strictly require AUDIO modality.
        # Including system prompts can confuse the model into text mode.
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}
                },
            },
        }

        # Explicitly do NOT add system instructions for TTS generation

        api_url = f"{self.BASE_API_URL}/models/{self.model}:generateContent"

        try:
            response = self._post_with_retry(
                api_url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json_data=payload,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            res_json = response.json()

            model_msg = self._parse_response(res_json)

            # Process and save any inline data (which should be the audio)
            saved_something = False
            for p in model_msg.parts:
                if isinstance(p, ContentPart) and p.inline_data:
                    # Provide a hint text for the filename
                    hint = text[:50]
                    log, saved_path = self._save_inline_media_and_get_log_entry(
                        p.inline_data, hint_text=hint
                    )
                    if log:
                        console.print(log)
                    saved_something = True

            if not saved_something:
                console.print(
                    "[yellow]No audio data received from the model. "
                    "Ensure the model supports audio generation.[/yellow]"
                )

        except Exception as e:
            self._report_error("Speech Generation", e)

    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("google")
        if not self.available_models:
            console.print(
                f"[yellow]Warning: No models configured for "
                f"'{self.config_section}'.[/yellow]"
            )

    def _process_single_source(self, source: str) -> Optional[DataSource]:
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

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        """Sends the conversation history and new data to Gemini."""
        if self._is_video_model():
            return self._send_video_generation(data)

        new_parts = []
        for item in data:
            file_uri = item.metadata.get("file_uri")
            if file_uri:
                new_parts.append(
                    {
                        "file_data": {
                            "mime_type": item.content_type,
                            "file_uri": file_uri,
                        }
                    }
                )
            elif any(
                item.content_type.startswith(t)
                for t in ["image/", "audio/", "video/", "application/pdf"]
            ):
                new_parts.append(
                    {
                        "inlineData": {
                            "mimeType": item.content_type,
                            "data": item.content,
                        }
                    }
                )
            else:
                new_parts.append({"text": str(item.content)})

        payload = self._to_provider_request_format(new_parts)

        api_url = f"{self.BASE_API_URL}/models/{self.model}:generateContent"
        try:
            response = self._post_with_retry(
                api_url,
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

            model_msg = self._parse_response(res_json)

            # Update history
            if new_parts:
                history_user_parts = []
                for p in new_parts:
                    if "text" in p:
                        history_user_parts.append(ContentPart(text=p["text"]))
                    elif "inlineData" in p:
                        history_user_parts.append(
                            ContentPart(inline_data=p["inlineData"])
                        )
                    elif "file_data" in p:
                        # Placeholder text for file data in history
                        uri = p["file_data"]["file_uri"]
                        history_user_parts.append(ContentPart(text=f"[File: {uri}]"))
                self.conversation.append(
                    Message(role=Role.USER, parts=history_user_parts)
                )

            self.conversation.append(model_msg)
            self.last_usage = res_json.get("usageMetadata")

            # Extract display text and thoughts
            display_text = ""
            thought_text = ""
            last_saved_image_path = None

            for p in model_msg.parts:
                if isinstance(p, ContentPart):
                    if p.text:
                        display_text += p.text
                    if p.thought:
                        thought_text += p.thought
                    # Handle image generation / other inline data if supported
                    if p.inline_data:
                        # Extract inline_data from ContentPart
                        # Use last user text as hint for filename
                        hint = ""
                        for m in reversed(self.conversation):
                            if m.role == Role.USER:
                                for up in m.parts:
                                    if isinstance(up, ContentPart) and up.text:
                                        hint = up.text[:100]
                                        break
                                if hint:
                                    break

                        log, saved_path = self._save_inline_media_and_get_log_entry(
                            p.inline_data, hint_text=hint
                        )
                        if log:
                            display_text += log
                        if saved_path:
                            last_saved_image_path = saved_path

            # If an image was generated, check for attach_file calls and fix path
            # if needed
            if last_saved_image_path:
                for p in model_msg.parts:
                    if isinstance(p, ContentPart) and p.function_call:
                        if p.function_call.get("name") == "read_image_file":
                            # Fix the path to point to the actually saved file
                            # This corrects model hallucination where it invents a
                            # filename different from what we saved
                            p.function_call["args"]["path"] = str(last_saved_image_path)

            return (display_text.strip(), thought_text.strip()), self.last_usage
        except Exception as e:
            self._report_error("Gemini", e)
            return (None, None), None

    def _to_provider_request_format(self, new_parts: List[Dict]) -> Dict:
        """Converts history and new parts to Gemini API format."""
        contents = []
        for m in self.conversation:
            parts = []
            for p in m.parts:
                if isinstance(p, str):
                    parts.append({"text": p})
                elif isinstance(p, ContentPart):
                    part_dict = {}
                    if p.text:
                        part_dict["text"] = p.text
                    # Note: 'thought' is only in API responses, not requests.
                    # We only send 'thoughtSignature' back to maintain context.
                    if p.function_call:
                        part_dict["functionCall"] = {
                            "name": p.function_call.get("name"),
                            "args": p.function_call.get("args"),
                        }
                    if p.function_response:
                        part_dict["functionResponse"] = {
                            "name": p.function_response.get("name"),
                            "response": p.function_response.get("response"),
                        }

                    # Gemini API expects 'thoughtSignature' (camelCase)
                    if p.thought_signature:
                        part_dict["thoughtSignature"] = p.thought_signature

                    if part_dict:
                        parts.append(part_dict)

            if parts:
                contents.append(
                    {
                        "role": "model" if m.role == Role.MODEL else "user",
                        "parts": parts,
                    }
                )

        # Filter out function calls that don't have a corresponding response
        # Gemini API requires functionCall to be followed by functionResponse
        filtered_contents = []
        i = 0
        while i < len(contents):
            msg = contents[i]
            if msg["role"] == "model":
                # Check if this message has function calls
                has_func_call = any("functionCall" in p for p in msg["parts"])
                if has_func_call:
                    # Look ahead for function response
                    has_response = False
                    if i + 1 < len(contents):
                        next_msg = contents[i + 1]
                        if next_msg["role"] == "user" and any(
                            "functionResponse" in p for p in next_msg["parts"]
                        ):
                            has_response = True

                    if not has_response:
                        # Remove function calls from this message
                        new_parts_list = [
                            p for p in msg["parts"] if "functionCall" not in p
                        ]
                        if new_parts_list:
                            msg["parts"] = new_parts_list
                            filtered_contents.append(msg)
                        # If message becomes empty, don't append it
                    else:
                        filtered_contents.append(msg)
                else:
                    filtered_contents.append(msg)
            else:
                filtered_contents.append(msg)
            i += 1

        if new_parts:
            filtered_contents.append({"role": "user", "parts": new_parts})

        payload = {"contents": filtered_contents}

        # Check if current model is a TTS model
        # TTS models require AUDIO modality and often fail with system instructions
        is_tts_model = "tts" in self.model.lower()

        if self.system_prompt and self.system_prompt_enabled and not is_tts_model:
            payload["system_instruction"] = {"parts": [{"text": self.system_prompt}]}

        if self.active_tools and self.tools_enabled and not is_tts_model:
            payload["tools"] = registry.get_gemini_spec(
                self.active_tools, provider=self.config_section
            )

        if self.reasoning_enabled and not is_tts_model:
            thinking_config = {}
            if self.include_thoughts:
                thinking_config["include_thoughts"] = True

            if self.thinking_key and self.thinking_budget:
                key = self.thinking_key or "thinkingLevel"
                budget = self.thinking_budget or "medium"
                thinking_config[key] = budget

                payload["generationConfig"] = {"thinkingConfig": thinking_config}

        if is_tts_model:
            # Enforce AUDIO modality for TTS models
            gen_config = payload.get("generationConfig", {})
            gen_config["responseModalities"] = ["AUDIO"]

            # Add default speech config if not present
            if "speechConfig" not in gen_config:
                gen_config["speechConfig"] = {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}
                }
            payload["generationConfig"] = gen_config

        return payload

    def _parse_response(self, response_json: Dict) -> Message:
        """Parses Gemini response into internal Message format."""
        if not response_json.get("candidates"):
            return Message(
                role=Role.MODEL, parts=[ContentPart(text="[No response candidates]")]
            )

        candidate = response_json["candidates"][0]
        raw_parts = candidate.get("content", {}).get("parts", [])

        model_parts = []
        for p in raw_parts:
            # API returns 'thoughtSignature'
            sig = p.get("thoughtSignature")
            # Gemini's response format:
            # - Thinking part: {"thought": true, "text": "thinking content..."}
            # - Regular part: {"text": "response to user..."}
            is_thought_part = p.get("thought") is True
            if "text" in p:
                if is_thought_part:
                    # Store as thought content for separate display
                    model_parts.append(
                        ContentPart(thought=p["text"], thought_signature=sig)
                    )
                else:
                    model_parts.append(
                        ContentPart(text=p["text"], thought_signature=sig)
                    )
            if "inlineData" in p:
                model_parts.append(
                    ContentPart(inline_data=p["inlineData"], thought_signature=sig)
                )
            if "functionCall" in p:
                model_parts.append(
                    ContentPart(function_call=p["functionCall"], thought_signature=sig)
                )

        return Message(role=Role.MODEL, parts=model_parts)

    def _send_video_generation(
        self, data: List[DataSource]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Handles video generation via Gemini/Veo API."""
        prompt_parts = []
        # Gather text prompts
        for m in self.conversation:
            for p in m.parts:
                if isinstance(p, ContentPart) and p.text:
                    prompt_parts.append(p.text)
                elif isinstance(p, str):
                    prompt_parts.append(p)
        for d in data:
            if d.content_type == "text/plain":
                prompt_parts.append(str(d.content))

        full_prompt = "\n".join(prompt_parts)

        # Construct payload for Veo 3.1 (Vertex AI / AI Studio format)
        payload = {
            "instances": [{"prompt": full_prompt}],
            "parameters": {
                "sampleCount": 1,
            },
        }

        api_url = f"{self.BASE_API_URL}/models/{self.model}:predictLongRunning"

        try:
            # Step 1: Start generation
            console.print(f"[dim]Starting video generation with {self.model}...[/dim]")
            response = self._post_with_retry(
                api_url,
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

            # response should contain 'name' which is the operation ID
            operation_name = res_json.get("name")
            if not operation_name:
                return ("Failed to get operation name for video generation.", ""), None

            # Step 2: Poll for results
            video_uri = None
            start_time = time.time()
            timeout_seconds = 1800  # 30 minutes

            console.print(
                "[dim]Video generation started. Polling for results... "
                "(this may take a few minutes)[/dim]"
            )

            while time.time() - start_time < timeout_seconds:
                poll_url = f"{self.BASE_API_URL}/{operation_name}"

                poll_response = requests.get(
                    poll_url,
                    headers={"x-goog-api-key": self.api_key},
                    timeout=self.request_timeout,
                )

                if poll_response.status_code == 200:
                    op_res = poll_response.json()
                    if op_res.get("done"):
                        if "error" in op_res:
                            err_msg = op_res["error"].get("message", "Unknown error")
                            return (f"Video generation failed: {err_msg}", ""), None

                        # Extract video URI
                        response_body = op_res.get("response", {})

                        # Try known patterns
                        # Pattern 1: Vertex AI style (predictions array)
                        predictions = response_body.get("predictions", [])
                        if predictions:
                            vid = predictions[0].get("video", {})
                            video_uri = vid.get("uri") or vid.get("url")
                            if not video_uri:
                                video_uri = predictions[0].get("url")

                        # Pattern 2: Direct result
                        if not video_uri:
                            vid = response_body.get("result", {}).get("video", {})
                            video_uri = vid.get("uri") or vid.get("url")

                        # Pattern 3: generateVideoResponse (New Gemini/Veo style)
                        if not video_uri:
                            gen_resp = response_body.get("generateVideoResponse", {})
                            samples = gen_resp.get("generatedSamples", [])
                            if samples:
                                vid = samples[0].get("video", {})
                                video_uri = vid.get("uri") or vid.get("url")

                        if video_uri:
                            break
                        else:
                            # Dump response for debugging
                            import json

                            debug_dump = json.dumps(
                                op_res, indent=2, ensure_ascii=False
                            )
                            return (
                                "Generation completed but no video URI found in "
                                "response.\n"
                                f"Response dump:\n{debug_dump}",
                                "",
                            ), None

                    # Not done yet
                    time.sleep(5)
                else:
                    # Retry on transient errors?
                    time.sleep(5)

            if not video_uri:
                return ("Video generation timed out.", ""), None

            display_text = (
                f"Successfully generated video.\n\n**Video URL:** `{video_uri}`"
            )

            # Attempt to download and save locally
            video_data = None
            mime_type = None

            try:
                import base64

                console.print("[dim]Downloading video content...[/dim]")
                vid_response = requests.get(
                    video_uri,
                    headers={"x-goog-api-key": self.api_key},
                    timeout=self.request_timeout,
                )
                if vid_response.status_code == 200:
                    video_bytes = vid_response.content
                    mime_type = vid_response.headers.get("Content-Type", "video/mp4")
                    video_data = base64.b64encode(video_bytes).decode("utf-8")
                else:
                    console.print(
                        f"[yellow]Failed to download video "
                        f"(Status: {vid_response.status_code})[/yellow]"
                    )
            except Exception as e:
                console.print(f"[yellow]Failed to download video: {e}[/yellow]")

            if video_data and mime_type:
                # Save inline using shared logic
                hint = full_prompt[:100]
                log, saved_path = self._save_inline_media_and_get_log_entry(
                    {"mimeType": mime_type, "data": video_data}, hint_text=hint
                )
                if log:
                    display_text += f"\n\n{log}"

                # Update history with inline data
                model_msg = Message(
                    role=Role.MODEL,
                    parts=[
                        ContentPart(text=display_text),
                        ContentPart(
                            inline_data={"mimeType": mime_type, "data": video_data}
                        ),
                    ],
                )
                self.conversation.append(model_msg)
            else:
                # Just text history if download failed
                self.conversation.append(
                    Message(role=Role.MODEL, parts=[ContentPart(text=display_text)])
                )

            return (display_text.strip(), ""), None

        except Exception as e:
            self._report_error("Veo Video", e)
            return (None, None), None

    def _upload_file(
        self, path: Path, mime_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """Handles resumable upload to Gemini File API."""
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(path)
        if not mime_type:
            return None
        file_size = path.stat().st_size

        headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            console.print(
                f"[dim]Initiating upload for {path.name} "
                f"({file_size / 1024 / 1024:.2f} MB)...[/dim]"
            )
            start_response = requests.post(
                self.UPLOAD_API_URL,
                headers=headers,
                json={"file": {"display_name": path.name}},
                timeout=self.UPLOAD_START_TIMEOUT,
            )
            start_response.raise_for_status()
            upload_url = start_response.headers["X-Goog-Upload-URL"]

            console.print(f"[dim]Uploading {path.name}...[/dim]")
            with path.open("rb") as f:
                upload_response = requests.post(
                    upload_url,
                    data=f,
                    headers={
                        "Content-Length": str(file_size),
                        "X-Goog-Upload-Offset": "0",
                        "X-Goog-Upload-Command": "upload,finalize",
                    },
                    timeout=self.UPLOAD_TIMEOUT,
                )
                upload_response.raise_for_status()
                file_info = upload_response.json()["file"]

            if not self._wait_for_file_active(file_info["name"]):
                return None

            return file_info["uri"], mime_type
        except Exception as e:
            self._report_error("Upload", e)
            return None

    def _wait_for_file_active(self, file_name: str) -> bool:
        """Polls the file status until it is ACTIVE."""
        console.print("[dim]Waiting for remote file processing...[/dim]")
        url = f"{self.BASE_API_URL}/{file_name}?key={self.api_key}"

        for i in range(120):
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                info = r.json()
                state = info.get("state")

                if state == "ACTIVE":
                    console.print("[dim]File is active.[/dim]")
                    return True
                if state == "FAILED":
                    console.print("[red]File processing failed.[/red]")
                    return False

                time.sleep(5)
            except Exception as e:
                console.print(f"[dim red]Polling failed: {e}. Retrying...[/dim red]")
                time.sleep(5)

        console.print("[red]File processing timed out.[/red]")
        return False
