# llm_cli/security/command_validator.py

import re
import shlex
from typing import List, Optional, Set

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
        "git",
        "grep",
        "head",
        "jq",
        "less",
        "locate",
        "ls",
        "md5sum",
        "more",
        "mypy",
        "pwd",
        "pytest",
        "python",
        "python3",
        "ruff",
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

    DANGEROUS_PATTERNS = [
        r";",
        r"`",
        r"\$\(",
        r"\$\{",
        r"\n",
    ]

    CHAINING_OPERATORS = {"&&", "||", "|"}

    def __init__(
        self,
        custom_whitelist: Optional[Set[str]] = None,
        allow_dangerous_patterns: bool = False,
    ):
        self.whitelist = self.DEFAULT_WHITELIST.copy()

        if custom_whitelist:
            self.whitelist.update(custom_whitelist)

        self.allow_dangerous_patterns = allow_dangerous_patterns

    def validate(self, command: str) -> None:
        if not command or not command.strip():
            raise CommandValidationError("Empty command not allowed")

        # 1. Pre-parsing checks for Python one-liners to provide better feedback
        self._check_python_oneliner_pre_parse(command)

        # 2. Dangerous pattern check
        if not self.allow_dangerous_patterns:
            self._check_dangerous_patterns(command)

        # 3. Parsing
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            raise CommandValidationError(f"Failed to parse command: {e}")

        if not tokens:
            raise CommandValidationError("No command found after parsing")

        current_segment: list[str] = []
        for token in tokens:
            if token in self.CHAINING_OPERATORS:
                if current_segment:
                    self._validate_parts(current_segment)
                    current_segment = []
            elif token == "&":
                raise CommandValidationError(
                    "Single '&' for background execution is forbidden."
                )
            else:
                current_segment.append(token)

        if current_segment:
            self._validate_parts(current_segment)

    def _check_python_oneliner_pre_parse(self, command: str) -> None:
        """Specifically check for python -c one-liners before other pattern checks."""
        # This regex looks for 'python' or 'python3' followed by one-liner flags
        # even if they are followed by other characters or semicolon.
        pattern = r"\bpython3?\b.*?\s(-c|-m|--code|--module)\b"
        if re.search(pattern, command):
            raise CommandValidationError(
                "Python one-liners (using -c or -m) are prohibited for security. "
                "Please write the code to a temporary file using 'write_file' "
                "and then execute it (e.g., 'python3 your_file.py')."
            )

    def _validate_parts(self, parts: List[str]) -> None:
        if not parts:
            return

        self._check_paths(parts)

        base_command = parts[0]
        if "/" in base_command:
            base_command = base_command.split("/")[-1]

        if base_command not in self.whitelist:
            raise CommandValidationError(
                f"Command '{base_command}' is not in the allowed whitelist."
            )

        self._check_dangerous_arguments(base_command, parts)

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

    def _check_paths(self, parts: List[str]) -> None:
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
                        import os

                        expanded_path = os.path.expanduser(part)
                        if not os.path.exists(expanded_path):
                            continue

                    # Bubble up the specific traversal error message
                    raise CommandValidationError(str(e))

    def _check_dangerous_arguments(self, base_command: str, parts: List[str]) -> None:
        config = _load_config_from_file()
        security_config = config.get("security", {})

        if base_command == "git":
            strictly_forbidden = {
                "push",
                "remote",
                "alias",
                "apply",
                "credential",
                "config",
                "clone",
                "fetch",
                "pull",
                "submodule",
            }
            default_allowed = {
                "status",
                "diff",
                "log",
                "show",
                "add",
                "commit",
                "branch",
                "tag",
                "rev-parse",
            }
            user_allowed = set(security_config.get("allowed_git_subcommands", []))
            allowed_subcommands = default_allowed.union(user_allowed)

            if len(parts) > 1:
                subcommand = parts[1]
                if subcommand in strictly_forbidden:
                    raise CommandValidationError(
                        f"Git subcommand '{subcommand}' is strictly forbidden."
                    )
                if subcommand not in allowed_subcommands:
                    raise CommandValidationError(
                        f"Git subcommand '{subcommand}' is not allowed."
                    )

                if subcommand == "add":
                    forbidden_add_args = {
                        ".",
                        "*",
                        ":",
                        "-A",
                        "--all",
                        "-u",
                        "--update",
                    }
                    for arg in parts[2:]:
                        if arg in forbidden_add_args:
                            raise CommandValidationError(
                                f"Bulk adding with 'git add {arg}' is "
                                "forbidden for AI agents. Please specify "
                                "files explicitly (e.g., 'git add path/to/file.py') "
                                "to ensure temporary or unrelated files are not staged."
                            )

        if base_command in {"python", "python3"}:
            forbidden_python_flags = {"-c", "-m", "--code", "--module"}
            for p in parts[1:]:
                if p in forbidden_python_flags:
                    raise CommandValidationError(
                        f"Python flag '{p}' is prohibited. "
                        "Please write the code to a file first and then execute it."
                    )

        if base_command == "find":
            forbidden_find_args = {"-exec", "-execdir", "-ok", "-okdir", "-delete"}
            for arg in parts[1:]:
                if arg in forbidden_find_args:
                    raise CommandValidationError(
                        f"Find argument '{arg}' is prohibited for security."
                    )


def validate_command(command: str, custom_whitelist: Optional[Set[str]] = None) -> None:
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
