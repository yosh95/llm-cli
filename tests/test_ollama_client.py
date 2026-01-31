from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.ollama import OllamaClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class TestOllamaClient:
    @pytest.fixture
    def client(self):
        # Mock configuration loading
        # Patch where it is imported in ollama.py
        with (
            patch("llm_cli.clients.ollama.get_setting") as mock_get_setting,
            patch("llm_cli.clients.config.get_model_aliases") as mock_get_aliases,
        ):
            mock_get_setting.return_value = "http://test-ollama:11434"
            mock_get_aliases.return_value = {"default": "llama3"}

            client = OllamaClient(initial_model_alias="default", stdout=False)
            return client

    def test_initialization(self, client):
        # The mock in fixture sets api_url via get_setting, but BaseLlmClient constructor calls get_setting before OllamaClient sets it?
        # Actually OllamaClient.__init__ calls super().__init__ then sets self.api_url.
        # Check if the patch context is active when client is created. Yes it is.
        # Maybe get_setting is called with different args?
        # Let's inspect what happened or just assert on the logic we control.
        # If the mock worked, it should be the mock value.
        # If it failed, it might be DEFAULT_API_URL.
        assert client.api_url == "http://test-ollama:11434"

    def test_send_basic_text(self, client):
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}],
            "usage": {"total_tokens": 10},
        }

        with patch.object(client, "_post", return_value=mock_response) as mock_post:
            data = [DataSource(content="Hi", content_type="text/plain")]
            (text, thought), usage = client._send(data)

            assert text == "Hello world"
            assert thought == ""
            assert usage["total_tokens"] == 10

            # Verify request payload
            mock_post.assert_called_once()
            # _post signature: (url, headers, json_data, timeout, max_retries)
            # call_args.kwargs might contain json_data if passed by name
            kwargs = mock_post.call_args.kwargs
            payload = kwargs.get("json_data")
            if not payload:
                # If passed positionally: 0=url, 1=headers, 2=json_data
                args = mock_post.call_args.args
                if len(args) > 2:
                    payload = args[2]

            assert payload is not None
            assert payload["model"] == "llama3"
            assert payload["messages"][-1]["role"] == "user"
            assert payload["messages"][-1]["content"] == "Hi"

    def test_send_with_tool_calls(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,  # Content is None when tool_calls are present
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "Tokyo"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

        with patch.object(client, "_post", return_value=mock_response):
            data = [DataSource(content="Weather?", content_type="text/plain")]
            (text, thought), _ = client._send(data)

            # The client implementation might return "" if content is None but handled correctly
            # Or it might fail if it tries to strip() None.
            # OllamaClient._send: raw_content.strip() -> ERROR if raw_content is None.
            # _parse_response returns content="" if get("content") is None or ""?
            # Let's check _parse_response logic in actual code or fix expectations.
            # "content": None in JSON -> choice.get("content", "") might return None if key exists and is null?
            # No, dict.get("key", default) returns value if key exists (even if None).
            # So if API returns "content": null, get returns None.
            # We should probably fix the Client code to handle None content gracefully, or mock it as "" here if that's what we expect.
            # But "content": null is valid for tool calls.

            # Assuming we fix the client code or expect empty string.
            assert text == ""

            # Check conversation update
            last_msg = client.conversation[-1]
            assert last_msg.role == Role.MODEL
            assert last_msg.parts[0].function_call["name"] == "get_weather"
            assert last_msg.parts[0].function_call["args"]["location"] == "Tokyo"

    def test_send_with_think_tags(self, client):
        # Test handling of <think> tags (e.g. DeepSeek models)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "<think>Thinking hard...</think>The answer is 42."
                    }
                }
            ]
        }

        with patch.object(client, "_post", return_value=mock_response):
            data = [DataSource(content="Solve this", content_type="text/plain")]
            (text, thought), _ = client._send(data)

            assert text == "The answer is 42."
            assert thought == "Thinking hard..."

    def test_send_api_failure(self, client):
        with patch.object(client, "_post", side_effect=Exception("API Error")):
            data = [DataSource(content="Hi", content_type="text/plain")]
            (text, thought), usage = client._send(data)

            assert text is None
            assert thought is None
            assert usage is None

    def test_build_messages_with_history_and_tools(self, client):
        # Add history: User -> Model (Call) -> Tool (Result)
        client.conversation.append(
            Message(role=Role.USER, parts=[ContentPart(text="Check weather")])
        )
        client.conversation.append(
            Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(
                        function_call={"id": "call_1", "name": "weather", "args": {}}
                    )
                ],
            )
        )
        client.conversation.append(
            Message(
                role=Role.TOOL,
                parts=[
                    ContentPart(
                        function_response={
                            "id": "call_1",
                            "name": "weather",
                            "response": {"result": "Sunny"},
                        }
                    )
                ],
            )
        )

        msgs = client._build_messages(
            [DataSource(content="Next day?", content_type="text/plain")]
        )

        # Verify structure
        # 0: System (if any, default mock setting)
        # 1: User "Check weather"
        # 2: Assistant tool_calls=[...]
        # 3: Tool response
        # 4: User "Next day?"

        # Note: Index depends on system prompt. Default base client has system prompt enabled.
        # Let's check roles content
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles

        # Check tool call message
        tool_call_msg = next(
            m for m in msgs if m["role"] == "assistant" and "tool_calls" in m
        )
        assert tool_call_msg["tool_calls"][0]["id"] == "call_1"

        # Check tool response message
        tool_res_msg = next(m for m in msgs if m["role"] == "tool")
        assert tool_res_msg["tool_call_id"] == "call_1"
        assert tool_res_msg["content"] == "Sunny"

    def test_build_messages_skips_unanswered_tools(self, client):
        # Scenario: Model called tool, but no result yet (e.g. crash or interrupted).
        # Should NOT include tool_calls in history to avoid API error about missing tool response?
        # OR implementation allows it but subsequent logic might fail?
        # The implementation of _build_messages tracks responded_tool_ids.

        client.conversation.append(
            Message(
                role=Role.MODEL,
                parts=[
                    ContentPart(
                        function_call={"id": "call_orphan", "name": "test", "args": {}}
                    )
                ],
            )
        )

        msgs = client._build_messages([])

        # Ensure the orphan tool call is NOT included in the assistant message tool_calls
        # because the implementation logic: "if tool_id and tool_id in responded_tool_ids"
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        if assistant_msgs:
            # If there's an assistant message, it shouldn't have tool_calls for call_orphan
            assert "tool_calls" not in assistant_msgs[0]

    def test_parse_response_alternative_format(self, client):
        # Some Ollama versions or endpoints return direct 'message' instead of 'choices'
        res_json = {"message": {"content": "Direct response"}}
        content, tools, reasoning = client._parse_response(res_json)
        assert content == "Direct response"
        assert tools == []
        assert reasoning is None
