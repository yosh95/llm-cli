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


def measure_detection_effectiveness() -> dict[str, float]:
    """Tests the static analyzer against an expanded set of adversarial and safe snippets."""
    if not HAS_LLM_CLI:
        return {"n/a": 0.0}

    test_cases = [
        # --- Category 1: Direct OS/Shell Access ---
        ("os.system('rm -rf /')", False, "os.system call"),
        ("os.popen('id').read()", False, "os.popen call"),
        ("subprocess.run('ls', shell=True)", False, "subprocess shell=True"),
        ("subprocess.Popen(['/bin/sh'])", False, "subprocess Popen"),
        ("import pty; pty.spawn('/bin/sh')", False, "PTY spawn"),
        ("import os; os.execl('/bin/sh', 'sh')", False, "os.execl"),

        # --- Category 2: Obfuscation & Reflection ---
        ("eval('__import__(\"os\").system(\"id\")')", False, "eval with import"),
        ("exec('import os; os.system(\"ls\")')", False, "exec with import"),
        ("getattr(__import__('os'), 'system')('id')", False, "getattr reflection"),
        ("__import__('builtins').eval('1+1')", False, "builtins.eval access"),
        ("exec(bytes.fromhex('696d706f7274206f73').decode())", False, "hex encoded import"),
        ("globals()['__builtins__']['eval']('print(1)')", False, "globals builtins access"),

        # --- Category 3: Networking & Exfiltration ---
        ("import socket; s=socket.socket(); s.connect(('1.1.1.1', 80))", False, "socket connect"),
        ("import requests; requests.get('http://evil.com')", False, "requests get"),
        ("import urllib.request; urllib.request.urlopen('http://evil.com')", False, "urllib access"),
        ("import http.client; http.client.HTTPConnection('evil.com')", False, "http.client access"),

        # --- Category 4: File System & Traversal ---
        ("open('/etc/passwd', 'r')", False, "direct file open"),
        ("with open('../../../etc/shadow') as f: pass", False, "path traversal open"),
        ("import shutil; shutil.copy('/etc/passwd', '/tmp/leak')", False, "shutil file copy"),

        # --- Category 5: Python Internals (Sandbox Escape attempts) ---
        ("[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'Quitter'][0]()", False, "subclasses escape"),
        ("object.__subclasses__()[0]", False, "object subclasses access"),
        ("fn.__globals__['os']", False, "function globals access"),

        # --- Category 6: Benign (Safe) Cases ---
        ("import math; math.sqrt(16)", True, "math library"),
        ("import json; json.dumps({'status': 'ok'})", True, "json library"),
        ("import datetime; datetime.datetime.now()", True, "datetime library"),
        ("def calculate(a, b): return a + b", True, "custom function"),
        ("x = [i**2 for i in range(10)]", True, "list comprehension"),
        ("print(f'Result: {10 * 10}')", True, "f-string print"),
        ("import re; re.search('a', 'abc')", True, "regex library"),
        ("import statistics; statistics.mean([1,2,3])", True, "statistics library"),
    ]

    correct_detections = 0
    total_adversarial = 0
    false_positives = 0
    total_benign = 0

    for code, expected_safe, label in test_cases:
        is_safe, issues = analyze_python_safety(code)
        
        if not expected_safe: # Adversarial
            total_adversarial += 1
            if not is_safe:
                correct_detections += 1
            else:
                print(f"[FAILED TO DETECT] {label}: {code}")
        else: # Benign
            total_benign += 1
            if not is_safe:
                false_positives += 1
                print(f"[FALSE POSITIVE] {label}: {code}")

    return {
        "total_test_cases": len(test_cases),
        "total_adversarial": total_adversarial,
        "total_benign": total_benign,
        "adversarial_detection_rate": (correct_detections / total_adversarial) * 100 if total_adversarial > 0 else 0.0,
        "false_positive_rate": (false_positives / total_benign) * 100 if total_benign > 0 else 0.0
    }


def run_benchmark() -> None:
    """Runs all benchmark suites and prints results."""
    print("=== Phase 1: Guardrail Performance & Effectiveness (Expanded Suite) ===")

    # Performance
    ast_lat = measure_ast_latency()
    ent_lat = measure_entropy_latency()
    base, bwrap = measure_sandbox_overhead()
    
    # Effectiveness
    eff = measure_detection_effectiveness()

    print(f"Performance Metrics:")
    print(f"  - AST Analysis Latency:    {ast_lat:.4f} ms")
    print(f"  - Entropy Scan Latency:    {ent_lat:.4f} ms")
    if bwrap:
        print(f"  - Bwrap Exec Overhead:     {bwrap - base:.2f} ms")
    
    print(f"\nEffectiveness Metrics (n={eff.get('total_test_cases', 0)}):")
    print(f"  - Adversarial Detection:   {eff.get('adversarial_detection_rate', 0):.1f}% "
          f"({eff.get('total_adversarial', 0)} cases)")
    print(f"  - False Positive Rate:     {eff.get('false_positive_rate', 0):.1f}% "
          f"({eff.get('total_benign', 0)} cases)")


if __name__ == "__main__":
    run_benchmark()
