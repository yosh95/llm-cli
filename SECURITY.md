# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ Active  |
| < 1.0   | ❌ EOL     |

---

## Architecture Overview: Triple-Lock Framework

`llm-secure-cli` implements a **Triple-Lock** security framework across three
dimensions — Space, Behavior, and Time — designed for autonomous LLM agents
operating via the Model Context Protocol (MCP).  The central orchestration
engine is **CASS (Context-Adaptive Security Scaling)**, which dynamically
adjusts security posture based on each tool call's risk profile.

```
 Agent Tool Request
        │
        ▼
  ┌─────────────┐
  │    CASS     │  ← Context-Adaptive Security Scaling
  └──┬──┬──┬───┘
     │  │  │
     ▼  ▼  ▼
  T1  T2  T3
Space Beh Time
  │   │   │
  └───┴───┘
       │
       ▼
  Secure Tool Execution
```

---

## Tier 1 — Structural Guardrails (Space)

### AST Static Analysis

Before any generated code is executed, `llm_cli/security/static_analyzer.py`
parses it into an Abstract Syntax Tree and applies a whitelist-based scanner:

| Blocked pattern | Example |
|---|---|
| Dangerous modules | `os`, `socket`, `pty`, `ctypes` |
| Unsafe built-ins | `eval`, `exec`, `compile`, `__import__` |
| Shell invocation | `subprocess.run(…, shell=True)` |
| Reflection APIs | `__subclasses__`, `globals()`, `vars()` |

### Path Guardrails

All file-system operations are resolved against the workspace root (defaults
to `.`).  Symbolic-link traversal is validated.  Paths are normalised to
absolute form before comparison against `allowed_paths` / `blocked_paths`
defined in `defaults.toml`:

```toml
[security]
allowed_paths = ["."]
blocked_paths = ["/etc", "/var", "~/.ssh"]
```

### Resource Limits

OS-level `rlimit` caps cap memory usage and wall-clock execution time for
sandboxed processes.  Output length is enforced by `tool_executor.py` to
prevent Denial-of-Wallet attacks.

### Environment Isolation (MCP)

High-risk tool execution is delegated to remote MCP servers running inside
VMs or Docker containers (Shared-Nothing architecture).  Even if a generated
script bypasses static analysis, any malicious activity is contained within a
disposable, restricted environment with no access to the host's filesystem or
credentials.

**Least-privilege MCP server configuration:**

```toml
[[mcp_servers]]
name   = "ops"
command = "ssh"
args   = ["user@host", "python3", "-m", "llm_cli.apps.mcp_server"]
roles  = ["user"]   # never default to "admin"

[[mcp_servers]]
name    = "github"
command = "docker"
args    = ["run", "--rm", "-i", "--network=none",
           "ghcr.io/github/github-mcp-server:latest"]
roles   = ["guest"]
```

**TCB note:** The server binary / container image and its launch
configuration are part of the Trusted Computing Base.  Pin Docker image
digests and enforce SSH host-key verification.

---

## Tier 2 — Behavioral Zero-Trust (Behavior)

### Workload Identity — Hybrid COSE Tokens (RFC 9052)

Every MCP tool call is accompanied by a cryptographically signed identity
token encoded as a **COSE\_Sign** structure (CBOR tag 98, RFC 9052).

**Native implementation:** The COSE layer is implemented directly using
`cbor2` + `cryptography` — no `pycose` dependency.  This makes custom
algorithm identifiers (ML-DSA alg `−48`, IANA-pending per
*draft-ietf-cose-dilithium*) fully auditable without registry injection.

**Token structure:**

```
COSE_Sign [CBOR tag 98]
├── body_protected   : cbor2.dumps({})
├── unprotected      : {}
├── payload          : cbor2.dumps(claims_dict)
└── signatures
    ├── [0] COSE_Signature   alg = -257  (RS256)
    │       protected   : cbor2.dumps({1: -257})
    │       unprotected : {}
    │       signature   : RSA-PKCS1v15/SHA-256 over Sig_Structure
    └── [1] COSE_Signature   alg = -48   (ML-DSA)
            protected   : cbor2.dumps({1: -48})
            unprotected : {4: b"ML-DSA-65"}   ← kid = variant name (agility)
            signature   : ML-DSA variant over Sig_Structure
```

