# tests/test_command_validator.py

import pytest

from llm_cli.security import (
    CommandValidationError,
    CommandValidator,
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

    def test_git_add_restrictions(self):
        """Test that bulk git add operations are blocked."""
        validator = CommandValidator()

        # Forbidden bulk add operations
        forbidden_adds = [
            "git add .",
            "git add *",
            "git add :",
            "git add -A",
            "git add --all",
            "git add -u",
            "git add --update",
            "git add . --force",
        ]
        for cmd in forbidden_adds:
            with pytest.raises(
                CommandValidationError,
                match="Bulk adding with 'git add .*' is forbidden",
            ):
                validator.validate(cmd)

        # Explicit file additions should be allowed
        validator.validate("git add main.py")
        validator.validate("git add src/core.py tests/test_core.py")
        validator.validate("git add README.md .gitignore")

    def test_path_traversal_blocking(self):
        """Test that any command with .. is blocked."""
        validator = CommandValidator()
        with pytest.raises(
            CommandValidationError, match="Directory traversal '..' is forbidden"
        ):
            validator.validate("ls ../secrets")

    def test_newline_injection(self):
        """Test that newline characters are strictly forbidden."""
        validator = CommandValidator()
        # Verify the error message contains the readable representation
        with pytest.raises(
            CommandValidationError,
            match=r"Command contains dangerous pattern '\\n \(Newline\)'",
        ):
            validator.validate("ls\necho dangerous")

    def test_background_execution(self):
        """Test that background execution using '&' is forbidden."""
        validator = CommandValidator()
        with pytest.raises(
            CommandValidationError, match=r"Single '&' for background execution is forbidden|Command contains dangerous pattern '&'"
        ):
            validator.validate("ls & echo dangerous")

    def test_find_restrictions(self):
        """Test specific restrictions on find command arguments."""
        validator = CommandValidator()

        # Safe usage should be allowed
        validator.validate("find . -name '*.py'")

        # Forbidden arguments
        forbidden_args = ["-exec", "-execdir", "-ok", "-okdir", "-delete"]
        for arg in forbidden_args:
            # Use '+' for exec to avoid semicolon check, or just the arg itself
            test_cmd = (
                f"find . {arg} rm {{}} +"
                if "exec" in arg or "ok" in arg
                else f"find . {arg}"
            )
            with pytest.raises(
                CommandValidationError, match=f"Find argument '{arg}' is prohibited"
            ):
                validator.validate(test_cmd)

    def test_removed_commands(self):
        """Test that dangerous commands have been removed from the whitelist."""
        validator = CommandValidator()

        # List of commands that were removed for security
        removed_commands = [
            "awk",
            "tar",
            "gzip",
            "gunzip",
            "bzip2",
            "bunzip2",
            "zip",
            "unzip",
            "whoami",
            "id",
            "groups",
            "hostname",
            "uname",
            "ps",
            "top",
            "htop",
            "pgrep",
            "env",
            "printenv",
            "base64",
            "xxd",
            "curl",
            "wget",
            "nc",
            "ruff",
        ]

        for cmd in removed_commands:
            with pytest.raises(
                CommandValidationError,
                match=f"Command '{cmd}' is not in the allowed whitelist",
            ):
                validator.validate(f"{cmd} some_arg")

    def test_error_message_readability(self):
        """Test that dangerous patterns produce readable error messages."""
        validator = CommandValidator()

        # Test newline specifically
        try:
            validator.validate("ls\nls")
        except CommandValidationError as e:
            assert "\\n (Newline)" in str(e)

        # Test backtick
        try:
            validator.validate("echo `ls`")
        except CommandValidationError as e:
            # Should show '`' (repr)
            assert "`" in str(e)

    def test_command_chaining_allowed(self):
        """Test that &&, ||, and | are allowed if parts are safe."""
        validator = CommandValidator()
        # Should be allowed
        validator.validate("ls && echo 'done'")
        validator.validate("grep 'foo' file.txt || echo 'not found'")
        validator.validate("cat file.txt | grep 'bar'")

        # Should be blocked if any part is unsafe
        with pytest.raises(CommandValidationError, match="not in the allowed whitelist"):
            validator.validate("ls && rm file.txt")

        with pytest.raises(CommandValidationError, match="not in the allowed whitelist"):
             validator.validate("whoami || echo 'whoops'")

