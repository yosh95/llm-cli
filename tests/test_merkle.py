import json
import uuid

from llm_cli.consts import AUDIT_LOG_PATH
from llm_cli.security.audit import log_audit
from llm_cli.security.merkle_anchor import SessionAnchorManager


def test_merkle_anchoring():
    # 1. Clear or use a temp audit log
    trace_id = str(uuid.uuid4())
    print(f"Testing with Trace ID: {trace_id}")

    # 2. Generate some audit logs
    context = {"trace_id": trace_id, "model": "test-model"}
    log_audit("test_tool_1", {"arg": 1}, "output 1", context=context)
    log_audit("test_tool_2", {"arg": 2}, "output 2", context=context)

    # 3. Create Anchor
    root = SessionAnchorManager.create_anchor(trace_id)
    print(f"Generated Merkle Root: {root}")
    assert root is not None

    # 4. Verify Anchor
    success = SessionAnchorManager.verify_session(trace_id)
    print(f"Verification Result: {success}")
    assert success is True

    # 5. Tamper with the log and check if verification fails
    with AUDIT_LOG_PATH.open("r") as f:
        lines = f.readlines()

    # Tamper with the last entry's output for this trace_id
    tampered = False
    with AUDIT_LOG_PATH.open("w") as f:
        for line in lines:
            entry = json.loads(line)
            if entry.get("trace_id") == trace_id and not tampered:
                entry["output"] = "TAMPERED"
                f.write(json.dumps(entry) + "\n")
                tampered = True
            else:
                f.write(line)

    print("Tampered with log entry.")
    success_tampered = SessionAnchorManager.verify_session(trace_id)
    print(f"Verification Result (after tampering): {success_tampered}")
    assert success_tampered is False
    print("Test passed!")


if __name__ == "__main__":
    test_merkle_anchoring()
