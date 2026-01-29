# llm_cli/clients/openai.py

import json
from typing import Any, Dict, List, Optional, Tuple

import requests

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

# OpenAI Responses API endpoint (recommended for reasoning models)
DEFAULT_API_URL = "https://api.openai.com/v1/responses"
IMAGE_API_URL = "https://api.openai.com/v1/images/generations"


class OpenAIClient(BaseLlmClient):
    """
    Client for interacting with OpenAI's Responses API and Images API.

    Supports vision, tool calling, reasoning modes with summary output,
    and DALL-E image generation.

    Note: This client uses the Responses API (not Chat Completions) for better
    support of reasoning models like GPT-5 and o-series. Reasoning tokens are
    not directly visible, but a summary can be retrieved via reasoning.summary.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs):
        """Initializes the OpenAI client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="openai",
            pdf_as_base64=False,
            **kwargs,
        )
        # Load custom API URL if provided, otherwise use default
        config_url = get_setting("api_url", "openai")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("openai")

    def _is_image_model(self) -> bool:
        """Determines if the current model is an image generation model."""
        m = self.model.lower()
        return "dall-e" in m or "image" in m

    def _is_video_model(self) -> bool:
        """Determines if the current model is a video generation model."""
        m = self.model.lower()
        return "sora" in m

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Sends the conversation history and new data to OpenAI Responses API.
        """
        if self._is_image_model():
            return self._send_image_generation(data)
        if self._is_video_model():
            return self._send_video_generation(data)

        input_items = self._build_input_items(data)
        payload = {
            "model": self.model,
            "input": input_items,
        }

        # Add system instructions if enabled
        if self.system_prompt and self.system_prompt_enabled:
            payload["instructions"] = self.system_prompt

        # Add tools if enabled
        if self.active_tools and self.tools_enabled:
            standard_tools = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )
            # Transform for Responses API: Move function fields to top level
            transformed_tools = []
            for t in standard_tools:
                if t.get("type") == "function" and "function" in t:
                    f = t["function"]
                    transformed_tools.append(
                        {
                            "type": "function",
                            "name": f.get("name"),
                            "description": f.get("description"),
                            "parameters": f.get("parameters"),
                        }
                    )
                else:
                    transformed_tools.append(t)
            payload["tools"] = transformed_tools

        # Configure reasoning for reasoning models (GPT-5, o-series)
        if self.reasoning_enabled:
            payload["reasoning"] = {
                "effort": getattr(self, "reasoning_effort", "medium"),
                "summary": getattr(self, "reasoning_summary", "auto"),
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post_with_retry(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            model_parts: List[ContentPart] = []
            full_text = ""
            thought_text = ""

            # Parse Responses API output array
            for item in res.get("output", []):
                item_type = item.get("type")

                if item_type == "reasoning":
                    # Extract reasoning summary if available
                    summaries = item.get("summary", [])
                    for summary in summaries:
                        if summary.get("type") == "summary_text":
                            reasoning_text = summary.get("text", "")
                            if reasoning_text:
                                thought_text += reasoning_text
                                model_parts.append(ContentPart(thought=reasoning_text))

                elif item_type == "message":
                    # Extract text content from message
                    for content_block in item.get("content", []):
                        if content_block.get("type") == "output_text":
                            text_content = content_block.get("text", "")
                            if text_content:
                                full_text += text_content
                                model_parts.append(ContentPart(text=text_content))

                elif item_type == "function_call":
                    # Handle function/tool calls
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": item.get("call_id", item.get("id")),
                                "name": item.get("name"),
                                "args": json.loads(item.get("arguments", "{}")),
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)

            self._update_history(data, model_msg)
            return (full_text.strip(), thought_text.strip()), res.get("usage")
        except Exception as e:
            self._report_error("OpenAI", e)
            return (None, None), None

    def _send_image_generation(
        self, data: List[DataSource]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Handles image generation via OpenAI's DALL-E API."""
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
            "n": 1,
            "size": "1024x1024",
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post_with_retry(
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
            self._report_error("OpenAI Image", e)
            return (None, None), None

    def _send_video_generation(
        self, data: List[DataSource]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Handles video generation via OpenAI Sora API."""
        import time

        from llm_cli.clients.base import console

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

        # Assuming endpoint based on search results (similar to Images API)
        # Note: This is based on preview documentation/community info
        video_api_url = "https://api.openai.com/v1/videos"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # Step 1: Start generation
            response = self._post_with_retry(
                video_api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            # Expecting an ID for polling
            video_id = res.get("id")
            if not video_id:
                return ("Failed to get video ID from response.", ""), None

            # Step 2: Poll for results
            video_url = None
            start_time = time.time()
            timeout_seconds = 1800  # 30 minutes

            console.print(
                "[dim]Video generation started. Polling for results... "
                "(this may take a few minutes)[/dim]"
            )

            while time.time() - start_time < timeout_seconds:
                poll_url = f"{video_api_url}/{video_id}"

                poll_response = requests.get(
                    poll_url,
                    headers=headers,
                    timeout=self.request_timeout,
                )

                if poll_response.status_code == 200:
                    poll_res = poll_response.json()
                    status = poll_res.get("status")

                    if status == "completed":
                        # Look for URL in various possible fields
                        # result_url is common in OpenAI async patterns,
                        # but check others too
                        video_url = poll_res.get("result_url")
                        if not video_url:
                            # Try 'data' array like image API
                            if "data" in poll_res and poll_res["data"]:
                                video_url = poll_res["data"][0].get("url")
                            # Try 'video' object
                            elif "video" in poll_res:
                                video_url = poll_res["video"].get("url")

                        if video_url:
                            break
                    elif status == "failed":
                        err = poll_res.get("error", {}).get("message", "Unknown error")
                        return (f"Video generation failed: {err}", ""), None

                    # If status is 'processing' or 'pending', continue polling
                    pass

                elif poll_response.status_code not in (200, 202):
                    # Log unexpected status but continue polling unless fatal
                    pass

                time.sleep(5)

            if not video_url:
                return (
                    "Video generation timed out or failed to retrieve URL.",
                    "",
                ), None

            display_text = (
                f"Successfully generated video.\n\n**Video URL:** `{video_url}`"
            )

            # Download and save
            from llm_cli.modules.media_utils import fetch_url_content

            video_data, mime_type = fetch_url_content(video_url)
            if video_data and mime_type:
                hint = full_prompt[:100]
                log, saved_path = self._save_inline_media_and_get_log_entry(
                    {"mimeType": mime_type, "data": video_data}, hint_text=hint
                )
                if log:
                    display_text += f"\n\n{log}"

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
                self.conversation.append(
                    Message(role=Role.MODEL, parts=[ContentPart(text=display_text)])
                )

            return (display_text.strip(), ""), None

        except Exception as e:
            self._report_error("OpenAI Sora", e)
            return (None, None), None

    def _update_history(self, data: List[DataSource], model_msg: Message):
        """Updates the internal conversation history with new messages."""
        user_parts: List[ContentPart] = []
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

    def _build_input_items(self, data: List[DataSource]) -> List[Dict[str, Any]]:
        """Converts the internal conversation history to OpenAI Responses API format."""
        items = []

        # Track tool_call_ids that have responses
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
                # Add function call outputs
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        ):
                            result = func_resp.get("response", {}).get("result", "")
                            items.append(
                                {
                                    "type": "function_call_output",
                                    "call_id": tool_id,
                                    "output": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else "user"
                content_parts = []
                function_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        content_parts.append({"type": "input_text", "text": p})
                    elif isinstance(p, ContentPart):
                        if p.text:
                            text_type = (
                                "output_text" if role == "assistant" else "input_text"
                            )
                            content_parts.append({"type": text_type, "text": p.text})
                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            if mime.startswith("image/"):
                                content_parts.append(
                                    {
                                        "type": "input_image",
                                        "image_url": (
                                            f"data:{mime};base64,"
                                            f"{p.inline_data.get('data', '')}"
                                        ),
                                    }
                                )
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if (
                                tool_id
                                and tool_id != "unknown"
                                and tool_id in responded_tool_ids
                            ):
                                function_calls.append(
                                    {
                                        "type": "function_call",
                                        "call_id": tool_id,
                                        "name": func_call.get("name", "unknown"),
                                        "arguments": json.dumps(
                                            func_call.get("args", {})
                                        ),
                                    }
                                )

                # Add message item
                if content_parts:
                    items.append(
                        {
                            "type": "message",
                            "role": role,
                            "content": content_parts,
                        }
                    )

                # Add function calls separately
                for fc in function_calls:
                    items.append(fc)

        # Append incoming data for the next user message
        user_content = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "input_text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{d.content_type};base64,{d.content}",
                    }
                )

        if user_content:
            items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": user_content,
                }
            )

        return items
