# llm_cli/security/command_validator.py

import shlex
import re
from typing import List, Set, Optional, Dict, Any
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
        'ls', 'cat', 'head', 'tail', 'less', 'more', 'file', 'stat',
        'pwd', 'tree', 'du', 'df',

        # Text processing
        'grep', 'egrep', 'fgrep', 'sed', 'awk', 'cut', 'sort', 'uniq',
        'wc', 'tr', 'fold', 'column',

        # File search
        'find', 'locate', 'which', 'whereis', 'type',

        # System info (read-only)
        'echo', 'date', 'cal', 'uptime', 'whoami', 'id', 'groups',
        'hostname', 'uname', 'arch', 'sleep',

        # Process viewing (no control)
        'ps', 'top', 'htop', 'pgrep',

        # Network info (read-only)
        'ping', 'traceroute', 'dig', 'nslookup', 'host', 'whois',
        'netstat', 'ifconfig', 'ip',

        # Development tools (mostly read-only)
        'git', 'diff', 'patch', 'make', 'cmake',

        # Package managers (info commands only - install/remove require explicit permission)
        'pip', 'npm', 'cargo', 'go',

        # Python
        'python', 'python3', 'pytest',

        # Compression (viewing)
        'tar', 'gzip', 'gunzip', 'bzip2', 'bunzip2', 'zip', 'unzip',
        'zcat', 'zless',

        # Misc utilities
        'jq', 'yq', 'base64', 'xxd', 'md5sum', 'sha256sum',
        'curl', 'wget', 'env', 'printenv',
    }

    # Dangerous patterns that suggest command injection or dangerous operations
    DANGEROUS_PATTERNS = [
        r'&&',          # Command chaining
        r'\|\|',        # OR chaining
        r';',           # Command separator
        r'\|',          # Pipe
        r'>',           # Output redirection
        r'<',           # Input redirection
        r'`',           # Command substitution (backticks)
        r'\$\(',        # Command substitution $(...)
        r'\$\{',        # Variable substitution ${...}
        r'~/',          # Home directory expansion (can be dangerous)
        r'\.\.',        # Parent directory traversal
    ]

    # MCP server whitelist - commands commonly used for MCP servers
    MCP_SERVER_WHITELIST = {
        'node', 'python', 'python3', 'deno', 'npx',
        'docker', 'ssh', 'uvx',
    }

    def __init__(self, custom_whitelist: Optional[Set[str]] = None,
                 allow_dangerous_patterns: bool = False,
                 mcp_mode: bool = False):
        """
        Initialize the command validator.

        Args:
            custom_whitelist: Additional commands to allow (merged with defaults)
            allow_dangerous_patterns: If True, skip dangerous pattern checks
            mcp_mode: If True, use MCP server whitelist instead of default
        """
        if mcp_mode:
            self.whitelist = self.MCP_SERVER_WHITELIST.copy()
        else:
            self.whitelist = self.DEFAULT_WHITELIST.copy()

        if custom_whitelist:
            self.whitelist.update(custom_whitelist)

        self.allow_dangerous_patterns = allow_dangerous_patterns
        self.mcp_mode = mcp_mode

    def validate(self, command: str) -> None:
        """
        Validate a command string.

        Args:
            command: The command string to validate

        Raises:
            CommandValidationError: If the command fails validation
        """
        if not command or not command.strip():
            raise CommandValidationError("Empty command not allowed")

        # Check for dangerous patterns first (unless explicitly allowed)
        if not self.allow_dangerous_patterns:
            self._check_dangerous_patterns(command)

        # Parse the command to extract the base command
        try:
            parts = shlex.split(command)
        except ValueError as e:
            raise CommandValidationError(
                f"Failed to parse command (possible shell injection): {e}"
            )

        if not parts:
            raise CommandValidationError("No command found after parsing")

        base_command = parts[0]

        # Handle commands with path
        if '/' in base_command:
            # Extract just the command name from path
            base_command = base_command.split('/')[-1]

        # Check against whitelist
        if base_command not in self.whitelist:
            raise CommandValidationError(
                f"Command '{base_command}' is not in the allowed whitelist. "
                f"Allowed commands: {', '.join(sorted(self.whitelist))}"
            )

        # Additional checks for specific dangerous command arguments
        self._check_dangerous_arguments(base_command, parts)

    def _check_dangerous_patterns(self, command: str) -> None:
        """Check for dangerous shell patterns in the command."""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                raise CommandValidationError(
                    f"Command contains dangerous pattern '{pattern}'. "
                    f"Complex shell operations with pipes, redirects, and "
                    f"command substitution are not allowed for security reasons."
                )

    def _check_dangerous_arguments(self, base_command: str,
                                   parts: List[str]) -> None:
        """Check for dangerous arguments to specific commands."""

        # Check for dangerous git operations
        if base_command == 'git' and len(parts) > 1:
            git_subcommand = parts[1]
            dangerous_git_commands = {
                'push', 'clone', 'fetch', 'pull',  # Network operations
                'submodule',  # Can execute arbitrary code
                'config',  # Can modify git config
            }
            if git_subcommand in dangerous_git_commands:
                raise CommandValidationError(
                    f"Git subcommand '{git_subcommand}' is not allowed. "
                    f"Only read-only git operations are permitted."
                )

        # Check for dangerous package manager operations
        package_managers = {'pip', 'npm', 'cargo', 'go'}
        if base_command in package_managers and len(parts) > 1:
            operation = parts[1]
            dangerous_operations = {
                'install', 'uninstall', 'remove', 'add',
                'publish', 'update', 'upgrade',
            }
            if operation in dangerous_operations:
                raise CommandValidationError(
                    f"Package manager operation '{operation}' is not allowed. "
                    f"Only info/list commands are permitted for {base_command}."
                )

        # Check for dangerous tar operations (file extraction)
        if base_command == 'tar' and len(parts) > 1:
            # Check if any argument contains 'x' (extract)
            for arg in parts[1:]:
                if arg.startswith('-') and 'x' in arg:
                    raise CommandValidationError(
                        "Tar extraction is not allowed. "
                        "Only viewing tar contents (t flag) is permitted."
                    )

        # Check for dangerous curl/wget operations
        if base_command in {'curl', 'wget'}:
            for i, arg in enumerate(parts):
                # Check for output redirection or file writing
                if arg in {'-o', '--output', '-O', '--remote-name'}:
                    raise CommandValidationError(
                        f"{base_command} file writing is not allowed. "
                        f"Only viewing content is permitted."
                    )


