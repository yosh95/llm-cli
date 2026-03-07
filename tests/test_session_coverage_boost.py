import os
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.exceptions import CheckpointRequest, ExitRequest, TemplateRequest
from llm_cli.clients.session import ChatSession
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class MockClient(BaseLlmClient):
    def __init__(self):
        self.history_path = None
        self.conversation = []
        self.chat_log_path = None
        self.stdout = False
        self.model = "test-model"
        self.last_usage = None
        self.max_chat_log_lines = 100
        self._slash_commands = set()

    def _load_model_aliases(self):
        pass

    def _send(self, _data):
        return (("Response", None), {"prompt_tokens": 10})

    def _handle_command(self, _user_input, _sources, _pending_data):
        return False

    def get_display_name(self):
        return "TestBot"

    def _has_pending_tool_calls(self):
        return False

    def _trim_log_file(self, path, max_lines):
        pass

    def get_conversation_state(self):
        return []

    def set_conversation_state(self, state):
        pass

    def clear_history(self):
        self.conversation = []


@pytest.fixture
def session():
    client = MockClient()
    return ChatSession(client)


def test_editor_key_binding():
    """Test the c-x c-e editor key binding logic."""
    from llm_cli.clients.session import kb

    editor_handler = None
    for binding in kb.bindings:
        if binding.keys == ("c-x", "c-e"):
            editor_handler = binding.handler
            break

    assert editor_handler is not None

    mock_event = MagicMock()
    mock_event.current_buffer.text = "original text"

    with patch.dict(os.environ, {"EDITOR": "dummy-editor"}):
        with patch("subprocess.call", return_value=0) as mock_call:
            with patch("llm_cli.clients.session.Path") as MockPath:
                mock_path_instance = MockPath.return_value
                mock_path_instance.exists.return_value = True
                mock_file = mock_path_instance.open.return_value.__enter__.return_value
                mock_file.read.return_value = "new text from editor"

                with patch("tempfile.NamedTemporaryFile") as mock_tf:
                    mock_tf_instance = mock_tf.return_value.__enter__.return_value
                    mock_tf_instance.name = "fake_temp_file"

                    editor_handler(mock_event)

    assert mock_event.current_buffer.text == "new text from editor"
    assert mock_call.called


def test_run_exception_handling():
    """Test CheckpointRequest, TemplateRequest, ExitRequest in run loop."""
    client = MockClient()
    client._handle_command = MagicMock(
        side_effect=[
            CheckpointRequest(),
            TemplateRequest("templated text"),
            ExitRequest(),
        ]
    )

    with patch("llm_cli.clients.session.PromptSession") as mock_prompt_cls:
        mock_prompt = mock_prompt_cls.return_value
        mock_prompt.prompt.side_effect = ["cmd1", "cmd2", "cmd3"]

        session_obj = ChatSession(client)
        with patch.object(session_obj, "_handle_checkpoint") as mock_checkpoint:
            session_obj.run()

            assert mock_checkpoint.call_count == 1
            assert (
                mock_prompt.prompt.call_args_list[2][1]["default"] == "templated text"
            )


def test_process_and_print_with_tool_loop(session):
    """Test the complex tool execution loop."""
    session.client._send = MagicMock(
        side_effect=[(("Tool Reply", None), {}), (("Final Answer", None), {})]
    )
    session.client._has_pending_tool_calls = MagicMock(
        side_effect=[True, True, True, False, False, False]
    )

    tool_part = ContentPart(function_call={"name": "test_tool", "args": {}})
    session.client.conversation = [Message(role=Role.MODEL, parts=[tool_part])]

    tool_result_part = ContentPart(
        function_response={"name": "test_tool", "response": {"result": "ok"}}
    )
    with patch.object(
        session, "_execute_tool_call", return_value=(tool_result_part, None)
    ):
        session.process_and_print(
            [DataSource(content="hello", content_type="text/plain")]
        )

    assert session.client._send.call_count == 2
    assert any(m.role == Role.TOOL for m in session.client.conversation)


