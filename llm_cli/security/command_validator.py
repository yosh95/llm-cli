# llm_cli/security/command_validator.py

import re
import shlex

from llm_cli.clients.config import _load_config_from_file
from llm_cli.security.path_validator import PathValidationError, validate_path


class CommandValidationError(Exception):
    """Raised when a command fails security validation."""

    pass


class CommandValidator:
    """
    Validates shell commands against a whitelist of allowed commands.
    Provides protection against command injection and dangerous operations.
    """

    DEFAULT_WHITELIST = {
        "cal",
        "cat",
        "column",
        "cut",
        "date",
        "df",
        "diff",
        "du",
        "echo",
        "egrep",
        "fgrep",
        "file",
        "find",
        "fold",
        "grep",
        "head",
        "jq",
        "less",
        "locate",
        "ls",
        "md5sum",
        "more",
        "pwd",
        "sha256sum",
        "sleep",
        "sort",
        "stat",
        "tail",
        "tr",
        "tree",
        "type",
        "uniq",
        "wc",
        "whereis",
        "which",
        "yq",
    }

    CHAINING_OPERATORS = {"&&", "||", "|"}

    def __init__(
        self,
        custom_whitelist: set[str] | None = None,
        allow_dangerous_patterns: bool = False,
    ):
        self.whitelist = self.DEFAULT_WHITELIST.copy()

        if custom_whitelist:
            self.whitelist.update(custom_whitelist)

        self.allow_dangerous_patterns = allow_dangerous_patterns
        self.chaining_operators = self.CHAINING_OPERATORS.copy()
        if self.allow_dangerous_patterns:
            self.chaining_operators.add(";")

        # Load security config once
        config = _load_config_from_file()
        self.security_config = config.get("security", {})

    def validate(self, command: str) -> None:
        if not command or not command.strip():
            raise CommandValidationError("Empty command not allowed")

        if not self.allow_dangerous_patterns:
            self._check_dangerous_patterns(command)

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            raise CommandValidationError(f"Failed to parse command: {e}") from e

        if not tokens:
            raise CommandValidationError("No command found after parsing")

        current_segment: list[str] = []
        for token in tokens:
            if token in self.chaining_operators:
                if current_segment:
                    self._validate_parts(current_segment)
                    current_segment = []
            elif token == "&":
                if not self.allow_dangerous_patterns:
                    raise CommandValidationError(
                        "Single '&' for background execution is forbidden."
                    )
                current_segment.append(token)
            else:
                current_segment.append(token)

        if current_segment:
            self._validate_parts(current_segment)

    def _validate_parts(self, parts: list[str]) -> None:
        if not parts:
            return

        # Ensure tokens are clean of leading/trailing whitespace/newlines
        # that might have survived from line continuations.
        parts = [p.strip() for p in parts]

        self._check_paths(parts)

        base_command = parts[0]
        if "/" in base_command:
            base_command = base_command.split("/")[-1]

        if base_command not in self.whitelist:
            raise CommandValidationError(
                f"Command '{base_command}' is not in the allowed whitelist."
            )

    def _check_dangerous_patterns(self, command: str) -> None:
        # 1. Mask single-quoted strings (Always safe zones)
        # Shells do not expand variables or subshells inside single quotes.
        masked_command = re.sub(r"'(?:[^'\\]|\\.)*'", "''", command)

        # 2. Check for ALWAYS_DANGEROUS patterns
        # These function even inside double quotes.
        # - Backticks: `cmd`
        # - Command substitution: $(cmd)
        # - Variable expansion: ${VAR} (Detecting this prevents env exfiltration)
        always_dangerous = [r"`", r"\$\(", r"\$\{"]
        for pattern in always_dangerous:
            if re.search(pattern, masked_command):
                readable = pattern.replace("\\", "")
                raise CommandValidationError(
                    f"Command contains dangerous pattern '{readable}' "
                    "(Substitution/Expansion). If you need to use these "
                    "characters literally, please use single quotes."
                )

        # 3. Mask double-quoted strings
        # Now that we've checked for injections, we can treat double-quoted sections
        # as safe from shell meta-characters like ; and \n.
        masked_command = re.sub(r'"(?:[^"\\]|\\.)*"', '""', masked_command)

        # 4. Check for SHELL_META patterns
        # These are dangerous only when unquoted.
        shell_meta = [r";", r"\n"]
        for pattern in shell_meta:
            if re.search(pattern, masked_command):
                readable = "\\n (Newline)" if pattern == r"\n" else pattern
                raise CommandValidationError(
                    f"Command contains dangerous pattern '{readable}'."
                )

        if re.search(r"[<>]", masked_command):
            raise CommandValidationError("I/O redirection (> or <) is forbidden.")

    def _check_paths(self, parts: list[str]) -> None:
        base_command = parts[0]
        if "/" in base_command:
            base_command = base_command.split("/")[-1]

        for part in parts[1:]:
            # More careful path check: only validate if it really looks like a path
            if "/" in part or part.startswith(".") or part.startswith("~"):
                if part == "...":  # Common placeholder in tests/prompts
                    continue
                try:
                    validate_path(part)
                except PathValidationError as e:
                    # Exception handling logic for grep-like commands
                    if base_command in {"grep", "egrep", "fgrep", "find", "locate"}:
                        # If the path doesn't exist, it might be a pattern or
                        # search query. For these read-only/search commands, we
                        # allow non-existent paths because they won't lead to
                        # unauthorized file access (file not found).
                        from pathlib import Path

                        expanded_path = Path(part).expanduser()
                        if not expanded_path.exists():
                            continue

                    # Bubble up the specific traversal error message
                    raise CommandValidationError(str(e)) from e


def validate_command(command: str, custom_whitelist: set[str] | None = None) -> None:
    config = _load_config_from_file()
    security_config = config.get("security", {})
    config_whitelist = set(security_config.get("allowed_commands", []))
    if custom_whitelist:
        config_whitelist.update(custom_whitelist)

    allow_dangerous = security_config.get("allow_dangerous_patterns", False)
    validator = CommandValidator(
        custom_whitelist=config_whitelist if config_whitelist else None,
        allow_dangerous_patterns=allow_dangerous,
    )
    validator.validate(command)
