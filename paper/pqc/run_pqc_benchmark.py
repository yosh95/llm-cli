import json
import time
from statistics import mean
from typing import Any

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87


def measure_rsa_2048(payload: dict, iterations: int = 50) -> dict:
    # Keygen
    start = time.perf_counter()
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    keygen_ms = (time.perf_counter() - start) * 1000

    # Sign (JWT encode)
    sign_times = []
    token = ""
    for _ in range(iterations):
        start = time.perf_counter()
        token = jwt.encode(payload, private_key, algorithm="RS256")
        sign_times.append((time.perf_counter() - start) * 1000)

    # Verify (JWT decode)
    public_key = private_key.public_key()
    verify_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        jwt.decode(token, public_key, algorithms=["RS256"])
        verify_times.append((time.perf_counter() - start) * 1000)

    return {
        "keygen_ms": keygen_ms,
        "sign_ms": mean(sign_times),
        "verify_ms": mean(verify_times),
        "sig_size": 256,  # Approx for RS256
    }


def measure_ml_dsa(variant_class: Any, payload_bytes: bytes, iterations: int = 50) -> dict:
    # Keygen
    start = time.perf_counter()
    pk, sk = variant_class.keygen()
    keygen_ms = (time.perf_counter() - start) * 1000

    # Sign
    sign_times = []
    sig = b""
    for _ in range(iterations):
        start = time.perf_counter()
        sig = variant_class.sign(sk, payload_bytes)
        sign_times.append((time.perf_counter() - start) * 1000)

    # Verify
    verify_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        variant_class.verify(pk, payload_bytes, sig)
        verify_times.append((time.perf_counter() - start) * 1000)

    return {
        "keygen_ms": keygen_ms,
        "sign_ms": mean(sign_times),
        "verify_ms": mean(verify_times),
        "sig_size": len(sig),
        "pub_size": len(pk),
    }


def create_mcp_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "secret.txt"}},
        "id": 1,
    }


def run_comprehensive_benchmark() -> None:
    print("==================================================================")
    print("   AI Agent MCP Security Benchmark: Post-Quantum Comparison      ")
    print("   (Live Measurement using dilithium-py and cryptography)        ")
    print("==================================================================")

    payload = create_mcp_payload()
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode("utf-8")
    base_size = len(payload_bytes)

    iterations = 20  # Reduced for speed in pure Python env

    print(f"Base MCP Payload Size: {base_size} bytes")
    print("-" * 75)
    print(
        f"{'Algorithm':<12} | {'Sign (ms)':<10} | {'Verify (ms)':<11} | "
        f"{'Sig Size':<8} | {'Tokens (Est)'}"
    )
    print("-" * 75)

    # Classical RSA-2048 baseline
    rsa_res = measure_rsa_2048(payload, iterations)
    rsa_token_est = (base_size + (rsa_res["sig_size"] * 1.33)) / 4
    print(
        f"{'RSA-2048':<12} | {rsa_res['sign_ms']:<10.2f} | "
        f"{rsa_res['verify_ms']:<11.2f} | "
        f"{rsa_res['sig_size']:<8} | ~{int(rsa_token_est)}"
    )

    # ML-DSA Variants
    variants = [
        ("ML-DSA-44", ML_DSA_44),
        ("ML-DSA-65", ML_DSA_65),
        ("ML-DSA-87", ML_DSA_87),
    ]

    for name, v_class in variants:
        res = measure_ml_dsa(v_class, payload_bytes, iterations)
        # B64 inflation factor ~1.33
        token_est = (base_size + (res["sig_size"] * 1.33)) / 4

        print(
            f"{name:<12} | {res['sign_ms']:<10.2f} | {res['verify_ms']:<11.2f} | "
            f"{res['sig_size']:<8} | ~{int(token_est)}"
        )

    print("-" * 75)
    print("\n[Security Strategy Analysis]")
    print(
        "1. Hybrid Approach (RSA + PQC): Recommended for production to maintain "
        "backwards compatibility while ensuring future-proofing."
    )
    print("2. ML-DSA-65: Optimal balance of performance and security (NIST Level 3).")

    print("\n[Audit-Chain Performance Note]")
    print(
        "With PQC-Audit-Chain enabled, each log entry adds the PQC 'Sign (ms)' "
        "overhead to tool execution. In pure Python, this is significant (~50-100ms)."
    )


if __name__ == "__main__":
    run_comprehensive_benchmark()
