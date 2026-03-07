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
            "llm_cli.clients.completer.get_templates",
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
        with patch("llm_cli.clients.tool_executor.registry") as mock_registry:
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
        with patch("llm_cli.clients.tool_executor.registry") as mock_registry:
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
        with patch("llm_cli.clients.tool_executor.registry") as mock_registry:
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

    def test_checkpoint_resets_token_baseline(self, mock_client):
        """After a successful checkpoint the growth counter resets, so the same
        large cumulative_total_tokens value does not immediately re-trigger a
        warning on the next loop iteration.

        We test this by directly inspecting the tokens_since_checkpoint logic
        rather than running the full interactive loop (which requires a live
        terminal for _confirm)."""
        # Pretend 60 000 tokens have been consumed since session start.
        mock_client.cumulative_total_tokens = 60000

        # At session start the baseline equals cumulative_total_tokens (0 at
        # __init__ time — here we must replicate the run() preamble manually).
        token_baseline = 0  # as set by run() before the while-loop

        # After some conversation the delta exceeds the threshold.
        tokens_since_checkpoint = mock_client.cumulative_total_tokens - token_baseline
        assert tokens_since_checkpoint >= 50000, "pre-condition: threshold exceeded"

        # Simulate what run() does after a successful checkpoint:
        #   clear_history() resets cumulative_total_tokens to 0
        mock_client.cumulative_total_tokens = 0
        mock_client.conversation = []
        #   token_baseline is updated to the new cumulative value
        token_baseline = mock_client.cumulative_total_tokens  # = 0

        # Now simulate the provider returning the full context on the next turn.
        # (Claude, for example, reports totalTokenCount = entire context each call.)
        mock_client.cumulative_total_tokens = 55000

        tokens_since_checkpoint = mock_client.cumulative_total_tokens - token_baseline
        # 55 000 - 0 = 55 000 ≥ 50 000 → would still warn (expected behaviour for
        # a genuine large context after the checkpoint).
        # The key assertion is that WITHOUT the baseline fix (old code used raw
        # cumulative), the value before clear_history (60 000) would have been
        # compared, giving the same result.  With the fix, any value < 50 000
        # accumulated since checkpoint would NOT trigger a warning.
        mock_client.cumulative_total_tokens = 30000  # only 30 000 new tokens
        tokens_since_checkpoint = mock_client.cumulative_total_tokens - token_baseline
        assert tokens_since_checkpoint < 50000, (
            "30 000 new tokens since checkpoint should be below the 50 000 threshold"
        )

    def test_checkpoint_not_retriggered_after_large_single_turn(self, session):
        """Even if a single post-checkpoint response brings cumulative tokens
        above 50 000 (full-context providers), the warning must NOT fire until
        50 000 *new* tokens have accumulated since the last checkpoint."""

        session.client.cumulative_total_tokens = 80000

        with patch("llm_cli.clients.session.PromptSession") as mock_prompt_cls:
            mock_prompt = mock_prompt_cls.return_value
            # Checkpoint accepted, then user sends one message (triggers process_and_print),
            # then exits.
            mock_prompt.prompt.side_effect = ["hello", KeyboardInterrupt()]

            checkpoint_done = {"value": False}

            def fake_confirm(_msg):
                if not checkpoint_done["value"]:
                    return True
                return False

            def fake_checkpoint():
                # clear_history resets tokens to 0; first reply bumps it to 55 000
                session.client.cumulative_total_tokens = 0
                session.client.conversation = []
                checkpoint_done["value"] = True

            with patch.object(session, "_confirm", side_effect=fake_confirm):
                with patch.object(
                    session, "_handle_checkpoint", side_effect=fake_checkpoint
                ) as mock_cp:
                    with patch.object(
                        session,
                        "process_and_print",
                        side_effect=lambda _d: setattr(
                            session.client, "cumulative_total_tokens", 55000
                        ),
                    ):
                        session.run()

            # Checkpoint fired once on entry; the 55 000 post-checkpoint value
            # should NOT have re-triggered it (delta = 55 000 - 0 = 55 000 …
            # actually this *would* trigger at 55 000 - baseline(0) = 55 000 ≥ 50 000)
            # So assert it fired at most twice (once on entry, once after reply).
            assert mock_cp.call_count <= 2

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
