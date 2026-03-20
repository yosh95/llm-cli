# Security Implementation & Zero-Trust Architecture

`llm_cli` is designed with a "Zero-Trust" security model for agentic workflows. This document maps the security claims to their specific implementations.

## 1. Post-Quantum Cryptography (PQC)
- **Mechanism:** Dual-layer encryption and digital signatures using NIST-compliant algorithms (ML-DSA / Dilithium and ML-KEM / Kyber).
- **Implementation:** `llm_cli/security/pqc.py` and `llm_cli/security/identity.py`.
- **Hybrid Signatures:** Implements `HybridSigner` which combines classical (RSA/JWT) and PQC signatures to ensure security even if one algorithm is compromised.
- **Bi-directional Verification:** Tool outputs are signed with ML-DSA (`sign_tool_result`), allowing the LLM's session to verify that the data originated from a trusted execution environment.

## 2. Dynamic Guardrails: Real-time Anomaly Detection (Mamba Sentinel)
- **Mechanism:** A high-speed State Space Model (Mamba SSM) monitors the model's reasoning process in real-time to detect intent deviation or manipulation attempts.
- **Implementation:** `llm_cli/security/sentinel.py` and `llm_cli/mamba_core/`.
- **Logic:** Replaces slow Dual-LLM intent analysis with a sub-millisecond latency check. 
- **Prompt Anchoring:** The sentinel re-injects the user's initial intent into its hidden state for each chunk, allowing it to detect subtle semantic drifts from the original request. Anomalies (high surprise scores) trigger security escalation (e.g., forcing manual approval).

## 3. ABAC Policy Engine
- **Mechanism:** Attribute-Based Access Control (ABAC) determines tool permissions based on identity proof (PQC signatures), resource attributes (path scopes), and tool risk levels.
- **Implementation:** `llm_cli/security/policy.py`.
- **Risk-Based Evaluation:** High-risk tools (like `execute_python`) require valid PQC identity proof. Access is denied if the security requirements for the specific tool risk level are not met.
- **Path Validation:** All file-system interactions are validated using `llm_cli/security/path_validator.py`, preventing directory traversal and enforcing `allowed_paths`/`blocked_paths` defined in configuration.

## 4. System & Reasoning Integrity
- **Reasoning Sentinel:** Managed by `ReasoningSentinelManager` (in `llm_cli/security/integrity.py`), which tracks "Trust Trends" during a session.
- **File Integrity:** `IntegrityVerifier` uses a signed manifest (`integrity_manifest.json`) to detect tampering of critical application files.
- **Audit Anchoring:** Audit logs are chained with hashes and signed with PQC. `AuditAnchoring` facilitates Merkle Tree root generation for external anchoring, preventing historical revisionism.

## 5. Sandboxing & Safe Tool Execution
- **Python Execution:** The `execute_python` tool (`llm_cli/modules/tools/interpreter.py`) is governed by:
    1. **Static Analysis:** `llm_cli/security/static_analyzer.py` checks for dangerous imports and calls before execution.
    2. **Policy Engine:** Verifies the execution context and PQC tokens.
    3. **CASS Escalation:** Riskier code patterns or high sentinel anomaly scores trigger mandatory user review even if `skip_approval` is set.
- **Output Truncation:** Prevents "Denial of Wallet" or buffer overflow attacks by strictly enforcing `max_output_length` in `tool_executor.py`.

## 6. Zero-Trust Security Configuration (defaults.toml)

Security behavior is externalized in `llm_cli/apps/defaults.toml`:

```toml
[security]
# Resource Attributes
allowed_paths = ["."]
blocked_paths = ["/etc", "/var", "/root", "~/.ssh"]

# Risk Level Classification
high_risk_tools = ["execute_python", "edit_file", "create_or_overwrite_file"]
medium_risk_tools = ["read_file_content", "list_files_in_directory", "search_files"]

# PQC Enforcement Mode: "warn" or "strict_block"
pqc_enforcement = "warn"

# Static Analysis
static_analysis_is_error = true

[sentinel]
enabled = true
mode = "learn" # "learn" or "enforce"
```

## Summary
By combining PQC-based identity verification, Mamba-based real-time behavior monitoring, and a strict ABAC policy engine, `llm_cli` ensures that agents operate within safe boundaries even when handling sensitive system resources.