**Sig\_Structure (RFC 9052 §4.4):**

```python
cbor2.dumps(["Signature", body_protected, sign_protected, b"", payload])
```

**Key files:**
- `llm_cli/security/pqc.py` — `HybridSigner.create_hybrid_token()` /
  `verify_hybrid_token()`
- `llm_cli/security/identity.py` — `IdentityManager.generate_token()` /
  `verify_token()`

**COSE algorithm constants:**

```python
_COSE_ALG_RS256  = -257   # RSASSA-PKCS1-v1_5 + SHA-256  (RFC 9052 §9.1)
_COSE_ALG_MLDSA  = -48    # ML-DSA (IANA pending: draft-ietf-cose-dilithium)
_COSE_HEADER_ALG =  1     # RFC 9052 §3.1
_COSE_SIGN_TAG   = 98     # CBOR tag for COSE_Sign
```

### ABAC Policy Engine

Claims embedded in the COSE payload carry execution-context attributes used
for Attribute-Based Access Control:

| Claim | Description |
|---|---|
| `tool` | Requested tool name |
| `risk_level` | `low` / `medium` / `high` |
| `workspace` | SHA-256 of the current workspace root path |
| `iat` / `exp` | Issued-at / expiry (Unix timestamps) |
| `integrity_attestation` | Signed manifest of core security files |

Remote MCP servers verify the token signature and enforce policy against these
claims.  Risk-level classification in `defaults.toml`:

```toml
[security]
high_risk_tools   = ["execute_python", "edit_file", "create_or_overwrite_file"]
medium_risk_tools = ["read_file_content", "list_files_in_directory", "search_files"]
# All other tools → low risk
```

Implementation: `llm_cli/security/policy.py`.

### Bi-directional Verification (ResponseSigner)

High-risk write tools embed an ML-DSA signature in their return value,
binding the response to a unique `verification_id`.  The `tool_executor`
layer verifies this signature before passing the result to the LLM —
preventing Man-in-the-Middle manipulation of tool outputs.

Implementation: `PQCProvider.sign()` / `ResponseSigner.sign_response()` in
`llm_cli/security/pqc.py`.

### Out-of-Band Key Distribution

Public keys and remote attestation manifests are distributed via an OOB
trusted channel (e.g., MDM, Secure Enclave, or enterprise PKI). This design
eliminates Trust-On-First-Use (TOFU) in production deployments.

A bootstrap mode is available for standalone development environments. 
Simply run `llm-cli-security manifest` to generate the initial manifest.
Once the manifest is generated, all subsequent runs will strictly enforce
integrity against it.

---

## Distributed Zero-Trust (High-Assurance Mode)

In a distributed environment (e.g., Client Agent and Remote MCP Server),
the system shifts to a **Distributed Trust** model designed to eliminate
shared secrets:

1.  **Trusted Directory Model:** Servers store Agent public keys in
    `~/.llm_cli/trusted/<entity_id>/id_pqc_<level>.pub`. There is no sharing
    of private keys between entities.
2.  **Impersonation Resistance:** The Agent ID is fixed to `user@hostname`.
    Removing the ability to override this ID prevents attackers with stolen
    keys from easily spoofing authorized identities on different hosts.
3.  **Automatic Key Generation:** For better UX, keys are automatically
    generated on first run. However, security is enforced at the **Verification
    Layer** — servers will reject any key not explicitly provisioned in their
    `trusted/` directory.
4.  **Blast Radius Containment:** Because keys are not shared, the compromise
    of a remote MCP server does not expose the Agent's private identity key,
    preventing an attacker from impersonating the user in other contexts.
5.  **Mutual Authentication:** Every request/response loop is protected by
    mutual ML-DSA signatures. The Agent verifies the tool output's
    `ResponseSigner` signature using the Server's public key (if trusted),
    while the Server verifies the `IdentityToken` using the Agent's public key.

### Trust Resolution & KMS Integration (Enterprise)

To support large-scale deployments, `llm-secure-cli` abstracts key resolution
through the `TrustResolver` interface (`llm_cli/security/trust.py`). This
allows for seamless transition between local and enterprise trust models:

