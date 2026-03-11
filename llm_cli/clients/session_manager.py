# llm_cli/clients/session_manager.py

import json
from pathlib import Path
from typing import Any

from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class SessionManager:
    """
    Manages conversation history and session persistence (save/load).
    """

    def __init__(self) -> None:
        self.conversation: list[Message] = []

    def clear_history(self) -> None:
        """Clears the current conversation history."""
        self.conversation.clear()

    def update_history(self, data: list[DataSource], model_msg: Message) -> None:
        """
        Standard history update.
        Converts input data to USER messages and appends MODEL message.
        """
        user_parts: list[str | ContentPart] = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                inline_data = {"mimeType": d.content_type, "data": d.content}
                if "filename" in d.metadata:
                    inline_data["filename"] = d.metadata["filename"]
                user_parts.append(ContentPart(inline_data=inline_data))

        if user_parts:
            self.conversation.append(Message(role=Role.USER, parts=user_parts))
        self.conversation.append(model_msg)

    def load_session(self, path_str: str) -> tuple[bool, str]:
        """
        Loads a conversation session from a JSON file.
        Returns (success, message).
        """
        try:
            load_path = Path(path_str)
            if not load_path.exists():
                return False, f"File not found: {load_path}"

            with load_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Convert list of dicts back to list of Message objects
            loaded_conversation = []
            for msg_data in data:
                role = Role(msg_data["role"])
                parts: list[str | ContentPart] = []
                for p in msg_data["parts"]:
                    if isinstance(p, str):
                        parts.append(p)
                    elif isinstance(p, dict):
                        parts.append(ContentPart(**p))
                loaded_conversation.append(Message(role=role, parts=parts))

            self.clear_history()
            self.conversation = loaded_conversation
            msg = f"Session loaded from {load_path} ({len(self.conversation)} messages)"
            return True, msg
        except Exception as e:
            return False, f"Failed to load session: {e}"

    def save_session(self, path_str: str) -> tuple[bool, str]:
        """
        Saves the current conversation to a JSON file.
        Returns (success, message).
        """
        try:
            save_path = Path(path_str)
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert Message objects to serializable dicts
            serializable_conversation = []
            for msg in self.conversation:
                msg_dict: dict[str, Any] = {"role": str(msg.role), "parts": []}
                for part in msg.parts:
                    if isinstance(part, str):
                        msg_dict["parts"].append(part)
                    else:
                        # ContentPart as dict
                        import dataclasses

                        p_dict = dataclasses.asdict(part)
                        # Clean up None values
                        clean_part = {k: v for k, v in p_dict.items() if v is not None}
                        msg_dict["parts"].append(clean_part)
                serializable_conversation.append(msg_dict)

            with save_path.open("w", encoding="utf-8") as f:
                json.dump(serializable_conversation, f, indent=2, ensure_ascii=False)

            return True, f"Session saved to {save_path}"
        except Exception as e:
            return False, f"Failed to save session: {e}"

    def get_state(self) -> dict[str, Any]:
        """Returns the serializable state of the conversation."""
        import copy

        return {
            "conversation": copy.deepcopy(self.conversation),
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Restores the conversation state from a dictionary."""
        self.conversation = state.get("conversation", [])
