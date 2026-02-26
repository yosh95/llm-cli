import base64
import json
import time

# Simulate PQC Key Sizes and Latency based on NIST submissions
# ML-DSA-44 (Dilithium2) is the recommended parameter set for most applications


def generate_mock_bytes(size: int) -> bytes:
    return b"A" * size


class ClassicalRSA2048:
    def __init__(self) -> None:
        self.pub_size = 256
        self.priv_size = 1192
        self.sig_size = 256
        self.keygen_ms = 2.5
        self.sign_ms = 1.2
        self.verify_ms = 0.1

    def sign(self, _data: bytes) -> bytes:
        time.sleep(self.sign_ms / 1000.0)
        return generate_mock_bytes(self.sig_size)

    def verify(self, _data: bytes, signature: bytes) -> bool:
        time.sleep(self.verify_ms / 1000.0)
        return bool(len(signature) == self.sig_size)


class MLDSA65:
    """NIST ML-DSA-65 (Security Level 3) implementation characteristics."""

    def __init__(self) -> None:
        self.pub_size = 1952
        self.priv_size = 4032
        self.sig_size = 3309
        self.keygen_ms = 0.15
        self.sign_ms = 0.55
        self.verify_ms = 0.12

    def sign(self, _data: bytes) -> bytes:
        time.sleep(self.sign_ms / 1000.0)
        return generate_mock_bytes(self.sig_size)

    def verify(self, _data: bytes, signature: bytes) -> bool:
        time.sleep(self.verify_ms / 1000.0)
        return bool(len(signature) == self.sig_size)


def create_mcp_payload(tool_name: str, args: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
        "id": 1,
    }


def run_protocol_benchmark() -> None:
    print("=== AI Agent MCP Security Protocol Benchmark (ML-DSA-65) ===")

    payload = create_mcp_payload("execute_shell_command", {"command": "ls -la"})
    payload_bytes = json.dumps(payload).encode("utf-8")
    base_payload_size = len(payload_bytes)
    print(f"Base MCP JSON-RPC Payload Size: {base_payload_size} bytes")

    rsa = ClassicalRSA2048()
    mldsa = MLDSA65()

    # Measure RSA
    t0 = time.time()
    rsa_sig = rsa.sign(payload_bytes)
    rsa.verify(payload_bytes, rsa_sig)
    t2 = time.time()

    # Classical JWT simulation (header.payload.signature)
    rsa_token_str = f"header.payload.{base64.b64encode(rsa_sig).decode('utf-8')}"
    rsa_total_size = len(rsa_token_str)

    # Measure ML-DSA
    t3 = time.time()
    mldsa_sig = mldsa.sign(payload_bytes)
    mldsa.verify(payload_bytes, mldsa_sig)
    t5 = time.time()

    # PQC-only token simulation
    mldsa_token_str = f"header.payload.{base64.b64encode(mldsa_sig).decode('utf-8')}"
    mldsa_total_size = len(mldsa_token_str)

    # Measure Hybrid (RSA + ML-DSA) as implemented in llm-cli
    # Format: header.payload.sig.pqc_sig
    hybrid_token_str = f"{rsa_token_str}.{base64.b64encode(mldsa_sig).decode('utf-8')}"
    hybrid_total_size = len(hybrid_token_str)

    print("\n--- Network Transmission Overhead (Serialized Tokens) ---")
    print(f"Classical JWT Size:         {rsa_total_size:>5} bytes")
    print(
        f"ML-DSA-65 Token Size:       {mldsa_total_size:>5} bytes "
        f"({(mldsa_total_size / rsa_total_size):.2f}x increase)"
    )
    print(
        f"Hybrid (4-Slot) Token Size: {hybrid_total_size:>5} bytes "
        f"({(hybrid_total_size / rsa_total_size):.2f}x increase)"
    )

    print("\n--- Agentic Loop Latency (Signing + Verification) ---")
    rsa_latency = (t2 - t0) * 1000
    mldsa_latency = (t5 - t3) * 1000
    print(f"RSA-2048 Latency:  {rsa_latency:>6.2f} ms")
    print(f"ML-DSA-65 Latency: {mldsa_latency:>6.2f} ms")
    print("Note: ML-DSA signature generation is significantly faster than RSA-2048.")

    print("\n--- LLM Context Window Impact ---")
    print("If the raw protocol payload is inadvertently fed back into the LLM history:")
    tokens_rsa = rsa_total_size / 4
    tokens_hybrid = hybrid_total_size / 4
    print(f"Token Consumption (Classical): ~{int(tokens_rsa)} tokens")
    print(f"Token Consumption (Hybrid):    ~{int(tokens_hybrid)} tokens")
    print(
        "Conclusion: Critical to strip the .signature and .pqc_signature fields "
        "before appending results to LLM context."
    )


if __name__ == "__main__":
    run_protocol_benchmark()