| Resolver | Storage Mechanism | Use Case |
|---|---|---|
| `LocalTrustResolver` | `~/.llm_cli/trusted/` | Standard / Decentralized |
| `KMSTrustResolver` | Remote KMS API / HSM | Enterprise / Centralized |

### Hardware Sovereignty (TEE-protected PQC)

For environments requiring high-assurance protection of private keys,
the **TEEPQCBackend** (`llm_cli/security/tee_backend.py`) provides a
simulated reference implementation of a Trusted Execution Environment.

When enabled via `IdentityManager.use_tee()`, the system:
1.  Generates PQC keys inside the secure enclave boundary.
2.  **Seals** private keys using hardware-backed master keys before
    storing them on the host filesystem.
3.  Performs all **signing operations** (ML-DSA) inside the enclave,
    ensuring that raw private keys never enter the host's memory space.

---

## Tier 3 — Post-Quantum Resilience (Time)

### PQC Primitives

| Algorithm | NIST FIPS | Security Level | Key / Sig Sizes | Default use |
|---|---|---|---|---|
| ML-DSA-44 | FIPS 204 | Level 2 | pk=1 312 B, sk=2 528 B, sig=2 420 B | Low-risk tools |
| ML-DSA-65 | FIPS 204 | Level 3 | pk=1 952 B, sk=4 032 B, sig=3 293 B | Standard identity |
| ML-DSA-87 | FIPS 204 | Level 5 | pk=2 592 B, sk=4 896 B, sig=4 595 B | High-risk tools |
| ML-KEM-512 | FIPS 203 | Level 1 | pk=800 B, sk=1 632 B, ct=768 B | — |
| ML-KEM-768 | FIPS 203 | Level 3 | pk=1 184 B, sk=2 400 B, ct=1 088 B | Audit encryption |
| ML-KEM-1024 | FIPS 203 | Level 5 | pk=1 568 B, sk=3 168 B, ct=1 568 B | — |

Implementation: `dilithium-py` (ML-DSA) and `kyber-py` (ML-KEM) — pure-Python
FIPS-compliant reference implementations.

### PQC Agility (CASS)

CASS selects the ML-DSA variant based on tool risk at runtime. This agility
applies both to identity tokens and audit signatures. Three physically
separate key pairs are provisioned on disk:

| File | Variant | NIST Level |
|---|---|---|
| `~/.llm_cli/id_pqc_l2.key` | ML-DSA-44 | 2 |
| `~/.llm_cli/id_pqc_l3.key` | ML-DSA-65 | 3 |
| `~/.llm_cli/id_pqc_l5.key` | ML-DSA-87 | 5 |

Implementation: `PQCAgilityManager.get_required_level()` in
`llm_cli/security/pqc.py`.

### Remote Attestation

On startup, the client generates a SHA-256 manifest of six critical security
source files (`identity.py`, `policy.py`, `audit.py`, `pqc.py`,
`static_analyzer.py`, `cass.py`), signed with an ML-DSA key.  Remote servers
verify this manifest to confirm the agent is running an authentic, unmodified
stack.

Rebuild the manifest after any code update:

```bash
llm-cli-security manifest
```

### Audit Chain Continuity

- **Chained hashing** — each log entry includes a SHA-256 of the previous
  entry's hash, creating a tamper-evident chain.
- **Snapshot anchors** — on log rotation, a signed anchor entry records
  `snapshot_prev_hash` and `snapshot_first_hash` to maintain verifiability
  across file boundaries.
- **Merkle Tree anchoring** — a binary Merkle Root is computed over all entries
  on rotation and recorded in the security log.  This root can be submitted
  to an external immutable ledger (blockchain, transparency log) for public
  verification.
- **ML-KEM hybrid encryption** — audit logs are optionally encrypted with
  ML-KEM-768 + AES-256-GCM to guarantee future quantum confidentiality.
  Decrypt with:

  ```bash
  llm-cli-security decrypt-log ~/.llm_cli/audit.jsonl -o decrypted.jsonl
  ```

**Audit log retention:** Back up `audit.jsonl` and its
`*.archive.*.jsonl` files.  Forward to a remote WORM store (SIEM) if
available.

