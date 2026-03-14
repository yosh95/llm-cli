import time
from statistics import mean

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

from llm_cli.security.sentinel import MambaSentinel


def measure_identity_latency(iterations: int = 20) -> tuple[float, float]:
    priv = rsa.generate_private_key(65537, 2048, default_backend())
    pub = priv.public_key()
    payload = {"sub": "agent-01", "iat": time.time()}
    token = jwt.encode(payload, priv, algorithm="RS256")
    s = [
        (
            t := time.perf_counter(),
            jwt.encode(payload, priv, algorithm="RS256"),
            time.perf_counter() - t,
        )[2]
        * 1000
        for _ in range(iterations)
    ]
    v = [
        (
            t := time.perf_counter(),
            jwt.decode(token, pub, algorithms=["RS256"]),
            time.perf_counter() - t,
        )[2]
        * 1000
        for _ in range(iterations)
    ]
    return mean(s), mean(v)


def measure_mamba_latency(iterations: int = 20) -> float:
    sentinel = MambaSentinel(mode="detect")
    data = (
        b"The agent is planning to read file 'secret.txt'. "
        b"This might be an injection attempt."
    )
    latencies = [
        (t := time.perf_counter(), sentinel.analyze(data), time.perf_counter() - t)[2]
        * 1000
        for _ in range(iterations)
    ]
    return mean(latencies)


def run_benchmark() -> None:
    print("=== Phase 2: Zero Trust & IDS Performance ===")
    s, v = measure_identity_latency()
    print(f"Identity Sign:   {s:.4f} ms")
    print(f"Identity Verify: {v:.4f} ms")
    print(f"Mamba Sentinel:  {measure_mamba_latency():.4f} ms / block")


if __name__ == "__main__":
    run_benchmark()
