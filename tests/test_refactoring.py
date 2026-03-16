"""
tests/test_refactoring.py

Verifies the two high-priority refactoring items:

  1. Global variable elimination
     - `current_integrity_score` module global is gone.
     - `ReasoningSentinelManager.current_score` is an *instance* property.
     - Multiple manager instances are fully isolated.
     - `tool_registry` wrapper reads the score via `__audit_sentinel__`.
     - `command_handler` reads from `sentinel.current_score`, not from a global.

  2. `process_and_print` decomposition
     - `_run_single_turn()` handles the LLM call and returns (response, duration).
     - `_process_tool_loop()` handles tool execution and returns the correct signal.
     - `process_and_print()` orchestrates the two helpers correctly.
"""

from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.session import ChatSession
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.security.integrity import ReasoningSentinelManager

# ---------------------------------------------------------------------------
# Minimal mock client (copied from test_session_logic.py to keep tests isolated)
# ---------------------------------------------------------------------------


class _MockClient:
    def __init__(self):
        from llm_cli.clients.session_manager import SessionManager

        self._session_manager = SessionManager()
        self._slash_commands = set()
        self.config_section = "test"
        self.pdf_as_base64 = False
        self.available_models = {}
        self.current_alias = "default"
        self.history_path = None
        self.chat_log_path = None
        self.stdout = False
        self.model = "test-model"
        self.active_tools = []
        self.max_chat_log_lines = 1000
        self.live_debug = False
        self.tools_enabled = True
        self.system_prompt = ""
        self.system_prompt_enabled = True
        self.render_markdown = True
        self.last_usage = None

    @property
    def conversation(self):
        return self._session_manager.conversation

    @conversation.setter
    def conversation(self, value):
        self._session_manager.conversation = value

    # Required stubs
    def _load_model_aliases(self):
        pass

    def _set_initial_model(self, alias):
        pass

    def _refresh_general_settings(self):
        pass

    def _refresh_system_prompt(self):
        pass

    def _trim_log_file(self, path, max_lines):
        pass

    def get_display_name(self):
        return "TestBot"

    def _has_pending_tool_calls(self):
        return False

    def _send(self, _data):
        return (("Response", None), {})

    def _handle_command(self, *_args):
        return False


@pytest.fixture
def mock_client():
    return _MockClient()


@pytest.fixture
def session(mock_client):
    return ChatSession(mock_client)


# ===========================================================================
# 1. Global variable elimination
# ===========================================================================


