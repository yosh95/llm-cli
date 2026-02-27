from unittest.mock import MagicMock, patch

import pytest
from prompt_toolkit.document import Document

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.session import ChatSession, LlmCliCompleter
from llm_cli.modules.models import ContentPart


class MockClient(BaseLlmClient):
    def __init__(self):
        self._slash_commands = {
            "attach",
            "save",
            "load",
            "provider",
            "model",
            "template",
        }
        self.PROVIDER_CONFIG = {"google": {}, "openai": {}}
        self.available_models = {"gemini": "gemini-pro", "gpt4": "gpt-4"}
        self.history_path = None
        self.conversation = []
        self.chat_log_path = None
        self.stdout = False
        self.model = "test-model"
        self.cumulative_total_tokens = 0
        self._handle_command_called = False

    def _load_model_aliases(self):
        pass

    def _send(self, _data):
        return ("Response", None), {}

    def _handle_command(self, _user_input, _sources, _pending_data):
        self._handle_command_called = True
        return False

    def get_display_name(self):
        return "TestBot"

    def _has_pending_tool_calls(self):
        return False

    def _trim_log_file(self, path, max_lines):
        pass


@pytest.fixture
def mock_client():
    return MockClient()


class TestLlmCliCompleter:
    def test_command_completion(self, mock_client):
        completer = LlmCliCompleter(mock_client)
        doc = Document("/sav", cursor_position=4)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) > 0
        assert any(c.text == "/save" for c in completions)

    def test_provider_completion(self, mock_client):
        completer = LlmCliCompleter(mock_client)
        doc = Document("/provider go", cursor_position=12)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) > 0
        assert any(c.text == "google" for c in completions)

    def test_model_completion(self, mock_client):
        completer = LlmCliCompleter(mock_client)
        doc = Document("/model gem", cursor_position=10)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) > 0
        assert any(c.text == "gemini" for c in completions)

    def test_template_completion(self, mock_client):
        with patch(
            "llm_cli.clients.session.get_templates",
            return_value={"bug_report": "template"},
        ):
            completer = LlmCliCompleter(mock_client)
            doc = Document("/template bug", cursor_position=13)
            completions = list(completer.get_completions(doc, None))
            assert len(completions) > 0
            assert any(c.text == "bug_report" for c in completions)


