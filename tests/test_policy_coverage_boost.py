import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.security.path_validator import PathValidationError
from llm_cli.security.policy import PolicyEngine


@pytest.fixture
def engine():
    return PolicyEngine()


def test_reinitialize_lazy():
    engine = PolicyEngine()
    engine.config = {}
    with patch.object(engine, "reinitialize") as mock_reinit:
        engine.evaluate("read_file_content", {"path": "t.md"}, {"roles": ["guest"]})
        mock_reinit.assert_called_once()


def test_reinitialize_and_role_merging(engine):
    custom_config = {
        "roles": {
            "user": {"allowed_tools": ["custom_tool"]},
            "new_role": {"allow_all": True},
        }
    }
    engine.reinitialize(custom_config)
    assert "custom_tool" in engine.roles["user"]["allowed_tools"]
    assert engine.roles["new_role"]["allow_all"] is True


def test_subject_overrides(engine, tmp_path):
    safe_path = tmp_path / "sandbox"

    config = {
        "subjects": {
            "blocked_user": {"denied_tools": ["read_file_content"]},
            "limited_user": {
                "allowed_tools": ["read_file_content"],
                "scopes": {
                    "read_file_content": {"allowed_paths": [str(safe_path / "*")]}
                },
            },
        }
    }
    engine.reinitialize(config)

    # Patch validate_path to just return the Path in absolute form
    with patch(
        "llm_cli.security.policy.validate_path", side_effect=lambda p: Path(p).resolve()
    ):
        # Allowed subpath
        assert (
            engine.evaluate(
                "read_file_content",
                {"path": str(safe_path / "f.txt")},
                {"user_id": "limited_user"},
            )
            is True
        )
        # Denied (out of scope)
        assert (
            engine.evaluate(
                "read_file_content",
                {"path": str(tmp_path / "other.txt")},
                {"user_id": "limited_user"},
            )
            is False
        )


def test_analyze_intent_no_prompt(engine):
    engine.config["intent_analyzer_enabled"] = True
    assert (
        engine.evaluate(
            "read_file_content",
            {"path": "t.md"},
            {"roles": ["guest"], "user_prompt": ""},
        )
        is True
    )


def test_analyze_intent_initialization_failure_and_fallbacks(engine):
    engine.config["intent_analyzer_enabled"] = True

    with patch(
        "llm_cli.security.intent_analyzer.IntentAnalyzer",
        side_effect=Exception("Failed to init"),
    ):
        # High risk tool
        assert (
            engine.evaluate(
                "edit_file",
                {"path": "t.txt"},
                {"roles": ["user"], "user_prompt": "edit"},
            )
            is False
        )

        engine.config["intent_analyzer_fail_open"] = True
        assert (
            engine.evaluate(
                "read_file_content",
                {"path": "t.md"},
                {"roles": ["guest"], "user_prompt": "read"},
            )
            is True
        )


def test_analyze_intent_blocked_by_analyzer(engine):
    engine.config["intent_analyzer_enabled"] = True
    mock_analyzer = MagicMock()
    mock_analyzer.verify_action.return_value = (False, "Malicious intent")
    engine.intent_analyzer = mock_analyzer
    assert (
        engine.evaluate(
            "read_file_content",
            {"path": "t.md"},
            {"roles": ["guest"], "user_prompt": "do it"},
        )
        is False
    )


def test_verify_scope_path_validation_error(engine):
    engine.roles["guest"]["scopes"]["read_file_content"] = {
        "allowed_paths": ["/allowed/*"]
    }
    with patch(
        "llm_cli.security.policy.validate_path",
        side_effect=PathValidationError("Invalid Path"),
    ):
        assert (
            engine.evaluate("read_file_content", {"path": "!!!"}, {"roles": ["guest"]})
            is False
        )


def test_verify_scope_complex_matching(engine, tmp_path):
    engine.roles["user"]["scopes"]["edit_file"] = {
        "allowed_paths": [str(tmp_path / "sandbox" / "*"), "*.md"]
    }

    with patch(
        "llm_cli.security.policy.validate_path", side_effect=lambda p: Path(p).resolve()
    ):
        os.chdir(tmp_path)
        assert (
            engine.evaluate(
                "edit_file", {"path": "sandbox/test.txt"}, {"roles": ["user"]}
            )
            is True
        )


def test_verify_scope_command_restriction(engine):
    engine.roles["user"]["allowed_tools"].append("execute_command")
    engine.roles["user"]["scopes"]["execute_command"] = {
        "allowed_commands": [r"^ls", r"grep"]
    }
    assert (
        engine.evaluate("execute_command", {"command": "ls -la"}, {"roles": ["user"]})
        is True
    )
    assert (
        engine.evaluate("execute_command", {"command": "rm -rf /"}, {"roles": ["user"]})
        is False
    )


def test_global_guardrails_traversal(engine):
    assert (
        engine.evaluate(
            "read_file_content", {"path": "../secret.txt"}, {"roles": ["admin"]}
        )
        is False
    )


def test_global_guardrails_blocked_paths(engine, tmp_path):
    blocked = tmp_path / "blocked"
    engine.config["blocked_paths"] = [str(blocked)]
    assert (
        engine.evaluate(
            "read_file_content",
            {"path": str(blocked / "file.txt")},
            {"roles": ["admin"]},
        )
        is False
    )


def test_evaluate_role_not_found(engine):
    assert (
        engine.evaluate(
            "read_file_content", {"path": "t.md"}, {"roles": ["non_existent_role"]}
        )
        is False
    )


def test_analyze_intent_success(engine):
    engine.config["intent_analyzer_enabled"] = True
    mock_analyzer = MagicMock()
    mock_analyzer.verify_action.return_value = (True, "Fine")
    engine.intent_analyzer = mock_analyzer
    assert (
        engine.evaluate(
            "read_file_content",
            {"path": "t.md"},
            {"roles": ["guest"], "user_prompt": "read"},
        )
        is True
    )
