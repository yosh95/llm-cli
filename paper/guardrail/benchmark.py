import ast
import math
import subprocess
import time
from collections import Counter
from statistics import mean

# Attempt to import LLM-CLI security modules for realistic measurement
try:
    from llm_cli.security.static_analyzer import analyze_python_safety

    HAS_LLM_CLI = True
except ImportError:
    HAS_LLM_CLI = False


def calculate_shannon_entropy(data: bytes) -> float:
    """Calculates Shannon entropy of the given byte data."""
    if not data:
        return 0.0
    counter = Counter(data)
    len_data = len(data)
    entropy = 0.0
    for count in counter.values():
        p = count / len_data
        entropy -= p * math.log2(p)
    return entropy


def measure_ast_latency(iterations: int = 100) -> float:
    """Measures latency of AST parsing or static analysis."""
    sample_code = """
import os
import sys

def malicious_function():
    os.system("rm -rf /")
    eval("print('hello')")

for i in range(10):
    print(i)
"""
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        if HAS_LLM_CLI:
            analyze_python_safety(sample_code)
        else:
            # Fallback to simple parse if llm_cli not found
            ast.parse(sample_code)
        latencies.append((time.perf_counter() - start) * 1000)
    return mean(latencies)


def measure_entropy_latency(iterations: int = 100) -> float:
    """Measures latency of entropy calculation for secret detection."""
    sample_text = (
        "Standard user prompt with some random looking API_KEY_LIKE_STRING_12345" * 10
    )
    sample_bytes = sample_text.encode("utf-8")
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        calculate_shannon_entropy(sample_bytes)
        latencies.append((time.perf_counter() - start) * 1000)
    return mean(latencies)


def measure_sandbox_overhead(iterations: int = 10) -> tuple[float, float]:
    """Measures OS-level sandboxing overhead using bubblewrap."""
    base_cmd = ["python3", "-c", "print('hello')"]
    base_latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        subprocess.run(base_cmd, capture_output=True)
        base_latencies.append((time.perf_counter() - start) * 1000)

    bwrap_latencies = []
    has_bwrap = subprocess.run(["which", "bwrap"], capture_output=True).returncode == 0
    if has_bwrap:
        # Simple bwrap command with necessary mounts
        bwrap_cmd = [
            "bwrap",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--unshare-all",
            "python3",
            "-c",
            "print('hello')",
        ]
        for _ in range(iterations):
            start = time.perf_counter()
            subprocess.run(bwrap_cmd, capture_output=True)
            bwrap_latencies.append((time.perf_counter() - start) * 1000)

    return mean(base_latencies), mean(bwrap_latencies) if has_bwrap else 0.0


def run_benchmark() -> None:
    """Runs all benchmark suites and prints results."""
    print("=== Phase 1: Guardrail Performance Measurement ===")

    ast_lat = measure_ast_latency()
    print(f"AST Analysis: {ast_lat:.4f} ms")

    ent_lat = measure_entropy_latency()
    print(f"Entropy Scan: {ent_lat:.4f} ms")

    base, bwrap = measure_sandbox_overhead()
    print(f"Base Exec:    {base:.2f} ms")
    if bwrap:
        print(f"Bwrap Exec:   {bwrap:.2f} ms (Overhead: {bwrap - base:.2f} ms)")
    else:
        print("Bwrap Exec:   N/A (bubblewrap not found or execution failed)")


if __name__ == "__main__":
    run_benchmark()
