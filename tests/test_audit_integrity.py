from unittest.mock import patch

import pytest

from llm_cli.security.audit import log_audit
from llm_cli.security.merkle_anchor import SessionAnchorManager


@pytest.fixture
def mock_audit_log(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    anchor_dir = tmp_path / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch("llm_cli.security.audit.AUDIT_LOG_PATH", log_path),
        patch("llm_cli.security.merkle_anchor.AUDIT_LOG_PATH", log_path),
        patch("llm_cli.security.merkle_anchor.ANCHOR_DIR", anchor_dir),
    ):
        yield log_path


@pytest.fixture
def mock_config():
    with patch("llm_cli.security.audit.config_manager") as m_config:
        yield m_config


def test_audit_rotation_and_anchor_cleanup(mock_audit_log, mock_config):
    """
    Test that audit logs are rotated, old archives are deleted,
    and orphaned anchors are cleaned up.
    """
    # 1. Setup config for small limits
    mock_config.get.side_effect = lambda section, key, default=None: {
        ("general", "max_audit_log_lines"): 2,
        ("general", "max_audit_archives"): 1,
    }.get((section, key), default)

    # Mock identity for PQC signing if needed, or let it fallback to no signature
    # (Since we just want to test rotation and cleanup, we can let it fail/fallback)

    trace_id_1 = "session-1"
    trace_id_2 = "session-2"
    trace_id_3 = "session-3"

    # Create entries for session 1
    log_audit("tool1", {"arg": 1}, "out1", context={"trace_id": trace_id_1})
    log_audit("tool2", {"arg": 2}, "out2", context={"trace_id": trace_id_1})

    # Session 1 should have an anchor
    SessionAnchorManager.create_anchor(trace_id_1)

    # Check anchor file exists (manually using our patched ANCHOR_DIR)
    import llm_cli.security.merkle_anchor

    anchor_1 = llm_cli.security.merkle_anchor.ANCHOR_DIR / f"{trace_id_1}.anchor.json"
    assert anchor_1.exists()

    # Now we have 2 lines in audit.jsonl (session-1)
    # Adding a 3rd line will trigger rotation.
    log_audit("tool3", {"arg": 3}, "out3", context={"trace_id": trace_id_2})

    archives = list(mock_audit_log.parent.glob("audit.jsonl.archive.*.jsonl"))
    assert len(archives) >= 1

    # Add more entries to push session 1 completely out
    # main log is at 2 lines, so every call rotates.
    log_audit("tool4", {"arg": 4}, "out4", context={"trace_id": trace_id_2})
    log_audit("tool5", {"arg": 5}, "out5", context={"trace_id": trace_id_3})
    log_audit("tool6", {"arg": 6}, "out6", context={"trace_id": trace_id_3})
    log_audit("tool7", {"arg": 7}, "out7", context={"trace_id": trace_id_3})

    # Since max_audit_archives=1, only 1 archive should remain.
    archives = list(mock_audit_log.parent.glob("audit.jsonl.archive.*.jsonl"))
    assert len(archives) == 1

    # Check if session 1's anchor was deleted (it's orphaned)
    assert not anchor_1.exists()

    # Create anchor for session 2
    SessionAnchorManager.create_anchor(trace_id_2)
    anchor_2 = llm_cli.security.merkle_anchor.ANCHOR_DIR / f"{trace_id_2}.anchor.json"

    # If session 2 is still in the archives/log, its anchor should stay
    active_traces = set()
    for p in archives + [mock_audit_log]:
        with p.open("r") as f:
            for line in f:
                if trace_id_2 in line:
                    active_traces.add(trace_id_2)

    if trace_id_2 in active_traces:
        assert anchor_2.exists()
    else:
        # If rotation pushed it out, it might be gone
        pass