---

## Security Configuration Reference

The primary security configuration is in `llm_cli/apps/defaults.toml`
(overridden by `~/.llm_cli/config.toml`):

```toml
[security]
# Workspace scope
allowed_paths            = ["."]
blocked_paths            = ["/etc", "/var", "/root", "~/.ssh"]

# Risk classification
high_risk_tools          = ["execute_python", "edit_file",
                            "create_or_overwrite_file"]
medium_risk_tools        = ["read_file_content", "list_files_in_directory",
                            "search_files"]

# PQC enforcement: "warn" | "strict_block"
pqc_enforcement          = "warn"

# Static analysis errors block execution
static_analysis_is_error = true
```

---

## Dependency Security

| Package | Purpose | Notes |
|---|---|---|
| `cryptography` ≥ 46.0 | RSA, AES-256-GCM, key serialisation | Rust-backed; monitor upstream advisories |
| `dilithium-py` | ML-DSA (CRYSTALS-Dilithium) | Pure-Python constant-time reference |
| `kyber-py` | ML-KEM (CRYSTALS-Kyber) | Pure-Python reference |
| `cbor2` | CBOR serialisation for COSE tokens | Direct dependency since v1.0.2 |

> **`pycose` removal (v1.0.2):** `pycose` was removed because its internal
> algorithm registry could not accommodate the IANA-pending ML-DSA identifier
> (`alg=−48`) without monkey-patching, and v1.x API changes broke `Signer`
> and `CoseSignature` usage repeatedly.  The replacement is a self-contained
> ~150-line COSE\_Sign implementation using `cbor2` + `cryptography` that is
> fully auditable and stable across library versions.

---

## Known Limitations

1. **ML-DSA COSE algorithm identifier (`alg=−48`)** is not yet formally
   registered with IANA.  The value follows *draft-ietf-cose-dilithium*.
   `_COSE_ALG_MLDSA` in `pqc.py` will be updated when the draft is finalised.

2. **Pure-Python PQC performance** — `dilithium-py` and `kyber-py` are
   significantly slower than native C/Rust bindings (see
   `paper/comprehensive_framework/benchmark.py` for measured numbers).
   On x86-64 (AMD Ryzen 5, WSL2), ML-DSA-65 signing takes ~57 ms (pure-Python);
   native bindings achieve <5 ms. Productions requiring sub-10ms signing
   should evaluate `liboqs`-backed Python bindings. **Note: We prioritize 
   zero-dependency portability (especially for Termux/Android) in the 
   current release. We plan to migrate to `python-cryptography` once 
   NIST-standardized PQC primitives are integrated into its stable release, 
   providing a native performance boost without sacrificing installation 
   simplicity.**

3. **Single RSA key pair** — `IdentityManager` currently uses one RSA-2048
   key pair for classical hybrid signing. However, full cryptographic
   isolation is already achieved at the post-quantum layer through physically
   separate ML-DSA-44/65/87 keys. Classical RSA separation is considered
   a low-priority backlog item given the robust PQC agility implementation.

---

## Production Hardening Roadmap

While the current implementation provides a robust software-defined security
stack, the following steps are recommended for production environments
requiring high-assurance guarantees:

1. **Hardware Sovereignty (TEE):**
   The software logic (especially PQC key management) is now abstracted via 
   `TEEPQCBackend`. This reference implementation demonstrates how to 
   protect private keys using enclave-based sealing and isolated signing 
   memory (e.g., Intel SGX, AWS Nitro).

2. **Formal Cryptographic Audit:**
   The reference implementations of ML-DSA and ML-KEM used in this project
   (`dilithium-py` and `kyber-py`) should undergo a professional third-party
   cryptographic audit before being used to protect high-value assets.

3. **Policy & Retention Configuration:**
   Adjust `max_audit_archives` and `max_audit_log_lines` in the deployment
   `config.toml` to satisfy specific legal (GDPR/CCPA) or regulatory data
   retention requirements.

4. **Hardware Security Modules (HSM) & KMS:**
   Enterprise identity management is now supported via the `TrustResolver` 
   interface. This allows integrating with a centralized KMS (Key Management 
   Service) or HSM for a unified root of trust.

