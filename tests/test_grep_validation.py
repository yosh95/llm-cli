import pytest

from llm_cli.security.command_validator import CommandValidationError, validate_command


def test_grep_with_slash_pattern():
    # '/abcd/' is likely not a real path, so it should be treated as a pattern
    # and passed through validation because it doesn't exist.
    try:
        validate_command("grep -rn '/abcd/' .")
    except CommandValidationError as e:
        pytest.fail(f"Validation failed for valid grep pattern: {e}")


def test_grep_with_existing_system_file():
    from pathlib import Path

    # '/etc/passwd' exists (on most *nix), so it should fail validation
    # even if used as a grep pattern, to be safe.
    if Path("/etc/passwd").exists():
        with pytest.raises(CommandValidationError):
            validate_command("grep -rn '/etc/passwd' .")


def test_ls_non_existent_path():
    # 'ls' is not in the exempted list for non-existent paths.
    # So 'ls /nonexistent' should still fail if outside CWD.
    # Note: validate_path resolves paths. '/nonexistent' resolves to '/nonexistent'
    # which is outside CWD.
    with pytest.raises(CommandValidationError):
        validate_command("ls /nonexistent")


if __name__ == "__main__":
    # Manually run tests if executed directly
    try:
        test_grep_with_slash_pattern()
        print("test_grep_with_slash_pattern: PASS")
    except Exception as e:
        print(f"test_grep_with_slash_pattern: FAIL {e}")

    try:
        test_grep_with_existing_system_file()
        print("test_grep_with_existing_system_file: PASS")
    except Exception as e:
        print(f"test_grep_with_existing_system_file: FAIL {e}")

    try:
        test_ls_non_existent_path()
        print("test_ls_non_existent_path: PASS")
    except Exception as e:
        print(f"test_ls_non_existent_path: FAIL {e}")
