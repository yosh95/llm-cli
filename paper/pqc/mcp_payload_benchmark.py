import json
import time
import base64
import hashlib
import sys

# Simulate PQC Key Sizes and Latency based on NIST submissions
# ML-DSA-44 (Dilithium2) is the recommended parameter set for most applications

def generate_mock_bytes(size: int) -> bytes:
    return b'A' * size

class ClassicalRSA2048:
    def __init__(self):
        self.pub_size = 256
        self.priv_size = 1192
        self.sig_size = 256
        self.keygen_ms = 2.5
        self.sign_ms = 1.2
        self.verify_ms = 0.1

    def sign(self, data: bytes) -> bytes:
        time.sleep(self.sign_ms / 1000.0)
        return generate_mock_bytes(self.sig_size)

    def verify(self, data: bytes, signature: bytes) -> bool:
        time.sleep(self.verify_ms / 1000.0)
        return len(signature) == self.sig_size

class MLDSA44:
    def __init__(self):
        self.pub_size = 1312
        self.priv_size = 2560
        self.sig_size = 2420
        self.keygen_ms = 0.1
        self.sign_ms = 0.3
        self.verify_ms = 0.1

    def sign(self, data: bytes) -> bytes:
        time.sleep(self.sign_ms / 1000.0)
        return generate_mock_bytes(self.sig_size)

    def verify(self, data: bytes, signature: bytes) -> bool:
        time.sleep(self.verify_ms / 1000.0)
        return len(signature) == self.sig_size

def create_mcp_payload(tool_name: str, args: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args
        },
        "id": 1
    }

def run_protocol_benchmark():
    print("=== AI Agent MCP Security Protocol Benchmark ===")
    
    payload = create_mcp_payload("execute_shell_command", {"command": "ls -la"})
    payload_bytes = json.dumps(payload).encode('utf-8')
    base_payload_size = len(payload_bytes)
    print(f"Base MCP JSON-RPC Payload Size: {base_payload_size} bytes")
    
    rsa = ClassicalRSA2048()
    mldsa = MLDSA44()
    
    # Measure RSA
    t0 = time.time()
    rsa_sig = rsa.sign(payload_bytes)
    t1 = time.time()
    rsa_verify = rsa.verify(payload_bytes, rsa_sig)
    t2 = time.time()
    
    rsa_token = {
        "alg": "RS256",
        "payload": payload,
        "signature": base64.b64encode(rsa_sig).decode('utf-8')
    }
    rsa_total_size = len(json.dumps(rsa_token))
    
    # Measure ML-DSA
    t3 = time.time()
    mldsa_sig = mldsa.sign(payload_bytes)
    t4 = time.time()
    mldsa_verify = mldsa.verify(payload_bytes, mldsa_sig)
    t5 = time.time()
    
    mldsa_token = {
        "alg": "ML-DSA-44",
        "payload": payload,
        "signature": base64.b64encode(mldsa_sig).decode('utf-8')
    }
    mldsa_total_size = len(json.dumps(mldsa_token))
    
    # Measure Hybrid (RSA + ML-DSA)
    hybrid_token = {
        "alg": "Hybrid-RSA-MLDSA",
        "payload": payload,
        "signatures": {
            "rsa": base64.b64encode(rsa_sig).decode('utf-8'),
            "mldsa": base64.b64encode(mldsa_sig).decode('utf-8')
        }
    }
    hybrid_total_size = len(json.dumps(hybrid_token))

    print("\n--- Network Transmission Overhead ---")
    print(f"RSA-Signed Payload Size:    {rsa_total_size:>5} bytes")
    print(f"ML-DSA-Signed Payload Size: {mldsa_total_size:>5} bytes ({(mldsa_total_size/rsa_total_size):.2f}x increase)")
    print(f"Hybrid-Signed Payload Size: {hybrid_total_size:>5} bytes ({(hybrid_total_size/rsa_total_size):.2f}x increase)")
    
    print("\n--- Agentic Loop Latency (Signing + Verification) ---")
    rsa_latency = (t2 - t0) * 1000
    mldsa_latency = (t5 - t3) * 1000
    print(f"RSA-2048 Latency:  {rsa_latency:>6.2f} ms")
    print(f"ML-DSA-44 Latency: {mldsa_latency:>6.2f} ms")
    print("Note: ML-DSA signature generation is typically 3-4x faster than RSA-2048.")
    
    print("\n--- LLM Context Window Impact ---")
    print("If the raw protocol payload is inadvertently fed back into the LLM history (e.g., poorly configured agent framework):")
    tokens_rsa = rsa_total_size / 4  # rough estimate: 1 token ~= 4 chars
    tokens_mldsa = mldsa_total_size / 4
    print(f"Token Consumption per Tool Call (RSA):    ~{int(tokens_rsa)} tokens")
    print(f"Token Consumption per Tool Call (ML-DSA): ~{int(tokens_mldsa)} tokens")
    print(f"Conclusion: Critical to strip signatures ('.signatures' key) before appending MCP tool results to the LLM context to prevent rapid context exhaustion.")

if __name__ == "__main__":
    run_protocol_benchmark()
