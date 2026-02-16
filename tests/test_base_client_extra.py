"""Tests for remaining BaseLlmClient functionality."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.models import DataSource


class ConcreteClient(BaseLlmClient):
    """Concrete implementation for testing."""

    def _load_model_aliases(self) -> None:
        self.available_models = {"default": "test-model"}

    def _send(
        self, _data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, int] | None]:
        return ("response", None), {}


@pytest.fixture
def client(mock_config: object) -> BaseLlmClient:
    """Fixture for a concrete client."""
    return ConcreteClient(
        initial_model_alias="default",
        api_key_name="api_key",
        config_section="test_section",
        pdf_as_base64=True,
        stdout=False,
    )


class TestBaseClientExtra:
    """Extra tests for BaseLlmClient."""

    def test_expand(self, client: BaseLlmClient) -> None:
        """Test path expansion."""
        assert client._expand(None) is None
        # Use a path that likely doesn't expand to something else in test env, or check basic string
        expanded = client._expand("/tmp")
        assert expanded is not None
        assert "/tmp" in expanded

    def test_post_get_wrappers(self, client: BaseLlmClient) -> None:
        """Test _post and _get wrappers."""
        with patch("requests.post") as mock_post:
            client._post("http://test.com", {"header": "1"}, {"data": "1"})
            mock_post.assert_called_with(
                "http://test.com",
                headers={"header": "1"},
                json={"data": "1"},
                timeout=None,
            )

        with patch("requests.get") as mock_get:
            client._get("http://test.com", {"header": "1"})
            mock_get.assert_called_with(
                "http://test.com", headers={"header": "1"}, timeout=None
            )

        # Test defaults
        with patch("requests.post") as mock_post:
            client._post("http://test.com", {}, {})
            mock_post.assert_called_with(
                "http://test.com", headers={}, json={}, timeout=None
            )

    def test_process_sources_logic(self, client: BaseLlmClient) -> None:
        """Test process_sources dispatch logic."""
        # Case 1: stdout=True -> process_and_print
        client.stdout = True
        with patch("llm_cli.clients.session.ChatSession") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            client.process_sources(["src1"])
            mock_session.process_and_print.assert_called()
            # If stdout is True, run is NOT called in 'process_sources' unless sources provided?
            # Code:
            # if data:
            #   if self.stdout or has_prompt:
            #       session.process_and_print(data)
            #       if not self.stdout: session.run(...)
            #   else: session.run(...)

            # Here stdout=True, so run() is NOT called if data is present?
            # Wait, if stdout=True, we process_and_print and stop?
            # Let's check code:
            # if not self.stdout: session.run(sources=sources)
            # So if stdout=True, run is not called. Correct.
            mock_session.run.assert_not_called()

        # Case 2: stdout=False, has_prompt=True (text source)
        client.stdout = False
        with patch("llm_cli.clients.session.ChatSession") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            # "text" is treated as prompt, so has_prompt=True
            client.process_sources(["some text"])
            mock_session.process_and_print.assert_called()
            mock_session.run.assert_called()

        # Case 3: stdout=False, has_prompt=False (file source)
        client.stdout = False
        with patch("llm_cli.clients.session.ChatSession") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            with patch.object(client, "_process_single_source") as mock_proc:
                # return a dummy file datasource
                mock_proc.return_value = DataSource(
                    content=b"", content_type="", is_file_or_url=True
                )
                client.process_sources(["file.txt"])
                mock_session.process_and_print.assert_not_called()
                mock_session.run.assert_called()

    def test_report_error_details(self, client: BaseLlmClient) -> None:
        """Test detailed error reporting with response body."""
        # JSON body
        err = requests.exceptions.HTTPError("400 Error")
        err.response = MagicMock()
        err.response.json.return_value = {"error": "bad request"}

        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._report_error("Test", err)
            assert "Response Body" in mock_print.call_args[0][0]
            assert '"error": "bad request"' in mock_print.call_args[0][0]

        # Text body (json parse fails)
        err = requests.exceptions.HTTPError("500 Error")
        err.response = MagicMock()
        err.response.json.side_effect = ValueError
        err.response.text = "Internal Server Error"

        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._report_error("Test", err)
            assert "Response Body: Internal Server Error" in mock_print.call_args[0][0]

    def test_get_model_icon(self, client: BaseLlmClient) -> None:
        """Test icon selection."""
        client.config_section = "google"
        assert client.get_model_icon() == "✨"
        client.config_section = "openai"
        assert client.get_model_icon() == "🤖"
        client.config_section = "anthropic"
        assert client.get_model_icon() == "🌿"
        client.config_section = "grok"
        assert client.get_model_icon() == "🌌"
        client.config_section = "ollama"
        assert client.get_model_icon() == "🦙"
        client.config_section = "other"
        assert client.get_model_icon() == "💡"

    def test_format_response_text(self, client: BaseLlmClient) -> None:
        """Test response text formatting."""
        client.model = "gpt-4"
        client.config_section = "openai"
        text = client._format_response_text(" hello ")
        assert text is not None
        assert "**🤖 (gpt-4):**" in text
        assert "hello" in text
        assert client._format_response_text(None) is None

    def test_init_mcp(self, client: BaseLlmClient) -> None:
        """Test MCP initialization."""
        # Mock sys.modules to simulate import
        mock_mcp_manager = MagicMock()
        mock_mcp_manager._initialized = False

        with patch.dict(
            "sys.modules",
            {"llm_cli.clients.mcp_manager": MagicMock(mcp_manager=mock_mcp_manager)},
        ):
            with patch(
                "llm_cli.modules.tool_registry.registry.register_remote_tools"
            ) as mock_reg:
                mock_reg.return_value = ["tool1"]

                # Test with update_active_tools=True
                client._init_mcp(update_active_tools=True)

                assert "tool1" in client.active_tools
                mock_reg.assert_called_with(mock_mcp_manager)

    def test_init_mcp_fail(self, client: BaseLlmClient) -> None:
        """Test MCP initialization failure."""
        with patch.dict("sys.modules", {"llm_cli.clients.mcp_manager": MagicMock()}):
            with patch(
                "llm_cli.modules.tool_registry.registry.register_remote_tools",
                side_effect=Exception("Failed"),
            ):
                with patch("llm_cli.clients.base.console.print") as mock_print:
                    client._init_mcp(True)
                    assert "MCP initialization failed" in mock_print.call_args[0][0]

    def test_print_live_debug_complex(self, client: BaseLlmClient) -> None:
        """Test detailed debug printing."""
        client.live_debug = True

        # Request object with body (bytes)
        req_obj = MagicMock()
        req_obj.request.url = "http://api.com"
        req_obj.request.body = b'{"key": "val"}'
        req_obj.status_code = 200
        req_obj.json.return_value = {"res": "ok"}

        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._log_debug(response_obj=req_obj)
            # Should see URL, request body, response
            # Check for panel titles
            titles = []
            for call in mock_print.call_args_list:
                arg = call.args[0]
                if hasattr(arg, "title"):
                    titles.append(arg.title)

            titles_str = "".join(titles)
            assert "API Request" in titles_str
            assert "API Response" in titles_str

        # Request object with invalid body
        req_obj.request.body = object()
        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._log_debug(response_obj=req_obj)

            # Check content for "Raw Body"
            # (Just ensuring no exception was raised)
            assert mock_print.called

            # Since we can't easily inspect Renderables without rendering,
            # let's just assert that we didn't crash and printed something.
            assert mock_print.called

    def test_has_pending_tool_calls(self, client: BaseLlmClient) -> None:
        """Test tool call detection."""
        from llm_cli.modules.models import ContentPart, Message, Role

        # No conversation
        client.conversation = []
        assert client._has_pending_tool_calls() is False

        # User message last
        client.conversation = [Message(Role.USER, ["hi"])]
        assert client._has_pending_tool_calls() is False

        # Model message no tools
        client.conversation = [Message(Role.MODEL, [ContentPart(text="hi")])]
        assert client._has_pending_tool_calls() is False

        # Model message with tool
        client.conversation = [
            Message(Role.MODEL, [ContentPart(function_call={"name": "tool"})])
        ]
        assert client._has_pending_tool_calls() is True
