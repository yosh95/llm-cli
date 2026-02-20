# llm_cli/clients/grok.py

import json
import time
from typing import Any

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.x.ai/v1/chat/completions"
IMAGE_API_URL = "https://api.x.ai/v1/images/generations"
VIDEO_GENERATION_URL = "https://api.x.ai/v1/videos/generations"
VIDEO_RESULT_URL_TEMPLATE = "https://api.x.ai/v1/videos/{}"


class GrokClient(BaseLlmClient):
    """
    Client for interacting with the xAI Grok API.

    Compatible with OpenAI-style chat completions.

    Note: Grok 4 performs internal reasoning but does NOT expose reasoning
    content via the API. The reasoning_content field is not returned even
    though reasoning tokens are billed. This is a limitation of the xAI API.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Grok client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="xai",
            pdf_as_base64=False,
            **kwargs,
        )
        config_url = get_setting("api_url", "xai")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("xai")

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        m = self.model.lower()
        return "image" in m and "video" not in m

    def _is_video_model(self) -> bool:
        """Determines if the current model is a video generation model."""
        m = self.model.lower()
        return "video" in m

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Sends the conversation history and new data to Grok."""
        # Check if we should use image generation path
        # If tools are enabled or there are images in the input, we might want the
        # chat path instead, but if the model is strictly an image model,
        # we stay on this path.
        if self._is_image_model():
            return self._send_image_generation(data)
        if self._is_video_model():
            return self._send_video_generation(data)

        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "messages": messages,
        }

        # Note: Grok 4 does NOT return reasoning_content via API.
        # We don't add any reasoning configuration as it has no effect
        # on the response format (reasoning tokens are still billed).

        if self.active_tools and self.tools_enabled:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
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

            choice = res["choices"][0]["message"]
            content = choice.get("content", "")
            thought_text = ""
            model_parts: list[str | ContentPart] = []

            # Note: reasoning_content is NOT returned by Grok 4 API
            # even though the model performs internal reasoning.
            # This code is kept for potential future API updates.
            reasoning = choice.get("reasoning_content")
            if reasoning:
                model_parts.append(ContentPart(thought=reasoning))
                thought_text += reasoning

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
            self._report_error("Grok", e)
            return (None, None), None

    def _send_image_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Handles image generation via Grok API."""
        # Extract prompt from conversation and new data
        prompt_parts = []
        for m in self.conversation:
            for p in m.parts:
                if isinstance(p, ContentPart) and p.text:
                    prompt_parts.append(p.text)
                elif isinstance(p, str):
                    prompt_parts.append(p)

        for d in data:
            if d.content_type == "text/plain":
                prompt_parts.append(str(d.content))
            else:
                # Include a placeholder for non-text data to maintain context
                prompt_parts.append(f"[Attached {d.content_type}]")

        full_prompt = "\n".join(prompt_parts)
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "n": 1,
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
            res = response.json()

            data_item = res["data"][0]
            revised_prompt = data_item.get("revised_prompt", "")
            img_data = None
            mime_type = "image/png"  # Default

            # Handle both URL and Base64 response formats
            if "b64_json" in data_item:
                img_data = data_item["b64_json"]
            elif "url" in data_item:
                img_url = data_item["url"]
                from llm_cli.modules.media_utils import fetch_url_content

                img_data, fetched_mime = fetch_url_content(img_url)
                if fetched_mime:
                    mime_type = fetched_mime

            if not img_data:
                return ("Failed to retrieve image data from the response.", ""), None

            # Use shared media saving logic from BaseLlmClient
            display_text, _ = self._save_inline_media_and_get_log_entry(
                {"mimeType": mime_type, "data": img_data}, hint_text=full_prompt[:100]
            )
            if not display_text:
                display_text = (
                    "Successfully generated image, but failed to save it locally."
                )

            if revised_prompt:
                display_text += f"\n**Revised Prompt:** {revised_prompt}"

            # Update history with the image data (base64)
            model_msg = Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(text=display_text),
                    ContentPart(inline_data={"mimeType": mime_type, "data": img_data}),
                ],
            )
            self._update_history(data, model_msg)

            return (display_text.strip(), ""), None
        except Exception as e:
            self._report_error("Grok Image", e)
            return (None, None), None

    def _send_video_generation(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Handles video generation via Grok API (deferred)."""
        # Extract prompt from conversation and new data
        prompt_parts = []
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
        payload = {
            "model": self.model,
            "prompt": full_prompt,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # Step 1: Start generation
            response = self._post(
                VIDEO_GENERATION_URL,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            request_id = res.get("request_id") or res.get("id")
            if not request_id:
                return (("Failed to get request_id for video generation.", ""), None)

            # Step 2: Poll for results
            video_url = None
            start_time = time.time()
            timeout_seconds = 1800  # 30 minutes timeout for video

            # Notify user that generation started
            from llm_cli.clients.base import console

            console.print(
                "[dim]Video generation started. Polling for results... "
                "(this may take a few minutes)[/dim]"
            )

            while time.time() - start_time < timeout_seconds:
                poll_url = VIDEO_RESULT_URL_TEMPLATE.format(request_id)

                poll_response = self._get(
                    poll_url,
                    headers=headers,
                    timeout=self.request_timeout,
                )

                if poll_response.status_code == 200:
                    poll_res = poll_response.json()
                    status = poll_res.get("status")

                    if status == "completed":
                        video_url = poll_res.get("url")
                        if not video_url and "data" in poll_res:
                            if isinstance(poll_res["data"], dict):
                                video_url = poll_res["data"].get("url")
                            elif (
                                isinstance(poll_res["data"], list)
                                and len(poll_res["data"]) > 0
                            ):
                                video_url = poll_res["data"][0].get("url")

                        if video_url:
                            break
                    elif status == "failed":
                        return (
                            (
                                f"Video generation failed: "
                                f"{poll_res.get('error', 'Unknown error')}",
                                "",
                            ),
                            None,
                        )

                elif poll_response.status_code not in (200, 202):
                    # Log unexpected status but continue polling unless fatal
                    pass

                time.sleep(5)  # Poll interval

            if not video_url:
                return (
                    (
                        "Video generation timed out or failed to retrieve URL.",
                        "",
                    ),
                    None,
                )

            display_text = (
                f"Successfully generated video based on prompt.\n\n"
                f"[Download Video]({video_url})\n\n**Video URL:** `{video_url}`"
            )

            # Update history with text representation
            model_msg = Message(
                role=Role.MODEL,
                parts=[ContentPart(text=display_text)],
            )
            self._update_history(data, model_msg)

            return ((display_text.strip(), ""), None)

        except Exception as e:
            self._report_error("Grok Video", e)
            return ((None, None), None)

    def _update_history(self, data: list[DataSource], model_msg: Message) -> None:
        """Updates internal history."""
        user_parts: list[str | ContentPart] = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                user_parts.append(
                    ContentPart(
                        inline_data={
                            "mimeType": d.content_type,
                            "data": d.content,
                        }
                    )
                )

        if user_parts:
            self.conversation.append(Message(role=Role.USER, parts=user_parts))
        self.conversation.append(model_msg)

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal history to Grok (OpenAI-compatible) format."""
        msgs: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        responded_tool_ids = set()
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        tool_id = p.function_response.get("id")
                        if tool_id and tool_id != "unknown":
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        is_responded = (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        )
                        if is_responded:
                            result = func_resp.get("response", {}).get("result", "")
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(tool_id),
                                    "content": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else m.role.value
                msg_content = ""
                tool_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        msg_content += p
                    elif isinstance(p, ContentPart):
                        if p.text:
                            msg_content += p.text
                        # Note: We don't include p.thought in history for Grok
                        # as Grok 4 doesn't return reasoning_content anyway
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            is_responded = (
                                tool_id
                                and tool_id != "unknown"
                                and tool_id in responded_tool_ids
                            )
                            if is_responded:
                                tool_calls.append(
                                    {
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": func_call.get("name", "unknown"),
                                            "arguments": json.dumps(
                                                func_call.get("args", {})
                                            ),
                                        },
                                    }
                                )

                if msg_content or tool_calls:
                    msg: dict[str, Any] = {"role": role, "content": msg_content or None}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        user_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{d.content_type};base64,{d.content}"
                        },
                    }
                )

        if user_content:
            from typing import cast

            msgs.append(cast(dict[str, Any], {"role": "user", "content": user_content}))

        return msgs
