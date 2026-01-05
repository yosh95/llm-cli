# llm_cli/security/command_validator.py

import os
import re
import shlex
from typing import List, Optional, Set

from llm_cli.clients.config import _load_config_from_file


class CommandValidationError(Exception):
    """Raised when a command fails security validation."""

    pass


class CommandValidator:
    """
    Validates shell commands against a whitelist of allowed commands.
    Provides protection against command injection and dangerous operations.
    """

    # Default whitelist of safe, read-only or low-risk commands
    DEFAULT_WHITELIST = {
        # File viewing and navigation
        "ls",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "file",
        "stat",
        "pwd",
        "tree",
        "du",
        "df",
        # Text processing
        "grep",
        "egrep",
        "fgrep",
        "sed",
        "awk",
        "cut",
        "sort",
        "uniq",
        "wc",
        "tr",
        "fold",
        "column",
        # File search
        "find",
        "locate",
        "which",
        "whereis",
        "type",
        # System info (read-only)
        "echo",
        "date",
        "cal",
        "uptime",
        "whoami",
        "id",
        "groups",
        "hostname",
        "uname",
        "arch",
        "sleep",
        # Process viewing (no control)
        "ps",
        "top",
        "htop",
        "pgrep",
        # Network info (read-only)
        "ping",
        "traceroute",
        "dig",
        "nslookup",
        "host",
        "whois",
        "netstat",
        "ifconfig",
        "ip",
        # Development tools
        "git",
        "diff",
        "patch",
        "make",
        "cmake",
        "ruff",
        # Package managers (info commands only)
        "pip",
        "npm",
        "cargo",
        "go",
        # Python
        "python",
        "python3",
        "pytest",
        # Compression (viewing)
        "tar",
        "gzip",
        "gunzip",
        "bzip2",
        "bunzip2",
        "zip",
        "unzip",
        "zcat",
        "zless",
        # Misc utilities
        "jq",
        "yq",
        "base64",
        "xxd",
        "md5sum",
        "sha256sum",
        "env",
        "printenv",
    }

    # Dangerous patterns that suggest command injection or dangerous operations
    DANGEROUS_PATTERNS = [
        r";",  # Command separator
        r"`",  # Command substitution (backticks)
        r"\$\(",  # Command substitution $(...)
        r"\$\{",  # Variable substitution ${...}
    ]

    # Operators that we now support by splitting and validating each part
    CHAINING_OPERATORS = {"&&", "||", "|"}

    # MCP server whitelist
    MCP_SERVER_WHITELIST = {
        "node",
        "python",
        "python3",
        "deno",
        "npx",
        "docker",
        "ssh",
        "uvx",
    }

    def __init__(
        self,
        custom_whitelist: Optional[Set[str]] = None,
        allow_dangerous_patterns: bool = False,
        mcp_mode: bool = False,
    ):
        if mcp_mode:
            self.whitelist = self.MCP_SERVER_WHITELIST.copy()
        else:
            self.whitelist = self.DEFAULT_WHITELIST.copy()

        if custom_whitelist:
            self.whitelist.update(custom_whitelist)

        self.allow_dangerous_patterns = allow_dangerous_patterns
        self.mcp_mode = mcp_mode

    def validate(self, command: str) -> None:
        if not command or not command.strip():
            raise CommandValidationError("Empty command not allowed")

        if not self.allow_dangerous_patterns:
            self._check_dangerous_patterns(command)

        try:
            # Tokenize the command respecting quotes
            tokens = shlex.split(command)
        except ValueError as e:
            raise CommandValidationError(
                f"Failed to parse command (possible shell injection): {e}"
            )

        if not tokens:
            raise CommandValidationError("No command found after parsing")

        # Split tokens by chaining operators and validate each segment
        current_segment = []
        for token in tokens:
            if token in self.CHAINING_OPERATORS:
                if current_segment:
                    self._validate_parts(current_segment)
                    current_segment = []
            else:
                current_segment.append(token)

        if current_segment:
            self._validate_parts(current_segment)

    def _validate_parts(self, parts: List[str]) -> None:
        if not parts:
            return

        self._check_paths(parts)

        base_command = parts[0]
        # Handle cases like /usr/bin/git
        if "/" in base_command:
            base_command = base_command.split("/")[-1]

        if base_command not in self.whitelist:
            allowed_list = ", ".join(sorted(self.whitelist))
            raise CommandValidationError(
                f"Command '{base_command}' is not in the allowed whitelist. "
                f"Allowed commands: {allowed_list}"
            )

        self._check_dangerous_arguments(base_command, parts)

    def _check_dangerous_patterns(self, command: str) -> None:
        # Before splitting, check for patterns that shlex might swallow or are globally forbidden
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                raise CommandValidationError(
                    f"Command contains dangerous pattern '{pattern}'."
                )

        # Check for redirection - this is still blocked globally as it's hard to split safely
        if re.search(r"[<>]", command):
            raise CommandValidationError(
                "I/O redirection (> or <) is forbidden for security."
            )

    def _check_paths(self, parts: List[str]) -> None:
        cwd = os.getcwd()
        for part in parts:
            if ".." in part:
                raise CommandValidationError(
                    f"Directory traversal '..' is forbidden in argument: {part}"
                )

            if part.startswith("/"):
                # Relax absolute path check:
                # 1. Allow if it's within the current working directory
                # 2. Allow if the path does not actually exist on the system
                #    (likely a regex or string like grep "/help")
                # 3. Block if it's an existing absolute path outside CWD
                try:
                    abs_path = os.path.abspath(part)
                    if os.path.exists(abs_path):
                        if not abs_path.startswith(cwd):
                            # Check for sensitive system paths
                            sensitive_prefixes = [
                                "/etc",
                                "/var",
                                "/root",
                                "/bin",
                                "/sbin",
                                "/usr",
                                "/dev",
                                "/proc",
                                "/sys",
                                "/boot",
                            ]
                            if any(abs_path.startswith(p) for p in sensitive_prefixes):
                                raise CommandValidationError(
                                    f"Access to system absolute path is forbidden: {part}"
                                )
                except (ValueError, OSError):
                    pass

    def _check_dangerous_arguments(self, base_command: str, parts: List[str]) -> None:
        if base_command == "git":
            dangerous_git = {
                "push",
                "clone",
                "fetch",
                "pull",
                "submodule",
                "config",
            }
            for p in parts[1:]:
                if p in dangerous_git:
                    raise CommandValidationError(
                        f"Git subcommand '{p}' is not allowed."
                    )

        package_managers = {"pip", "npm", "cargo", "go"}
        if base_command in package_managers:
            dangerous_ops = {
                "install",
                "uninstall",
                "remove",
                "add",
                "publish",
                "update",
                "upgrade",
            }
            for p in parts[1:]:
                if p in dangerous_ops:
                    raise CommandValidationError(
                        f"Operation '{p}' is not allowed for {base_command}."
                    )

        if base_command in {"python", "python3"}:
            forbidden_python_flags = {"-c", "-m", "--code", "--module"}
            for p in parts[1:]:
                if p in forbidden_python_flags:
                    raise CommandValidationError(f"Python flag '{p}' is forbidden.")

        if base_command == "tar":
            for arg in parts[1:]:
                if arg.startswith("-") and "x" in arg:
                    raise CommandValidationError(
                        "Tar extraction (x flag) is not allowed."
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


def validate_mcp_command(command: str) -> None:
    config = _load_config_from_file()
    security_config = config.get("security", {})
    mcp_whitelist = set(security_config.get("allowed_mcp_commands", []))
    validator = CommandValidator(
        custom_whitelist=mcp_whitelist if mcp_whitelist else None,
        allow_dangerous_patterns=False,
        mcp_mode=True,
    )
    validator.validate(command)
