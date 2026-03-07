import runpy
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.unified import UnifiedClient, main


def test_unified_no_default_provider():
    with patch("llm_cli.apps.unified.get_setting", return_value=None):
        with patch("llm_cli.clients.base.console.print") as mock_print:
            with pytest.raises(SystemExit) as excinfo:
                # We need to make sure initial_provider is also None
                UnifiedClient(initial_provider=None)
            assert excinfo.value.code == 1
            mock_print.assert_called()


def test_unified_getattr_error():
    # To trigger line 54, we need active_client to NOT be in __dict__
    class BrokenUnified(UnifiedClient):
        def __init__(self):
            self.clients = {}
            # Do NOT call super().__init__ which sets active_client

    u = BrokenUnified()
    with pytest.raises(AttributeError) as excinfo:
        _ = u.non_existent_attr
    assert "BrokenUnified" in str(excinfo.value)


def test_unified_import_error_handling():
    # Trigger line 116-127
    u = UnifiedClient(initial_provider="google")

    # torch/tiktoken hint case
    with patch(
        "llm_cli.clients.registry.client_registry.get_client_class",
        side_effect=ImportError("No module named 'torch'"),
    ):
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert u._activate_provider("mamba") is False
            any_hint = any(
                "pip install torch" in str(args)
                for args, kwargs in mock_print.call_args_list
            )
            assert any_hint

    # Generic ImportError case
    with patch(
        "llm_cli.clients.registry.client_registry.get_client_class",
        side_effect=ImportError("Some other import error"),
    ):
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert u._activate_provider("other") is False
            any_error = any(
                "Error loading provider" in str(args)
                for args, kwargs in mock_print.call_args_list
            )
            assert any_error


def test_unified_delegations():
    u = UnifiedClient(initial_provider="google")
    u.active_client = MagicMock()

    u.clear_history()
    u.active_client.clear_history.assert_called_once()

    u.get_conversation_state()
    u.active_client.get_conversation_state.assert_called_once()

    u.set_conversation_state({"test": 1})
    u.active_client.set_conversation_state.assert_called_with({"test": 1})


def test_unified_handle_command_branches():
    u = UnifiedClient(initial_provider="google")
    # Line 185: Not a command (doesn't start with /)
    assert u._handle_command("hello", None) is False

    # Line 210-213: Unknown provider
    with patch("llm_cli.clients.base.console.print") as mock_print:
        # _activate_provider returning False
        with patch.object(u, "_activate_provider", return_value=False):
            u._handle_command("/p unknown_provider", None)
            any_unknown = any(
                "Unknown or unavailable provider" in str(args)
                for args, kwargs in mock_print.call_args_list
            )
            assert any_unknown


def test_unified_main_execution():
    with patch("llm_cli.apps.unified.run_client_cli") as mock_run:
        main()
        mock_run.assert_called_once()


def test_unified_module_main():
    with patch("sys.argv", ["llm-cli", "--help"]):
        try:
            runpy.run_module("llm_cli.apps.unified", run_name="__main__")
        except SystemExit:
            pass


def test_unified_properties():
    u = UnifiedClient(initial_provider="google")
    u.active_client = MagicMock()

    u.active_client.available_models = {"m1": "desc1"}
    assert u.available_models == {"m1": "desc1"}

    u.available_models = {"m2": "desc2"}
    u.active_client.available_models = {
        "m2": "desc2"
    }  # property setter should have called this

    u.set_custom_model("custom")
    u.active_client.set_custom_model.assert_called_with("custom")

    u._process_single_source("source")
    u.active_client._process_single_source.assert_called_with("source")


def test_unified_activate_provider_no_class():
    u = UnifiedClient(initial_provider="google")
    with patch(
        "llm_cli.clients.registry.client_registry.get_client_class", return_value=None
    ):
        assert u._activate_provider("unknown") is False


def test_unified_handle_command_super_delegation():
    u = UnifiedClient(initial_provider="google")
    with patch(
        "llm_cli.clients.base.BaseLlmClient._handle_command", return_value=True
    ) as mock_super:
        assert u._handle_command("/help", None) is True
        mock_super.assert_called()


def test_unified_send_syncs_state():
    u = UnifiedClient(initial_provider="google")
    u.active_client = MagicMock()
    u.active_tools = ["tool1"]
    u.conversation = [{"role": "user", "content": "hi"}]
    u.live_debug = True
    u.tools_enabled = False

    # Mocking _send return
    u.active_client._send.return_value = (("out", "reason"), {})

    u._send([])

    assert u.active_client.active_tools == ["tool1"]
    assert u.active_client.conversation == u.conversation
    assert u.active_client.live_debug is True
    assert u.active_client.tools_enabled is False
