import os
import shutil

import pytest

from llm_cli.consts import KEY_DIR, LLM_CLI_BASE_DIR
from llm_cli.security.identity import IdentityManager
from llm_cli.security.permissions import setup_permissions


def test_umask_setting():
    # Setup permissions sets umask to 0o077
    setup_permissions()

    # Verify current umask
    current_umask = os.umask(0)
    os.umask(current_umask)  # Restore it
    assert current_umask == 0o077


def test_setup_permissions_fixes_existing():
    # LLM_CLI_BASE_DIR is already redirected to a temp dir in conftest.py
    if LLM_CLI_BASE_DIR.exists():
        shutil.rmtree(LLM_CLI_BASE_DIR)
    LLM_CLI_BASE_DIR.mkdir(parents=True)

    # Create a directory with 755
    sub_dir = LLM_CLI_BASE_DIR / "test_dir"
    sub_dir.mkdir()
    sub_dir.chmod(0o755)

    # Create a file with 644
    test_file = sub_dir / "test_file.txt"
    test_file.write_text("secret")
    test_file.chmod(0o644)

    # Verify they are currently "open"
    assert (sub_dir.stat().st_mode & 0o777) == 0o755
    assert (test_file.stat().st_mode & 0o777) == 0o644

    setup_permissions()

    # Verify they are now restricted
    assert (LLM_CLI_BASE_DIR.stat().st_mode & 0o777) == 0o700
    assert (sub_dir.stat().st_mode & 0o777) == 0o700
    assert (test_file.stat().st_mode & 0o777) == 0o600


def test_check_private_file_permissions_raises(tmp_path):
    test_file = tmp_path / "private.key"
    test_file.write_text("private key content")

    # Too open: 0644
    test_file.chmod(0o644)
    with pytest.raises(PermissionError) as excinfo:
        IdentityManager._check_private_file_permissions(test_file)
    assert "too open" in str(excinfo.value)

    # Secure: 0600
    test_file.chmod(0o600)
    IdentityManager._check_private_file_permissions(test_file)  # Should not raise


def test_ensure_keys_creates_secure_files():
    # Clear existing keys if any
    if KEY_DIR.exists():
        shutil.rmtree(KEY_DIR)

    # This will generate keys if they don't exist
    # Using a subset of keys to speed up if possible, but IdentityManager._ensure_keys()
    # generates everything.
    IdentityManager._ensure_keys()

    assert KEY_DIR.exists()
    assert (KEY_DIR.stat().st_mode & 0o777) == 0o700

    # Check RSA private key
    rsa_key = IdentityManager._PRIVATE_KEY_PATH
    assert rsa_key.exists()
    assert (rsa_key.stat().st_mode & 0o777) == 0o600

    # Check a PQC key
    pqc_key = IdentityManager._PQC_PRIVATE_KEY_PATH
    if pqc_key.exists():
        assert (pqc_key.stat().st_mode & 0o777) == 0o600