class TestGlobalVariableElimination:
    """Ensure current_integrity_score no longer lives at module scope."""

    def test_module_global_is_removed(self):
        """The module-level `current_integrity_score` variable must not exist."""
        import llm_cli.security.integrity as integrity_module

        assert not hasattr(integrity_module, "current_integrity_score"), (
            "current_integrity_score should have been removed from module scope"
        )

    def test_instance_property_exists(self):
        """ReasoningSentinelManager must expose current_score as an instance attr."""
        with patch("llm_cli.clients.config.get_setting", return_value=None):
            manager = ReasoningSentinelManager()

        assert hasattr(manager, "current_score"), (
            "current_score instance property is missing"
        )
        # Initial value must be None (no data processed yet)
        assert manager.current_score is None

    def test_instance_isolation(self):
        """
        Two independent manager instances must not share score state.
        Writing to one must not affect the other.
        """
        with patch("llm_cli.clients.config.get_setting", return_value=None):
            mgr_a = ReasoningSentinelManager()
            mgr_b = ReasoningSentinelManager()

        # Directly set the instance property to simulate a processed chunk
        mgr_a.current_score = 1.23
        mgr_b.current_score = 9.99

        assert mgr_a.current_score == 1.23, "mgr_a score was mutated by mgr_b"
        assert mgr_b.current_score == 9.99, "mgr_b score was mutated by mgr_a"

    def test_process_chunk_updates_instance_not_global(self):
        """
        After process_chunk(), the score must be stored on the instance,
        and no module-level global must have been created.
        """
        import llm_cli.security.integrity as integrity_module

        with patch("llm_cli.clients.config.get_setting", return_value=None):
            mgr = ReasoningSentinelManager()

        mgr.process_chunk("hello world")

        # Score is on the instance
        assert mgr.current_score is not None
        assert isinstance(mgr.current_score, float)

        # No global side-effect
        assert not hasattr(integrity_module, "current_integrity_score")

    def test_get_sentinel_status_uses_instance_score(self):
        """get_sentinel_status() must read from self.current_score."""
        with patch("llm_cli.clients.config.get_setting", return_value=None):
            mgr = ReasoningSentinelManager()

        # Initial EMA loss is ~5.54. 
        # Thresholds will be y=5.94, r=6.74
        
        # Manually set a low score → should be green
        mgr.current_score = 1.0
        score, status = mgr.get_sentinel_status()
        assert score == 1.0
        assert status == "green"

        # Manually set a score above yellow but below red
        # (Based on initial EMA 5.54 + 0.4 = 5.94)
        mgr.current_score = 6.0
        score, status = mgr.get_sentinel_status()
        assert score == 6.0
        assert status == "yellow"

        # Manually set a high score above red
        # (Based on initial EMA 5.54 + 1.2 = 6.74)
        mgr.current_score = 7.0
        score, status = mgr.get_sentinel_status()
        assert score == 7.0
        assert status == "red"

    def test_tool_registry_wrapper_uses_injected_sentinel(self):
        """
        The tool_registry wrapper must read the integrity score from the
        injected __audit_sentinel__ instance, not from any module global.
        """
        # Build a minimal tool registration
        from llm_cli.modules.tool_registry import ToolRegistry

        reg = ToolRegistry()

        def my_tool(**kwargs):
            return "ok"

        reg.register(
            name="score_capture_tool",
            func=my_tool,
            description="Test tool",
        )

        # Create a fake sentinel with a known score
        fake_sentinel = MagicMock()
        fake_sentinel.current_score = 3.14

        # Patch log_audit to capture the reasoning_integrity_score argument
        with patch("llm_cli.modules.tool_registry.log_audit") as mock_log:
            reg.tools["score_capture_tool"]["func"](
                explanation="test",
                __audit_model__="test-model",
                __audit_sentinel__=fake_sentinel,
            )

        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        assert kwargs.get("reasoning_integrity_score") == 3.14, (
            "wrapper did not forward the sentinel's current_score to log_audit"
        )

    def test_tool_registry_wrapper_without_sentinel_passes_none(self):
        """
        When __audit_sentinel__ is not provided (e.g. in unit tests),
        reasoning_integrity_score must be None — not a crash.
        """
        from llm_cli.modules.tool_registry import ToolRegistry

        reg = ToolRegistry()

        def noop_tool(**kwargs):
            return "result"

        reg.register(name="noop", func=noop_tool, description="noop")

        with patch("llm_cli.modules.tool_registry.log_audit") as mock_log:
            reg.tools["noop"]["func"](
                explanation="no sentinel",
                __audit_model__="model",
                # __audit_sentinel__ intentionally omitted
            )

        _, kwargs = mock_log.call_args
        assert kwargs.get("reasoning_integrity_score") is None


# ===========================================================================
# 2. process_and_print decomposition
# ===========================================================================


