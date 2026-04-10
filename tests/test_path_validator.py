# tests/test_path_validator.py

from pathlib import Path
from unittest.mock import patch

import pytest

from llm_cli.security.path_validator import PathValidationError, validate_path


@pytest.fixture(autouse=True)
def mock_path_config():
    with patch("llm_cli.security.path_validator.config_manager.load_config") as mock_load:
        mock_load.return_value = {
            "security": {
                "allowed_paths": [".", "/var"],
                "blocked_paths": ["/etc", "/var/log/syslog"],
            }
        }
        yield


class TestBlockedFilenames:
    """Tests for the blocked_filenames fnmatch-based filename blocklist."""

    @pytest.fixture(autouse=True)
    def mock_with_blocked_filenames(self):
        """Override the autouse fixture with one that includes blocked_filenames."""
        with patch("llm_cli.security.path_validator.config_manager.load_config") as mock_load:
            mock_load.return_value = {
                "security": {
                    "allowed_paths": ["."],
                    "blocked_paths": [],
                    "blocked_filenames": [
                        ".env",
                        ".env.*",
                        "*.pem",
                        "*.key",
                        "id_rsa",
                        "id_ecdsa",
                        "id_ed25519",
                    ],
                }
            }
            yield

    def test_blocks_dotenv(self):
        """.env must be blocked by the filename blocklist."""
        with pytest.raises(PathValidationError, match="blocked pattern"):
            validate_path(".env")

    def test_blocks_dotenv_variants(self):
        """.env.local, .env.production etc. must all be blocked."""
        for variant in (".env.local", ".env.production", ".env.test", ".env.staging"):
            with (
                pytest.raises(PathValidationError, match="blocked pattern"),
                pytest.MonkeyPatch().context() as mp,
            ):
                # Resolve against a real directory so the whitelist passes
                mp.chdir(Path.cwd())
                validate_path(variant)

    def test_blocks_pem_key_files(self):
        """Certificate and private key files must be blocked."""
        for filename in ("server.pem", "private.key", "id_rsa", "id_ecdsa", "id_ed25519"):
            with pytest.raises(PathValidationError, match="blocked pattern"):
                validate_path(filename)

    def test_allows_normal_files(self):
        """Regular source files must not be blocked."""
        # Should not raise (path stays within CWD whitelist)
        validate_path("README.md")
        validate_path("pyproject.toml")
        validate_path("main.py")

    def test_env_in_name_not_blocked(self):
        """Files with 'env' in their name but not matching the pattern must pass."""
        # 'environment.py' or 'dotenv_example' should not match '.env' or '.env.*'
        validate_path("environment.py")
        validate_path("dotenv_example.txt")


class TestPathValidator:
    def test_sandbox_within_cwd(self):
        """Should allow paths within current directory."""
        cwd = Path.cwd()
        test_file = cwd / "test_file.txt"
        # Should not raise
        validate_path("test_file.txt")
        validate_path(str(test_file))

    def test_blocks_traversal(self):
        """Should block any use of ..
        The error message is intentionally vague ('Access to path is forbidden.')
        to avoid leaking bypass hints to the caller (including LLM feedback loops).
        """
        with pytest.raises(PathValidationError, match="Access to path is forbidden\\."):
            validate_path("../outside.txt")
        with pytest.raises(PathValidationError, match="Access to path is forbidden\\."):
            validate_path("dir/../../etc/passwd")

    def test_normalization(self):
        """Should normalize quotes, whitespace and trailing slashes."""
        cwd = Path.cwd().resolve()

        # Trailing slash
        assert validate_path("tests/").resolve() == (cwd / "tests").resolve()

        # Quotes
        assert validate_path("'tests'").resolve() == (cwd / "tests").resolve()
        assert validate_path('"tests/"').resolve() == (cwd / "tests").resolve()

        # Whitespace
        assert validate_path("  tests  ").resolve() == (cwd / "tests").resolve()
        assert validate_path(" ' tests/ ' ").resolve() == (cwd / "tests").resolve()

    def test_blocks_absolute_system_paths(self):
        """Should block absolute paths to system directories."""
        # /etc/passwd and /var/... should be blocked by the blacklist first
        with pytest.raises(PathValidationError, match="Access to blocked path is forbidden"):
            validate_path("/etc/passwd")
        with pytest.raises(PathValidationError, match="Access to blocked path is forbidden"):
            validate_path("/var/log/syslog")