def validate_command(command: str,
                    custom_whitelist: Optional[Set[str]] = None) -> None:
    """
    Convenience function to validate a command with custom whitelist from config.

    Args:
        command: The command string to validate
        custom_whitelist: Optional additional commands to allow

    Raises:
        CommandValidationError: If the command fails validation
    """
    # Load custom whitelist from config if available
    config = _load_config_from_file()
    security_config = config.get('security', {})

    # Merge config whitelist with provided whitelist
    config_whitelist = set(security_config.get('allowed_commands', []))
    if custom_whitelist:
        config_whitelist.update(custom_whitelist)

    # Check if dangerous patterns are allowed in config
    allow_dangerous = security_config.get('allow_dangerous_patterns', False)

    validator = CommandValidator(
        custom_whitelist=config_whitelist if config_whitelist else None,
        allow_dangerous_patterns=allow_dangerous
    )
    validator.validate(command)


def validate_mcp_command(command: str) -> None:
    """
    Validate a command intended for MCP server spawning.

    Args:
        command: The command string to validate

    Raises:
        CommandValidationError: If the command fails validation
    """
    # Load MCP whitelist from config if available
    config = _load_config_from_file()
    security_config = config.get('security', {})

    mcp_whitelist = set(security_config.get('allowed_mcp_commands', []))

    validator = CommandValidator(
        custom_whitelist=mcp_whitelist if mcp_whitelist else None,
        allow_dangerous_patterns=False,  # Never allow dangerous patterns for MCP
        mcp_mode=True
    )
    validator.validate(command)