class TestProcessAndPrintDecomposition:
    """Verify that the three extracted methods exist and behave correctly."""

    def test_methods_exist(self, session):
        """All three methods must be present on ChatSession."""
        assert callable(getattr(session, "_run_single_turn", None)), (
            "_run_single_turn is missing"
        )
        assert callable(getattr(session, "_process_tool_loop", None)), (
            "_process_tool_loop is missing"
        )
        assert callable(getattr(session, "process_and_print", None)), (
            "process_and_print is missing"
        )

    def test_run_single_turn_returns_tuple(self, session, mock_client):
        """
        _run_single_turn must return (response_text, duration) where
        response_text is a string and duration is a non-negative float.
        """
        mock_client._send = MagicMock(return_value=(("Hello!", None), {}))

        result = session._run_single_turn([])

        assert isinstance(result, tuple) and len(result) == 2, (
            "_run_single_turn must return a 2-tuple"
        )
        response_text, duration = result
        assert response_text == "Hello!"
        assert isinstance(duration, float) and duration >= 0.0

    def test_run_single_turn_none_response(self, session, mock_client):
        """When the API returns None, _run_single_turn must return (None, duration)."""
        mock_client._send = MagicMock(return_value=((None, None), {}))

        response_text, duration = session._run_single_turn([])

        assert response_text is None
        assert duration >= 0.0

    def test_process_tool_loop_no_pending_returns_none(self, session, mock_client):
        """
        When there are no pending tool calls, _process_tool_loop must return None
        to signal that the loop should stop.
        """
        mock_client._has_pending_tool_calls = MagicMock(return_value=False)

        result = session._process_tool_loop(duration=1.0)

        assert result is None, (
            "_process_tool_loop should return None when there are no tool calls"
        )

    def test_process_tool_loop_user_abort_returns_none(self, session, mock_client):
        """
        When the user denies a tool call (_execute_tool_call returns None / falsy),
        _process_tool_loop must return None to abort the ReAct loop.
        """
        mock_client._has_pending_tool_calls = MagicMock(return_value=True)

        # Inject a fake pending tool call into the conversation
        mock_client.conversation.append(
            Message(
                role=Role.MODEL,
                parts=[ContentPart(function_call={"name": "some_tool", "args": {}})],
            )
        )

        # Simulate user denying the tool call
        session._execute_tool_call = MagicMock(return_value=None)

        result = session._process_tool_loop(duration=1.0)

        assert result is None, (
            "_process_tool_loop should return None when user aborts a tool call"
        )

    def test_process_tool_loop_success_returns_list(self, session, mock_client):
        """
        When all tool calls succeed and there is no injected data,
        _process_tool_loop must return an empty list (not None).
        """
        mock_client._has_pending_tool_calls = MagicMock(return_value=True)

        # Inject a fake pending tool call
        mock_client.conversation.append(
            Message(
                role=Role.MODEL,
                parts=[ContentPart(function_call={"name": "ok_tool", "args": {}})],
            )
        )

        # Simulate successful tool execution with no injected data
        fake_result = ContentPart(
            function_response={
                "id": "t1",
                "name": "ok_tool",
                "response": {"result": "ok"},
            }
        )
        session._execute_tool_call = MagicMock(return_value=(fake_result, None))

        result = session._process_tool_loop(duration=0.5)

        assert isinstance(result, list), (
            "_process_tool_loop should return a list on success"
        )
        assert result == [], "Should be empty list when no injected data"

    def test_process_tool_loop_with_injected_data(self, session, mock_client):
        """
        When a tool returns injected data, _process_tool_loop must include it
        in the returned list so process_and_print can forward it as the next
        USER message.
        """
        mock_client._has_pending_tool_calls = MagicMock(return_value=True)

        mock_client.conversation.append(
            Message(
                role=Role.MODEL,
                parts=[ContentPart(function_call={"name": "data_tool", "args": {}})],
            )
        )

        injected = DataSource(content="file contents", content_type="text/plain")
        fake_result = ContentPart(
            function_response={
                "id": "t2",
                "name": "data_tool",
                "response": {"result": "ok"},
            }
        )
        session._execute_tool_call = MagicMock(return_value=(fake_result, injected))

        result = session._process_tool_loop(duration=0.5)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] is injected

    def test_process_and_print_delegates_to_helpers(self, session, mock_client):
        """
        process_and_print must call _run_single_turn and, when there are no
        pending tool calls, stop after the first turn.
        """
        mock_client._has_pending_tool_calls = MagicMock(return_value=False)

        with (
            patch.object(
                session, "_run_single_turn", return_value=("reply", 0.1)
            ) as mock_run,
            patch.object(
                session, "_process_tool_loop", return_value=None
            ) as mock_tool_loop,
            patch.object(session, "_log_chat"),
        ):
            session.process_and_print([])

        mock_run.assert_called_once()
        mock_tool_loop.assert_called_once()

    def test_process_and_print_loops_on_tool_calls(self, session, mock_client):
        """
        process_and_print must keep iterating as long as _process_tool_loop
        returns a list, and stop when it returns None.
        """
        # First turn has pending tool calls; second turn does not.
        mock_client._has_pending_tool_calls = MagicMock(
            side_effect=[True, True, False, False]
        )

        with (
            patch.object(
                session, "_run_single_turn", return_value=("reply", 0.1)
            ) as mock_run,
            patch.object(
                session,
                "_process_tool_loop",
                side_effect=[[], None],  # first iteration ok, second aborts
            ) as mock_tool_loop,
            patch.object(session, "_log_chat"),
        ):
            session.process_and_print([])

        assert mock_run.call_count == 2, "Expected two LLM round-trips"
        assert mock_tool_loop.call_count == 2, (
            "_process_tool_loop called twice (second call returns None → abort)"
        )
