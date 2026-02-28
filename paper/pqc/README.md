# Post-Quantum Cryptography (PQC) for AI Agents

This directory contains research papers, architecture diagrams, and benchmarking tools for implementing Post-Quantum Cryptography (PQC) within the Model Context Protocol (MCP) and AI agent workflows.

## Contents

- `pqc_in_ai_agents.tex`: Main research paper focusing on ML-DSA (Dilithium) integration in AI agents.
- `pqc_architecture.tex`: TikZ-based architecture diagram showing the "Signature Stripping" mechanism and Zero-Trust boundaries.
- `mcp_payload_benchmark.py`: A simulation tool to measure network overhead and token consumption of PQC-signed MCP messages.
- `run_pqc_benchmark.py`: A comprehensive benchmark script comparing ML-DSA-44, 65, and 87.

## Key Concepts

### 1. Hybrid PQC-Classical Tokens
To ensure backward compatibility during the quantum transition, we use a 4-slot token format:
`[Header].[Payload].[Classical Signature (RSA/ECDSA)].[PQC Signature (ML-DSA)]`

### 2. Signature Stripping
PQC signatures (3.5KB - 4.6KB) are significantly larger than classical ones. If these are fed back into an LLM's context window, they cause "Context Exhaustion." This tool implements a middleware that strips cryptographic metadata before updating the agent's memory.

### 3. PQC-Audit-Chain
Every action taken by the agent is cryptographically linked to its previous state using ML-DSA, ensuring that the history of autonomous decisions cannot be retroactively tampered with by quantum-capable adversaries.

## Benchmarking Results (Summary)

| Metric | RSA-2048 | ML-DSA-44 | ML-DSA-65 | ML-DSA-87 |
| :--- | :--- | :--- | :--- | :--- |
| Security Level | Classical | Level 2 | Level 3 | Level 5 |
| Signature Size | 256 B | 2,420 B | 3,309 B | 4,595 B |
| Token Bloat | 1.0x | 7.5x | 9.4x | 12.0x |
| Latency Impact | Minimal | ~64ms | ~92ms | ~135ms |

*Note: Latency is based on pure-Python implementations. Native C/Rust implementations are expected to be <1ms.*

## Standards Compliance
- **FIPS 204**: Module-Lattice-Based Digital Signature Standard (ML-DSA).
- **NIST SP 800-207**: Zero Trust Architecture principles.
