# llm_cli/clients/managers.py

from __future__ import annotations

import dataclasses
import json
import urllib.parse
from pathlib import Path
from typing import Any

from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.ui import console


class SessionManager:
    """Handles conversation history persistence (load/save)."""

    @staticmethod
    def load_session(path_str: str) -> tuple[list[Message] | None, str]:
        """Loads a conversation session from a JSON file."""
        try:
            load_path = Path(path_str)
            if not load_path.exists():
                return None, f"File not found: {load_path}"

            with load_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            loaded_conversation = []
            for msg_data in data:
                role = Role(msg_data["role"])
                parts = [
                    (ContentPart(**p) if isinstance(p, dict) else p) for p in msg_data["parts"]
                ]
                loaded_conversation.append(Message(role=role, parts=parts))

            msg = f"Session loaded from {load_path} ({len(loaded_conversation)} messages)"
            return loaded_conversation, msg
        except Exception as e:
            return None, f"Failed to load session: {e}"

    @staticmethod
    def save_session(path_str: str, conversation: list[Message]) -> tuple[bool, str]:
        """Saves the current conversation to a JSON file."""
        try:
            save_path = Path(path_str)
            save_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            serializable = []
            for msg in conversation:
                parts: list[Any] = []
                for part in msg.parts:
                    if isinstance(part, str):
                        parts.append(part)
                    else:
                        p_dict = dataclasses.asdict(part)
                        parts.append({k: v for k, v in p_dict.items() if v is not None})
                serializable.append({"role": str(msg.role), "parts": parts})

            with save_path.open("w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2, ensure_ascii=False)

            return True, f"Session saved to {save_path}"
        except Exception as e:
            return False, f"Failed to save session: {e}"


class MediaManager:
    """Handles processing of media sources (files, URLs, etc.)."""

    def __init__(self, pdf_as_base64: bool = False):
        self.pdf_as_base64 = pdf_as_base64

    def process_sources(self, sources: list[str]) -> list[DataSource]:
        return [processed for s in sources if (processed := self.process_single_source(s))]

    def process_single_source(self, source: str) -> DataSource | None:
        from llm_cli.modules import media_utils

        if source.startswith("http"):
            content, ctype = media_utils.fetch_url_content(source, self.pdf_as_base64)
            if content:
                filename = Path(urllib.parse.urlparse(source).path).name or "downloaded_file"
                return DataSource(
                    content=content,
                    content_type=ctype or "application/octet-stream",
                    is_file_or_url=True,
                    metadata={"filename": filename},
                )
            return None

        path = Path(source)
        if len(source) < 256 and path.exists() and path.is_file():
            res = media_utils.process_file(path, self.pdf_as_base64)
            if res:
                return DataSource(
                    content=res["content"],
                    content_type=res["content_type"],
                    is_file_or_url=True,
                    metadata={"filename": res.get("filename", path.name)},
                )
        return DataSource(content=source, content_type="text/plain")

    def save_inline_media(
        self, inline_data: dict[str, Any], hint_text: str = ""
    ) -> tuple[str | None, Path | None]:
        mime_type = inline_data.get("mimeType", "")
        if not mime_type.startswith("image/"):
            return None, None

        import base64
        import mimetypes

        from llm_cli.clients.config import config_manager
        from llm_cli.modules.media_utils import generate_safe_filename

        save_dir = Path(config_manager.get("general", "image_save_path") or ".").expanduser()
        save_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target_path = save_dir / generate_safe_filename(
            hint_text, ext=(mimetypes.guess_extension(mime_type) or ".png").strip(".")
        )

        try:
            data = inline_data["data"]
            missing_padding = len(data) % 4
            if missing_padding:
                data += "=" * (4 - missing_padding)
            target_path.write_bytes(base64.b64decode(data))
            return (
                f"\n\n[bold blue]IMAGE[/bold blue] Image generated and "
                f"saved to: **{target_path}**\n",
                target_path,
            )
        except Exception as e:
            console.print(f"[red]Failed to save image: {e}[/red]")
        return None, None
