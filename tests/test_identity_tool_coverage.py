import sys
from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.identity_tool import main


def test_identity_tool_help(capsys):
    with patch.object(sys, "argv", ["identity_tool"]):
        main()
    captured = capsys.readouterr()
    assert "LLM-CLI Identity and Integrity Management Tool" in captured.out


def test_identity_tool_keygen(tmp_path, monkeypatch, capsys):
    key_dir = tmp_path / "keys"
    key_dir.mkdir()

    # Patch all class-level paths in IdentityManager
    from llm_cli.security.identity import IdentityManager

    monkeypatch.setattr(IdentityManager, "_KEY_DIR", key_dir)
    monkeypatch.setattr(IdentityManager, "_PRIVATE_KEY_PATH", key_dir / "id_rsa")
    monkeypatch.setattr(IdentityManager, "_PUBLIC_KEY_PATH", key_dir / "id_rsa.pub")
    monkeypatch.setattr(
        IdentityManager, "_PQC_PRIVATE_KEY_PATH", key_dir / "id_pqc.key"
    )
    monkeypatch.setattr(IdentityManager, "_PQC_PUBLIC_KEY_PATH", key_dir / "id_pqc.pub")

    with patch.object(sys, "argv", ["identity_tool", "keygen"]):
        main()

    captured = capsys.readouterr()
    assert "Generating Identity Keys..." in captured.out
    assert "Keys generated" in captured.out
    assert (key_dir / "id_rsa").exists()
    assert (key_dir / "id_pqc.pub").exists()


def test_identity_tool_manifest(tmp_path, monkeypatch, capsys):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "llm_cli").mkdir()
    (project_root / "llm_cli" / "apps").mkdir()
    (project_root / "llm_cli" / "apps" / "mcp_server.py").write_text("print('test')")

    # Mock the Path(__file__) in identity_tool.py
    # identity_tool.py: root_path = Path(__file__).resolve().parent.parent.parent
    # We want root_path to be project_root.
    # So we mock Path in identity_tool.py

    mock_path = MagicMock()
    mock_path.resolve.return_value.parent.parent.parent = project_root

    key_dir = tmp_path / "keys"
    # Also need to patch IdentityManager here because manifest calls IntegrityVerifier which calls IdentityManager._ensure_keys
    from llm_cli.security.identity import IdentityManager

    monkeypatch.setattr(IdentityManager, "_KEY_DIR", key_dir)
    monkeypatch.setattr(IdentityManager, "_PRIVATE_KEY_PATH", key_dir / "id_rsa")
    monkeypatch.setattr(IdentityManager, "_PUBLIC_KEY_PATH", key_dir / "id_rsa.pub")
    monkeypatch.setattr(
        IdentityManager, "_PQC_PRIVATE_KEY_PATH", key_dir / "id_pqc.key"
    )
    monkeypatch.setattr(IdentityManager, "_PQC_PUBLIC_KEY_PATH", key_dir / "id_pqc.pub")

    with patch("llm_cli.apps.identity_tool.Path", return_value=mock_path):
        with patch(
            "llm_cli.security.integrity.IntegrityVerifier.MANIFEST_PATH",
            tmp_path / "manifest.json",
        ):
            with patch(
                "llm_cli.security.integrity.IntegrityVerifier.CRITICAL_FILES",
                ["llm_cli/apps/mcp_server.py"],
            ):
                with patch("llm_cli.consts.AUDIT_LOG_PATH", tmp_path / "audit.jsonl"):
                    with patch.object(sys, "argv", ["identity_tool", "manifest"]):
                        main()

    captured = capsys.readouterr()
    assert "Generating Integrity Manifest..." in captured.out
    assert "Integrity manifest signed" in captured.out
    assert (tmp_path / "manifest.json").exists()


def test_identity_tool_manifest_failure(tmp_path, monkeypatch, capsys):
    with patch(
        "llm_cli.security.integrity.IntegrityVerifier.rebuild_manifest",
        return_value=False,
    ):
        with patch.object(sys, "argv", ["identity_tool", "manifest"]):
            with pytest.raises(SystemExit) as e:
                main()
            assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to generate manifest." in captured.out