class TestChatSession:
    @pytest.fixture
    def session(self, mock_client):
        return ChatSession(mock_client)

    def test_init(self, session, mock_client):
        assert session.client == mock_client
        assert session.prompt_history is not None

    def test_run_basic_loop(self, mock_client):
        # Patch PromptSession before creating ChatSession to ensure the mock is used
        with patch("llm_cli.clients.session.PromptSession") as mock_prompt_cls:
            mock_prompt = mock_prompt_cls.return_value
            # Simulate user input: "hello", then interrupt to exit
            mock_prompt.prompt.side_effect = ["hello", KeyboardInterrupt()]

            session = ChatSession(mock_client)
            session.run()

            assert mock_prompt.prompt.call_count == 2

    # ... (other tests)

    def test_execute_tool_call_no_approval(self, session):
        with patch("llm_cli.clients.session.registry") as mock_registry:
            mock_tool_func = MagicMock(return_value="Tool Result")
            tool_entry = {
                "skip_approval": True,
                "func": mock_tool_func,
                "interactive": False,
            }

            mock_tools = MagicMock()
            mock_tools.__getitem__.return_value = tool_entry
            mock_tools.get.return_value = tool_entry
            mock_tools.__contains__.return_value = True
            mock_registry.tools = mock_tools

            part = ContentPart(function_call={"name": "test_tool", "args": {}})
            result = session._execute_tool_call(part)

            assert result is not None
            res_part, injected = result
            assert res_part.function_response["response"]["result"] == "Tool Result"

    def test_execute_tool_call_with_approval_granted(self, session):
        with patch("llm_cli.clients.session.registry") as mock_registry:
            mock_tool_func = MagicMock(return_value="Tool Result")
            tool_entry = {
                "skip_approval": False,
                "func": mock_tool_func,
                "interactive": False,
            }

            mock_tools = MagicMock()
            mock_tools.__getitem__.return_value = tool_entry
            mock_tools.get.return_value = tool_entry
            mock_tools.__contains__.return_value = True
            mock_registry.tools = mock_tools

            with patch.object(session, "_get_input", return_value="y"):
                part = ContentPart(function_call={"name": "dangerous_tool", "args": {}})
                result = session._execute_tool_call(part)

                assert result is not None
                res_part, _ = result
                assert res_part.function_response["response"]["result"] == "Tool Result"

    def test_execute_tool_call_with_approval_denied(self, session):
        with patch("llm_cli.clients.session.registry") as mock_registry:
            tool_entry = {
                "skip_approval": False,
                "func": MagicMock(),
                "interactive": False,
            }

            mock_tools = MagicMock()
            mock_tools.__getitem__.return_value = tool_entry
            mock_tools.get.return_value = tool_entry
            mock_tools.__contains__.return_value = True
            mock_registry.tools = mock_tools

            with patch.object(session, "_get_input", return_value="n"):
                part = ContentPart(function_call={"name": "dangerous_tool", "args": {}})
                result = session._execute_tool_call(part)

                assert result is not None
                res_part, _ = result
                assert (
                    "Operation denied"
                    in res_part.function_response["response"]["result"]
                )

    def test_handle_checkpoint_success(self, session):
        # Mock _send to return a summary
        session.client._send = MagicMock(return_value=(("Summary text", None), {}))

        # Mock confirm to yes
        with patch.object(session, "_confirm", return_value=True):
            session._handle_checkpoint()

            # Conversation should be reset to just the summary system message
            assert len(session.client.conversation) == 1
            assert "Summary text" in session.client.conversation[0].parts[0].text

    def test_handle_checkpoint_cancel(self, session):
        session.client._send = MagicMock(return_value=(("Summary text", None), {}))

        # Mock confirm to no
        with patch.object(session, "_confirm", return_value=False):
            original_len = len(session.client.conversation)
            session._handle_checkpoint()

            # Conversation should be restored (or unchanged if it was empty)
            assert len(session.client.conversation) == original_len

    def test_handle_checkpoint_interrupt(self, session):
        # Mock _send to raise KeyboardInterrupt
        session.client._send = MagicMock(side_effect=KeyboardInterrupt)

        original_len = len(session.client.conversation)

        # Should not raise KeyboardInterrupt
        try:
            session._handle_checkpoint()
        except KeyboardInterrupt:
            pytest.fail("KeyboardInterrupt should have been caught")

        # Conversation should be restored
        assert len(session.client.conversation) == original_len

    def test_get_input_interrupt(self, session):
        # Ensure _get_input catches KeyboardInterrupt and returns empty string
        # We need to mock sys.stdin.isatty to True to hit the prompt_toolkit path
        with patch("sys.stdin.isatty", return_value=True):
            with patch.object(
                session.prompt_session, "prompt", side_effect=KeyboardInterrupt
            ):
                result = session._get_input("Test: ")
                assert result == ""

    def test_get_input_raise_interrupt(self, session):
        # Ensure _get_input raises KeyboardInterrupt when raise_on_interrupt=True
        with patch("sys.stdin.isatty", return_value=True):
            with patch.object(
                session.prompt_session, "prompt", side_effect=KeyboardInterrupt
            ):
                with pytest.raises(KeyboardInterrupt):
                    session._get_input("Test: ", raise_on_interrupt=True)

    def test_handle_checkpoint_sends_prompt_as_data(self, session):
        # Mock _send
        session.client._send = MagicMock(return_value=(("Summary text", None), {}))

        # Mock confirm to yes
        with patch.object(session, "_confirm", return_value=True):
            session._handle_checkpoint()

            # Verify _send was called with a list containing DataSource with text content
            args, _ = session.client._send.call_args
            assert len(args[0]) == 1
            data_source = args[0][0]
            assert "Summarize" in str(data_source.content)
            assert data_source.content_type == "text/plain"

    def test_run_suggests_checkpoint_on_turns(self, session):
        from llm_cli.modules.models import Message, Role

        # Simulate 40 model turns
        session.client.conversation = [
            Message(role=Role.MODEL, parts=["Response"]) for _ in range(40)
        ]

        with patch("llm_cli.clients.session.PromptSession") as mock_prompt_cls:
            mock_prompt = mock_prompt_cls.return_value
            # First prompt triggers checkpoint, then exit
            mock_prompt.prompt.side_effect = KeyboardInterrupt()

            with patch.object(session, "_confirm", return_value=True) as mock_confirm:
                with patch.object(
                    session, "_handle_checkpoint"
                ) as mock_handle_checkpoint:
                    session.run()

                    mock_confirm.assert_called_once()
                    assert "turns" in mock_confirm.call_args[0][0]
                    mock_handle_checkpoint.assert_called_once()
