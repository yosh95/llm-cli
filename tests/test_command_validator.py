# tests/test_command_validator.py

import pytest

from llm_cli.security import (
    CommandValidationError,
    CommandValidator,
    validate_mcp_command,
)


class TestCommandValidator:
    def test_allowed_commands(self):
        validator = CommandValidator()
        validator.validate("ls -la")
        validator.validate("grep pattern file.txt")
        validator.validate("git status")

    def test_disallowed_sed_and_patch(self):
        """Test that sed and patch are now disallowed."""
        validator = CommandValidator()
        # sed is disallowed by whitelist
        with pytest.raises(
            CommandValidationError, match="not in the allowed whitelist"
        ):
            validator.validate("sed 's/a/b/g' file.txt")

        # patch is disallowed by whitelist (and also redirects if used)
        with pytest.raises(
            CommandValidationError, match="not in the allowed whitelist"
        ):
            validator.validate("patch file.txt")

    def test_git_strict_restrictions(self):
        """Test that dangerous git subcommands are strictly blocked."""
        validator = CommandValidator()

        # Forbidden subcommands
        forbidden = ["push", "remote", "alias", "apply", "config", "clone"]
        for sub in forbidden:
            with pytest.raises(CommandValidationError, match="strictly forbidden"):
                validator.validate(f"git {sub}")

        # Allowed subcommands
        validator.validate("git status")
        validator.validate("git diff")
        validator.validate("git log")
        validator.validate("git commit -m 'test'")

    def test_path_traversal_blocking(self):
        """Test that any command with .. is blocked."""
        validator = CommandValidator()
        with pytest.raises(
            CommandValidationError, match="Directory traversal '..' is forbidden"
        ):
            validator.validate("ls ../secrets")

    def test_mcp_mode(self):
        """Verify MCP mode still works with its own whitelist."""
        validator = CommandValidator(mcp_mode=True)
        validator.validate("node server.js")
        validator.validate("docker run alpine")

        with pytest.raises(
            CommandValidationError, match="not in the allowed whitelist"
        ):
            validator.validate("ls -la")

    def test_validate_mcp_command_function(self):
        """Test the convenience function for MCP, now allowing -m for python."""
        validate_mcp_command("python -m mcp_server")
        with pytest.raises(CommandValidationError):
            validate_mcp_command("rm -rf /")
