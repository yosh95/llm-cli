"""Tests for BaseLlmClient slash commands and extra functionality."""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.clients.base import (
    BaseLlmClient,
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class ConcreteClient(BaseLlmClient):
    """Concrete implementation for testing."""

    def _load_model_aliases(self) -> None:
        self.available_models = {
            "default": "test-model",
            "gpt-4": "gpt-4-turbo",
        }

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


class TestBaseClientCommands:
    """Tests for _handle_command in BaseLlmClient."""

    def test_not_a_command(self, client: BaseLlmClient) -> None:
        """Test that normal text is not handled as a command."""
        assert client._handle_command("hello", None) is False

    # --- /model ---
    def test_model_list(self, client: BaseLlmClient) -> None:
        """Test listing models."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/model", None) is True
            mock_print.assert_any_call("[bold]Available Models:[/bold]")
            # Check if models are printed in any of the subsequent calls
            printed_output = "".join(
                [str(call.args[0]) for call in mock_print.call_args_list]
            )
            assert "default" in printed_output
            assert "gpt-4" in printed_output

    def test_model_switch_success(self, client: BaseLlmClient) -> None:
        """Test switching to an existing model."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/m gpt-4", None) is True
            assert client.current_alias == "gpt-4"
            assert client.model == "gpt-4-turbo"
            mock_print.assert_called_with(
                "[cyan]Model switched to: gpt-4 (gpt-4-turbo)[/cyan]"
            )

    def test_model_switch_custom(self, client: BaseLlmClient) -> None:
        """Test switching to a custom model."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/m my-custom-model", None) is True
            assert client.current_alias == "custom"
            assert client.model == "my-custom-model"
            mock_print.assert_called_with(
                "[yellow]Custom model set: my-custom-model (not in config)[/yellow]"
            )

    # --- /template ---
    def test_template_list(self, client: BaseLlmClient) -> None:
        """Test listing templates."""
        with patch("llm_cli.clients.base.get_templates") as mock_get_templates:
            mock_get_templates.return_value = {"t1": "Template 1", "t2": "Template 2"}
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command("/template", None) is True
                mock_print.assert_any_call("[bold]Available Templates:[/bold]")

    def test_template_select_preview(self, client: BaseLlmClient) -> None:
        """Test selecting a template just for preview (no pending data)."""
        with patch("llm_cli.clients.base.get_templates") as mock_get_templates:
            mock_get_templates.return_value = {"t1": "Template content"}
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command("/t t1", None) is True
                args, _ = mock_print.call_args_list[0]
                assert "Selected template 't1':" in args[0]

    def test_template_select_load(self, client: BaseLlmClient) -> None:
        """Test selecting a template to load into input buffer."""
        with patch("llm_cli.clients.base.get_templates") as mock_get_templates:
            mock_get_templates.return_value = {"t1": "Template content"}
            pending_data: list[DataSource] = []
            with pytest.raises(TemplateRequest) as excinfo:
                client._handle_command("/t t1", None, pending_data=pending_data)
            assert excinfo.value.text == "Template content"

    def test_template_not_found(self, client: BaseLlmClient) -> None:
        """Test selecting a non-existent template."""
        with patch("llm_cli.clients.base.get_templates") as mock_get_templates:
            mock_get_templates.return_value = {}
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command("/t nonexist", None) is True
                mock_print.assert_called_with("[red]Template not found: nonexist[/red]")

    # --- /checkpoint ---
    def test_checkpoint(self, client: BaseLlmClient) -> None:
        """Test checkpoint command raises CheckpointRequest."""
        with pytest.raises(CheckpointRequest):
            client._handle_command("/checkpoint", None)
        with pytest.raises(CheckpointRequest):
            client._handle_command("/cp", None)

    # --- /save ---
    def test_save_with_arg(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test saving session with filename provided as argument."""
        client.conversation = [Message(role=Role.USER, parts=["Hi"])]
        save_file = tmp_path / "test_session.json"

        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command(f"/save {save_file}", None) is True
            assert save_file.exists()
            mock_print.assert_called_with(
                f"[green]Session saved to {save_file}[/green]"
            )

        with save_file.open() as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["role"] == "user"

    def test_save_prompt(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test saving session prompting for filename."""
        client.conversation = [Message(role=Role.USER, parts=["Hi"])]
        save_file = tmp_path / "prompt_session.json"

        with patch("llm_cli.clients.base.prompt") as mock_prompt:
            mock_prompt.return_value = str(save_file)
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command("/save", None) is True
                assert save_file.exists()
                mock_print.assert_called_with(
                    f"[green]Session saved to {save_file}[/green]"
                )

    def test_save_cancel(self, client: BaseLlmClient) -> None:
        """Test cancelling save at prompt."""
        with patch("llm_cli.clients.base.prompt") as mock_prompt:
            mock_prompt.side_effect = KeyboardInterrupt
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command("/save", None) is True
                mock_print.assert_called_with("[yellow]Save cancelled.[/yellow]")

    def test_save_existing_overwrite(
        self, client: BaseLlmClient, tmp_path: Path
    ) -> None:
        """Test overwriting existing file."""
        save_file = tmp_path / "exists.json"
        save_file.touch()

        with patch("llm_cli.clients.base.Confirm.ask") as mock_confirm:
            mock_confirm.return_value = True
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command(f"/save {save_file}", None) is True
                mock_print.assert_called_with(
                    f"[green]Session saved to {save_file}[/green]"
                )

    def test_save_existing_cancel(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test cancelling overwrite of existing file."""
        save_file = tmp_path / "exists.json"
        save_file.touch()

        with patch("llm_cli.clients.base.Confirm.ask") as mock_confirm:
            mock_confirm.return_value = False
            with patch("llm_cli.clients.base.console.print") as mock_print:
                assert client._handle_command(f"/save {save_file}", None) is True
                mock_print.assert_called_with("[yellow]Save cancelled.[/yellow]")

    # --- /load ---
    def test_load_command(self, client: BaseLlmClient) -> None:
        """Test load command delegates to load_session."""
        with patch.object(client, "load_session") as mock_load:
            assert client._handle_command("/load my_session.json", None) is True
            mock_load.assert_called_with("my_session.json")

    def test_load_no_args(self, client: BaseLlmClient) -> None:
        """Test load command without arguments."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/load", None) is True
            mock_print.assert_called_with("[red]Usage: /load <path>[/red]")

    # --- /attach ---
    def test_attach_file(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test attaching a file."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        pending_data: list[DataSource] = []

        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command(f"/attach {f}", None, pending_data) is True
            assert len(pending_data) == 1
            assert pending_data[0].content == "content"
            assert "Added as text context" in mock_print.call_args[0][0]

    def test_attach_fail(self, client: BaseLlmClient) -> None:
        """Test attaching non-existent file."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/attach nonexist.txt", None) is True
            assert "Failed to attach" in mock_print.call_args[0][0]

    def test_attach_no_args(self, client: BaseLlmClient) -> None:
        """Test attach without arguments."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/attach", None) is True
            mock_print.assert_called_with("[red]Usage: /attach <path>[/red]")

    # --- /dump ---
    def test_dump(self, client: BaseLlmClient) -> None:
        """Test dump command."""
        client.conversation = [Message(role=Role.USER, parts=["Hi"])]
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/dump", None) is True
            # Should print conversation panel
            assert mock_print.called

    def test_dump_pending(self, client: BaseLlmClient) -> None:
        """Test dump command with pending data."""
        pending_data = [DataSource(content="test", content_type="text/plain")]
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/dump", None, pending_data) is True
            # Should print conversation and pending data panels
            assert mock_print.call_count >= 2

    # --- /raw ---
    def test_raw(self, client: BaseLlmClient, capsys: pytest.CaptureFixture) -> None:
        """Test raw command output."""
        client.conversation = [
            Message(role=Role.USER, parts=["Hi"]),
            Message(
                role=Role.MODEL, parts=[ContentPart(text="Hello", thought="Thinking")]
            ),
        ]
        assert client._handle_command("/raw", None) is True
        captured = capsys.readouterr()
        assert "[USER]" in captured.out
        assert "Hi" in captured.out
        assert "[MODEL (REASONING)]" in captured.out
        assert "Thinking" in captured.out
        # Note: Depending on implementation, text might also be printed separately if parts are iterated.
        # In base.py:
        # if p.thought: role_suffix=" (REASONING)"; text=p.thought
        # elif p.text: text=p.text
        # So "Hello" might be skipped if it's in the same ContentPart?
        # Let's check ContentPart structure.
        # Usually 'thought' and 'text' are separate parts or separate fields?
        # base.py logic: if p.thought ... elif p.text ...
        # If one ContentPart has both, only thought is printed?
        # Let's verify with separate parts to be safe if that's the intention,
        # or just check what is printed.

    # --- /clear ---
    def test_clear(self, client: BaseLlmClient) -> None:
        """Test clear command."""
        client.conversation = [Message(role=Role.USER, parts=["Hi"])]
        client.cumulative_total_tokens = 100
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/clear", None) is True
            assert len(client.conversation) == 0
            assert client.cumulative_total_tokens == 0
            mock_print.assert_called_with(
                "[yellow]Conversation history cleared.[/yellow]"
            )

    # --- /quit ---
    def test_quit(self, client: BaseLlmClient) -> None:
        """Test quit command raises ExitRequest."""
        with pytest.raises(ExitRequest):
            client._handle_command("/quit", None)
        with pytest.raises(ExitRequest):
            client._handle_command("/q", None)

    # --- /tools ---
    def test_tools_on_off(self, client: BaseLlmClient) -> None:
        """Test tools toggling."""
        assert client._handle_command("/tools off", None) is True
        assert client.tools_enabled is False
        assert client._handle_command("/tools on", None) is True
        assert client.tools_enabled is True

    def test_tools_status(self, client: BaseLlmClient) -> None:
        """Test tools status display."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/tools", None) is True
            # Should print status
            assert mock_print.called

    def test_tools_invalid(self, client: BaseLlmClient) -> None:
        """Test tools with invalid arg."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/tools invalid", None) is True
            mock_print.assert_called_with(
                "[red]Error: Invalid argument 'invalid'. Usage: /tools on|off[/red]"
            )

    # --- /debug ---
    def test_debug(self, client: BaseLlmClient) -> None:
        """Test debug toggle."""
        client.live_debug = False
        assert client._handle_command("/debug", None) is True
        assert client.live_debug is True
        assert client._handle_command("/d", None) is True
        assert client.live_debug is False

    # --- /info ---
    def test_info(self, client: BaseLlmClient) -> None:
        """Test info command."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/info", None) is True
            assert mock_print.called

    # --- /help ---
    def test_help(self, client: BaseLlmClient) -> None:
        """Test help command."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            assert client._handle_command("/help", None) is True
            assert mock_print.called


class TestBaseClientMedia:
    """Tests for media handling in BaseLlmClient."""

    def test_save_inline_image(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test saving an inline image."""
        # Mock setting to use tmp_path
        with patch("llm_cli.clients.base.get_setting") as mock_setting:
            # When image_save_path is requested
            def get_setting_side_effect(key, section):
                if key == "image_save_path":
                    return str(tmp_path)
                return None

            mock_setting.side_effect = get_setting_side_effect

            data = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"  # 1x1 GIF
            inline_data = {"mimeType": "image/gif", "data": data}

            msg, saved_path = client._save_inline_media_and_get_log_entry(
                inline_data, "hint"
            )

            assert saved_path is not None
            assert saved_path.exists()
            assert msg is not None
            assert "Image generated and saved to" in msg

    def test_save_inline_audio_wav(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test saving PCM audio as WAV."""
        with patch("llm_cli.clients.base.get_setting") as mock_setting:

            def get_setting_side_effect(key, section):
                if key == "audio_save_path":
                    return str(tmp_path)
                return None

            mock_setting.side_effect = get_setting_side_effect

            # 4 bytes of data (1 sample, stereo, 16bit? or similar)
            inline_data = {
                "mimeType": "audio/l16;rate=24000",
                "data": base64.b64encode(b"\x00\x00\x00\x00").decode(),
            }

            import wave

            msg, saved_path = client._save_inline_media_and_get_log_entry(
                inline_data, "audio_hint"
            )

            assert saved_path is not None
            assert saved_path.exists()
            assert saved_path.suffix == ".wav"
            assert msg is not None
            assert "Audio generated and saved to" in msg

            # Verify it is a valid wav
            with wave.open(str(saved_path), "rb") as w:
                assert w.getframerate() == 24000

    def test_save_inline_audio_mp3(self, client: BaseLlmClient, tmp_path: Path) -> None:
        """Test saving MP3 audio."""
        with patch("llm_cli.clients.base.get_setting") as mock_setting:

            def get_setting_side_effect(key, section):
                if key == "audio_save_path":
                    return str(tmp_path)
                return None

            mock_setting.side_effect = get_setting_side_effect

            inline_data = {
                "mimeType": "audio/mp3",
                "data": base64.b64encode(b"dummy").decode(),
            }

            msg, saved_path = client._save_inline_media_and_get_log_entry(
                inline_data, "audio_hint"
            )

            assert saved_path is not None
            assert saved_path.exists()
            assert saved_path.suffix == ".mp3"

    def test_save_media_fail(self, client: BaseLlmClient) -> None:
        """Test media saving failure handling."""
        inline_data = {"mimeType": "image/png", "data": "invalid_base64"}

        with patch("llm_cli.clients.base.console.print") as mock_print:
            msg, saved_path = client._save_inline_media_and_get_log_entry(inline_data)
            assert msg is None
            assert saved_path is None
            mock_print.assert_called()  # Should print error
            assert "Failed to save" in mock_print.call_args[0][0]

    def test_save_unknown_mime(self, client: BaseLlmClient) -> None:
        """Test handling of unknown mime type."""
        inline_data = {"mimeType": "application/x-unknown", "data": "..."}
        msg, saved_path = client._save_inline_media_and_get_log_entry(inline_data)
        assert msg is None
        assert saved_path is None


class TestBaseClientDebug:
    """Tests for debug logging."""

    def test_log_debug_off(self, client: BaseLlmClient) -> None:
        """Test logging when debug is off."""
        client.live_debug = False
        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._log_debug(response_content={"a": 1})
            mock_print.assert_not_called()

    def test_log_debug_response(self, client: BaseLlmClient) -> None:
        """Test logging a response."""
        client.live_debug = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "value"}
        mock_resp.request.url = "http://test.com"
        mock_resp.request.body = b'{"req": 1}'

        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._log_debug(response_obj=mock_resp)
            assert mock_print.called

    def test_log_debug_payload(self, client: BaseLlmClient) -> None:
        """Test logging payload only."""
        client.live_debug = True
        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._log_debug(request_payload={"req": 1}, response_content={"res": 2})
            assert mock_print.called

    def test_log_debug_error(self, client: BaseLlmClient) -> None:
        """Test that errors in debug logging don't crash."""
        client.live_debug = True
        # Passing an object that causes serialization error if not handled

        with patch("llm_cli.clients.base.console.print") as mock_print:
            # We want to trigger the exception in _print_live_debug or _format_json
            # _format_json handles TypeError, but let's try to trigger the outer try/except
            # Maybe passing something that fails str()?

            # Actually _log_debug calls _print_live_debug inside a try/except.
            # Let's mock _print_live_debug to raise exception
            with patch.object(
                client, "_print_live_debug", side_effect=Exception("Boom")
            ):
                client._log_debug(response_content={})
                mock_print.assert_called()
                assert "Live debug display failed" in mock_print.call_args[0][0]

    def test_report_error(self, client: BaseLlmClient) -> None:
        """Test error reporting."""
        with patch("llm_cli.clients.base.console.print") as mock_print:
            client._report_error("TestProvider", Exception("Something went wrong"))
            mock_print.assert_called()
            assert (
                "TestProvider Error: Something went wrong" in mock_print.call_args[0][0]
            )
