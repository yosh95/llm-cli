from unittest.mock import patch

import pytest

from llm_cli.security.integrity import IntegrityVerifier, verify_installation


class TestIntegrityAutoInit:
    @pytest.fixture
    def mock_env(self, tmp_path):
        # Create a mock application directory structure
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "llm_cli").mkdir()
        (app_dir / "llm_cli/main.py").write_text("print('hello')", encoding="utf-8")
        (app_dir / "pyproject.toml").write_text("name = 'test'", encoding="utf-8")

        # Mock LLM_CLI_BASE_DIR to point to tmp_path
        with patch("llm_cli.security.integrity.LLM_CLI_BASE_DIR", tmp_path):
            # Point IntegrityVerifier's MANIFEST_PATH to our tmp_path
            IntegrityVerifier.MANIFEST_PATH = tmp_path / "integrity_manifest.json"
            yield app_dir, tmp_path

    def test_verify_installation_creates_manifest_if_missing(self, mock_env):
        app_dir, base_dir = mock_env
        manifest_path = base_dir / "integrity_manifest.json"

        assert not manifest_path.exists()

        # Dependencies for rebuild_manifest/verify
        with (
            patch("llm_cli.security.identity.IdentityManager._ensure_keys"),
            patch(
                "llm_cli.security.identity.IdentityManager._get_pqc_private_key_content",
                return_value=b"fake_priv",
            ),
            patch("llm_cli.security.pqc.PQCProvider.sign", return_value=b"fake_sig"),
            patch("llm_cli.ui.console.print"),
            patch("llm_cli.clients.config.config_manager.get", return_value="high"),
            patch("llm_cli.security.integrity.LLM_CLI_BASE_DIR", base_dir),
            patch(
                "llm_cli.security.integrity.IntegrityVerifier.MANIFEST_PATH",
                manifest_path,
            ),
        ):
            # The verifier created inside verify_installation will use the real
            # root_path (the repo root). We want it to use our mock app_dir.
            # So we patch the IntegrityVerifier constructor to always use app_dir.
            original_init = IntegrityVerifier.__init__

            def mock_init(self, base_path):
                original_init(self, app_dir)

            with patch(
                "llm_cli.security.integrity.IntegrityVerifier.__init__", mock_init
            ):
                # Execute verify_installation
                verify_installation()

        # Check if manifest was created
        assert manifest_path.exists()
        import json

        with manifest_path.open("r") as f:
            data = json.load(f)
            assert "hashes" in data
            # Check for files we created in mock_env app_dir
            assert "llm_cli/main.py" in data["hashes"]
            assert "pyproject.toml" in data["hashes"]
