from unittest.mock import MagicMock, patch

import pytest

import llm_cli.clients.tool_executor
from llm_cli.clients.tool_executor import (
    execute_tool_call,
    preview_command,
    preview_diff,
    preview_edit_diff,
)
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class MockSession:
    def __init__(self):
        self.client = MagicMock()
        self.client.conversation = []
        self.client.model = "test-model"
        self.client.get_display_name.return_value = "TestBot"
        self._print_block = MagicMock()
        self._get_input = MagicMock()


@pytest.fixture
def session():
    return MockSession()


def test_execute_tool_call_no_call(session):
    part = ContentPart()  # No function_call
    assert execute_tool_call(session, part) is None


def test_execute_tool_call_policy_violation(session):
    part = ContentPart(function_call={"name": "forbidden_tool", "args": {}})
    with patch("llm_cli.security.policy.policy_engine.evaluate", return_value=False):
        with patch("llm_cli.clients.base.console.print"):
            result = execute_tool_call(session, part)
            assert (
                "Policy Violation" in result[0].function_response["response"]["result"]
            )


def test_execute_tool_call_user_prompt_extraction(session):
    session.client.conversation = [
        Message(role=Role.USER, parts=[ContentPart(text="User instruction")]),
        Message(role=Role.MODEL, parts=["Assistant text"]),
    ]
    part = ContentPart(function_call={"name": "test_tool", "args": {}})
    with patch(
        "llm_cli.security.policy.policy_engine.evaluate", return_value=True
    ) as mock_eval:
        with patch(
            "llm_cli.modules.tool_registry.registry.tools",
            {"test_tool": {"skip_approval": True, "func": lambda **_: "ok"}},
        ):
            execute_tool_call(session, part)
            context = mock_eval.call_args[0][2]
            assert context["user_prompt"] == "User instruction"


def test_execute_tool_call_explanation_display(session):
    part = ContentPart(
        function_call={"name": "some_tool", "args": {"explanation": "I am doing this"}}
    )
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"some_tool": {"skip_approval": True, "func": lambda **_: "ok"}},
    ):
        execute_tool_call(session, part, duration=1.5)
        assert session._print_block.called


def test_execute_tool_call_denied_by_user(session):
    part = ContentPart(function_call={"name": "dangerous_tool", "args": {}})
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"dangerous_tool": {"skip_approval": False}},
    ):
        session._get_input.return_value = "n"
        result = execute_tool_call(session, part)
        assert "Operation denied" in result[0].function_response["response"]["result"]


def test_execute_tool_call_feedback_by_user(session):
    part = ContentPart(function_call={"name": "dangerous_tool", "args": {}})
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"dangerous_tool": {"skip_approval": False}},
    ):
        session._get_input.return_value = "Feedback"
        result = execute_tool_call(session, part)
        assert "Feedback: Feedback" in result[0].function_response["response"]["result"]


def test_execute_tool_call_not_found(session):
    part = ContentPart(function_call={"name": "missing_tool", "args": {}})
    # Approval phase (name not in registry.tools.get -> {})
    # skip_approval becomes False
    # Execution phase (name not in registry.tools -> raise ValueError)
    with patch("llm_cli.modules.tool_registry.registry.tools", {}):
        session._get_input.return_value = "y"
        result = execute_tool_call(session, part)
        assert "not found" in result[0].function_response["response"]["result"]


def test_execute_tool_call_interactive(session):
    part = ContentPart(function_call={"name": "interactive_tool", "args": {}})
    mock_func = MagicMock(return_value="interacted")
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {
            "interactive_tool": {
                "skip_approval": True,
                "interactive": True,
                "func": mock_func,
            }
        },
    ):
        execute_tool_call(session, part)
        mock_func.assert_called()


def test_execute_tool_call_injected_data(session):
    def mock_func(**kwargs):
        return {
            "result": "ok",
            "__llm_cli_data__": DataSource(content="c", content_type="t"),
        }

    part = ContentPart(function_call={"name": "inject_tool", "args": {}})
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"inject_tool": {"skip_approval": True, "func": mock_func}},
    ):
        result = execute_tool_call(session, part)
        assert result[1].content == "c"


def test_execute_tool_call_output_truncation(session):
    long_output = "A" * 100
    part = ContentPart(function_call={"name": "long_tool", "args": {}})
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {"long_tool": {"skip_approval": True, "func": lambda **_: long_output}},
    ):
        orig_get_setting = llm_cli.clients.tool_executor.get_setting

        def side_effect(key, section=None):
            if key == "max_output_length":
                return 10
            return orig_get_setting(key, section)

        with patch(
            "llm_cli.clients.tool_executor.get_setting", side_effect=side_effect
        ):
            result = execute_tool_call(session, part)
            assert "truncated" in result[0].function_response["response"]["result"]


def test_execute_tool_call_exec_output(session):
    part = ContentPart(
        function_call={"name": "execute_command", "args": {"command": "ls"}}
    )
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {
            "execute_command": {
                "skip_approval": True,
                "func": lambda **_: "file.txt",
            }
        },
    ):
        execute_tool_call(session, part)
        assert any(
            "Tool Output" in str(kwargs.get("title", ""))
            for _, kwargs in session._print_block.call_args_list
        )


def test_preview_diff_existing_file(session, tmp_path):
    file_path = tmp_path / "test.py"
    file_path.write_text("old content")
    preview_diff(session, {"path": str(file_path), "content": "new content"})
    assert session._print_block.called
    preview_diff(session, {})  # Coverage for not path or not new_content


def test_preview_diff_new_file(session, tmp_path):
    file_path = tmp_path / "new.py"
    preview_diff(session, {"path": str(file_path), "content": "c"})
    assert session._print_block.called


def test_preview_edit_diff(session):
    preview_edit_diff(session, {"path": "t.txt", "search": "s", "replace": "r"})
    assert session._print_block.called


def test_preview_command(session):
    preview_command(session, {"command": "ls"})
    assert session._print_block.called


def test_execute_tool_call_exception(session):
    part = ContentPart(function_call={"name": "buggy_tool", "args": {}})
    with patch(
        "llm_cli.modules.tool_registry.registry.tools",
        {
            "buggy_tool": {
                "skip_approval": True,
                "func": MagicMock(side_effect=Exception("Crash")),
            }
        },
    ):
        result = execute_tool_call(session, part)
        assert "Error: Crash" in result[0].function_response["response"]["result"]
