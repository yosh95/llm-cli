# llm_cli/clients/base_helpers.py

import base64
import datetime
import json
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax

from llm_cli.clients.config import config_manager
from llm_cli.ui import console

if TYPE_CHECKING:
    from rich.console import Console

    from llm_cli.clients.base import BaseLlmClient


def trim_log_file(console: "Console", path: Path, max_lines: int) -> None:
    try:
        if not path.exists():
            return

        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            with path.open("w", encoding="utf-8", errors="replace") as f:
                f.writelines(lines[-max_lines:])
    except Exception as e:
        console.print(f"[dim red]Log trimming failed: {e}[/dim red]")


def save_inline_media_and_get_log_entry(
    inline_data: dict[str, Any], hint_text: str = ""
) -> tuple[str | None, Path | None]:
    mime_type = inline_data.get("mimeType", "")
    if mime_type.startswith("image/"):
        from llm_cli.modules.media_utils import generate_safe_filename

        def _expand(p: str | None) -> str | None:
            return str(Path(p).expanduser()) if p else None

        image_save_path = (
            _expand(config_manager.get("general", "image_save_path")) or "."
        )

        save_dir = Path(image_save_path)
        default_ext = ".png"
        emoji = "🎨"
        type_name = "Image"

        save_dir.mkdir(parents=True, exist_ok=True)

        ext = mimetypes.guess_extension(mime_type) or default_ext
        filename = generate_safe_filename(hint_text, ext=ext.strip("."))
        target_path = save_dir / filename

        try:
            target_path.write_bytes(base64.b64decode(inline_data["data"]))
            msg = f"\n\n{emoji} {type_name} generated and saved to: **{target_path}**\n"
            return msg, target_path
        except Exception as e:
            console.print(f"[red]Failed to save {type_name.lower()}: {e}[/red]")
    return None, None


def log_debug(
    client: "BaseLlmClient",
    response_obj: requests.Response | None = None,
    request_payload: Any = None,
    response_content: Any = None,
) -> None:
    if not client.live_debug:
        return
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print_live_debug(timestamp, response_obj, request_payload, response_content)
    except Exception as e:
        console.print(f"[dim red]Live debug display failed: {e}[/dim red]")


def print_live_debug(
    timestamp: str,
    response_obj: requests.Response | None = None,
    request_payload: Any = None,
    response_content: Any = None,
) -> None:
    def _format_json(data: Any) -> str | Syntax:
        if isinstance(data, (dict, list)):
            try:
                return Syntax(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    "json",
                    theme="monokai",
                    background_color="default",
                    word_wrap=True,
                )
            except TypeError:
                pass
        return str(data)

    if response_obj:
        req_info: list[str | Syntax] = []
        title_req = f"[bold cyan]API Request ({timestamp})[/bold cyan]"
        if request_payload:
            req_info.append(_format_json(request_payload))
        elif hasattr(response_obj, "request"):
            req = response_obj.request
            req_info.append(f"[bold]URL:[/bold] {req.url}")
            if req.body:
                try:
                    b_str = (
                        req.body.decode("utf-8")
                        if isinstance(req.body, bytes)
                        else str(req.body)
                    )
                    req_info.append(_format_json(json.loads(b_str)))
                except Exception:
                    req_info.append(f"[dim]Raw Body:[/dim]\n{str(req.body)}")

        if req_info:
            console.print(
                Panel(
                    Group(*req_info), title=title_req, border_style="cyan", expand=False
                )
            )

        res_info: list[str | Syntax] = [
            f"[bold]Status:[/bold] {response_obj.status_code}"
        ]
        if response_content:
            res_info.append(_format_json(response_content))
        else:
            try:
                res_info.append(_format_json(response_obj.json()))
            except Exception:
                res_info.append(response_obj.text)

        title_res = f"[bold green]API Response ({timestamp})[/bold green]"
        console.print(
            Panel(Group(*res_info), title=title_res, border_style="green", expand=False)
        )
    else:
        if request_payload:
            title = f"[bold cyan]Payload Request ({timestamp})[/bold cyan]"
            console.print(
                Panel(
                    _format_json(request_payload),
                    title=title,
                    border_style="cyan",
                    expand=False,
                )
            )
        if response_content:
            title = f"[bold green]Payload Response ({timestamp})[/bold green]"
            console.print(
                Panel(
                    _format_json(response_content),
                    title=title,
                    border_style="green",
                    expand=False,
                )
            )


def report_error(provider_name: str, e: Exception) -> None:
    error_msg = str(e)
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        try:
            body_str = json.dumps(e.response.json(), indent=2, ensure_ascii=False)
            error_msg += f"\nResponse Body: {body_str}"
        except Exception:
            if e.response.text:
                error_msg += f"\nResponse Body: {e.response.text}"
    console.print(f"[bold red]{provider_name} Error: {error_msg}[/bold red]")
