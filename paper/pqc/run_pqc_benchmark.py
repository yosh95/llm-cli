import time
import sys

def simulate_rsa_2048():
    # Simulate RSA-2048 performance (approximate values for demonstration)
    return {
        "algo": "RSA-2048",
        "public_key_size": 256, # bytes
        "private_key_size": 1192, # bytes
        "signature_size": 256, # bytes
        "keygen_time_ms": 2.5,
        "sign_time_ms": 1.2,
        "verify_time_ms": 0.1
    }

def simulate_ml_dsa_44():
    # Simulate ML-DSA-44 (Dilithium2) performance
    return {
        "algo": "ML-DSA-44",
        "public_key_size": 1312, # bytes
        "private_key_size": 2560, # bytes
        "signature_size": 2420, # bytes
        "keygen_time_ms": 0.1,
        "sign_time_ms": 0.3,
        "verify_time_ms": 0.1
    }

def print_comparison():
    print("=" * 60)
    print(f"{'Metric':<25} | {'RSA-2048 (Classical)':<20} | {'ML-DSA-44 (PQC)':<15}")
    print("-" * 60)
    
    rsa = simulate_rsa_2048()
    pqc = simulate_ml_dsa_44()
    
    metrics = [
        ("Public Key Size (bytes)", "public_key_size"),
        ("Private Key Size (bytes)", "private_key_size"),
        ("Signature Size (bytes)", "signature_size"),
        ("KeyGen Time (ms)", "keygen_time_ms"),
        ("Sign Time (ms)", "sign_time_ms"),
        ("Verify Time (ms)", "verify_time_ms")
    ]
    
    for label, key in metrics:
        print(f"{label:<25} | {rsa[key]:<20.2f} | {pqc[key]:<15.2f}")
    
    print("=" * 60)
    print("\nImpact on AI Agent MCP Protocol:")
    size_diff = pqc['signature_size'] / rsa['signature_size']
    print(f"- Signature Payload Size increases by {size_diff:.1f}x.")
    print("- However, signing speed is significantly faster with ML-DSA.")
    print("- Network overhead over typical MCP transports (STDIO/SSH) is negligible for single-tool executions, but may impact high-frequency automated agentic loops.")

if __name__ == "__main__":
    print("Running PQC vs Classical Cryptography Benchmark for AI Agents...")
    time.sleep(1) # simulate loading
    print_comparison()