def test_process_and_print_branches(session):
    """Test various branches in process_and_print."""
    # Test last_usage assignment
    session.client._send = MagicMock(return_value=(("Text", None), {"usage": 100}))
    session.process_and_print([DataSource(content="hi", content_type="text/plain")])
    assert session.client.last_usage == {"usage": 100}

    # Test thought duration display
    session.client._send = MagicMock(return_value=(("Text", "ThoughtContent"), {}))
    with patch.object(session, "_print_block") as mock_print:
        session.process_and_print([DataSource(content="hi", content_type="text/plain")])
        # Check title instead of object
        assert any(
            "Thought" in kwargs.get("title", "")
            for _, kwargs in mock_print.call_args_list
        )

    # Test stdout mode
    session.client.stdout = True
    session.client._send = MagicMock(return_value=(("Direct output", None), {}))
    with patch("builtins.print") as mock_print:
        session.process_and_print([DataSource(content="hi", content_type="text/plain")])
        mock_print.assert_called_with("Direct output")


def test_run_empty_input():
    """Test continue on empty input (line 172)."""
    client = MockClient()
    with patch("llm_cli.clients.session.PromptSession") as mock_prompt_cls:
        mock_prompt = mock_prompt_cls.return_value
        mock_prompt.prompt.side_effect = ["", KeyboardInterrupt()]

        session_obj = ChatSession(client)
        session_obj.run()
        assert mock_prompt.prompt.call_count == 2


def test_tool_loop_edge_cases(session):
    """Test specific branches in tool execution loop (270, 275, 282)."""
    session.client._has_pending_tool_calls = MagicMock(return_value=True)
    tool_part = ContentPart(function_call={"name": "test_tool", "args": {}})
    session.client.conversation = [Message(role=Role.MODEL, parts=[tool_part])]

    with patch.object(session, "_execute_tool_call", return_value=None):
        session.process_and_print([])

    session.client._has_pending_tool_calls = MagicMock(
        side_effect=[True, True, True, False, False, False]
    )
    injected = DataSource(content="file content", content_type="text/plain")
    tool_result = ContentPart(function_response={"name": "t", "response": {}})

    # We need to make sure _send handles the injected data
    session.client._send = MagicMock(return_value=(("Response", None), {}))

    with patch.object(
        session, "_execute_tool_call", return_value=(tool_result, injected)
    ):
        with patch.object(session, "_log_chat") as mock_log:
            session.process_and_print([])
            # Verify logging of injected data list
            # The injected data is passed as a list to _log_chat
            assert any(
                isinstance(args[0], list) and injected in args[0]
                for args, _ in mock_log.call_args_list
            )


def test_log_chat_errors(session):
    """Test error handling in _log_chat."""
    session.client.chat_log_path = "/nonexistent/path/to/log"
    with patch("pathlib.Path.open", side_effect=OSError("Permission denied")):
        with patch("llm_cli.clients.session.console.print") as mock_print:
            session._log_chat("message", "role")
            assert any(
                "failed" in str(args[0]).lower()
                for args, _ in mock_print.call_args_list
            )


def test_get_input_no_tty_fallback(session):
    """Test TTY fallback when stdin is not a tty."""
    with patch("sys.stdin.isatty", return_value=False):
        with patch("llm_cli.clients.session.Path") as MockPath:
            mock_path_instance = MockPath.return_value
            mock_file = mock_path_instance.open.return_value.__enter__.return_value
            mock_file.readline.return_value = "input from tty\n"

            with patch("sys.platform", "linux"):
                result = session._get_input("Prompt: ")
                assert result == "input from tty"


def test_checkpoint_failure_handling(session):
    """Test failure cases in _handle_checkpoint."""
    session.client._send = MagicMock(return_value=None)
    with patch("llm_cli.clients.session.console.print") as mock_print:
        session._handle_checkpoint()
        assert any("Failed" in str(args[0]) for args, _ in mock_print.call_args_list)

    session.client._send = MagicMock(side_effect=RuntimeError("API Down"))
    with patch("llm_cli.clients.session.console.print") as mock_print:
        session._handle_checkpoint()
        assert any(
            "failed" in str(args[0]).lower() for args, _ in mock_print.call_args_list
        )
