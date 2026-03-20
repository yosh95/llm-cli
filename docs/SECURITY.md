# Security Implementation & Zero-Trust Architecture

`llm_cli` is designed with a "Zero-Trust" security model for agentic workflows. This document maps the security claims to their specific implementations.

## 1. Post-Quantum Cryptography (PQC)
- **Mechanism:** Dual-layer encryption and digital signatures using NIST-compliant algorithms (ML-DSA / Dilithium).
- **Implementation:** `llm_cli/security/pqc.py`.
- **Logic:** Sensitive operations (like Python execution or file modification) can be configured to require a PQC-signed token or RBAC verification.
- **Dynamic Escalation:** Security levels are escalated based on `scaling_patterns` defined in `llm_cli/apps/defaults.toml`.

## 2. Dynamic Guardrails: Real-time Anomaly Detection (Mamba Sentinel)
- **Mechanism:** A high-speed State Space Model (Mamba SSM) monitors the model's reasoning process in real-time to detect intent deviation or manipulation attempts.
- **Implementation:** `llm_cli/security/sentinel.py` and `llm_cli/mamba_core/`.
- **Logic:** Replaces slow Dual-LLM intent analysis with a sub-millisecond latency check using Prompt Anchoring. Anomalies (high scores) trigger automatic security escalation (e.g., forcing manual approval or blocking execution).

## 3. RBAC & ABAC Policy Engine
- **Mechanism:** Role-Based Access Control (RBAC) and Attribute-Based Access Control (ABAC) determine which tools and resource scopes (e.g., paths) are accessible.
- **Implementation:** `llm_cli/security/policy.py`.
- **Dynamic Policy:** Roles (`admin`, `user`, `guest`) and their scopes are externalized in `llm_cli/apps/defaults.toml`, allowing "No-Code" security configuration.
- **Path Validation:** All file-system interactions are validated against `allowed_paths` using `llm_cli/security/path_validator.py`.

## 4. Reasoning Integrity (Sentinel)
- **Mechanism:** Monitoring the reasoning/thought process of the LLM to detect signs of manipulation, jailbreak attempts, or "hallucinated" security bypasses.
- **Implementation:** `llm_cli/security/integrity.py`.
- **Sentinel Manager:** `ReasoningSentinelManager` (in `llm_cli/clients/session.py`) scores each turn for integrity.

## 5. Sandboxing & Safe Tool Execution
- **Python Execution:** `execute_python` tool (in `llm_cli/modules/tool_registry.py`) is governed by the Policy Engine and Mamba Sentinel.
- **Path Sanitization:** `validate_path` ensures tools cannot escape authorized directories (e.g., via directory traversal).

## 6. Zero-Trust Security Configuration (defaults.toml)

Example security section in `defaults.toml`:

```toml
[security]
blocked_paths = ["/etc/shadow", "/etc/passwd", "~/.ssh/id_rsa"]

# Tool risk levels
high_risk_tools = ["execute_python", "edit_file", "create_or_overwrite_file"]
medium_risk_tools = ["read_file_content", "list_files_in_directory", "search_files", "search_web", "read_url_content"]

# Dynamic scaling patterns for PQC security escalation.
scaling_patterns = [
    ".ssh/",
    ".env",
    "config",
    "credential",
    "password",
    "sudo",
    "rm -rf"
]

[security.roles.user]
```

## Summary
The combination of PQC signatures, Mamba-based real-time anomaly detection, and a robust policy engine ensures that `llm_cli` can safely execute complex tasks while maintaining strict control over system resources.
