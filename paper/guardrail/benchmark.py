import math
import subprocess
import time
from statistics import mean


def calculate_shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    entropy = 0.0
    for x in range(256):
        p_x = data.count(chr(x)) / len(data)
        if p_x > 0:
            entropy += -p_x * math.log2(p_x)
    return entropy


def measure_entropy_latency(iterations: int = 100) -> float:
    sample_text = (
        "Standard user prompt with some random looking API_KEY_LIKE_STRING_12345" * 10
    )
    latencies = [
        (
            start := time.perf_counter(),
            calculate_shannon_entropy(sample_text),
            time.perf_counter() - start,
        )[2]
        * 1000
        for _ in range(iterations)
    ]
    return mean(latencies)


def measure_sandbox_overhead(iterations: int = 10) -> tuple[float, float]:
    base_cmd = ["python3", "-c", "print('hello')"]
    base_latencies = [
        (
            start := time.perf_counter(),
            subprocess.run(base_cmd, capture_output=True),
            time.perf_counter() - start,
        )[2]
        * 1000
        for _ in range(iterations)
    ]

    bwrap_latencies = []
    has_bwrap = subprocess.run(["which", "bwrap"], capture_output=True).returncode == 0
    if has_bwrap:
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
        bwrap_latencies = [
            (
                start := time.perf_counter(),
                subprocess.run(bwrap_cmd, capture_output=True),
                time.perf_counter() - start,
            )[2]
            * 1000
            for _ in range(iterations)
        ]
    return mean(base_latencies), mean(bwrap_latencies) if has_bwrap else 0.0


def run_benchmark() -> None:
    print("=== Phase 1: Guardrail Performance ===")
    print(f"Entropy Scan: {measure_entropy_latency():.4f} ms")
    base, bwrap = measure_sandbox_overhead()
    print(f"Base Exec:    {base:.2f} ms")
    if bwrap:
        print(f"Bwrap Exec:   {bwrap:.2f} ms (Overhead: {bwrap - base:.2f} ms)")


if __name__ == "__main__":
    run_benchmark()
