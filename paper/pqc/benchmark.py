import time
from statistics import mean

from dilithium_py.ml_dsa import ML_DSA_65
from kyber_py.ml_kem import ML_KEM_768


def measure_pqc_latency(iterations: int = 10) -> tuple[float, float, float, float]:
    # ML-DSA-65
    pk_d, sk_d = ML_DSA_65.keygen()
    msg = b"MCP Tool Call Request"
    sig = ML_DSA_65.sign(sk_d, msg)
    s_d = [
        (t := time.perf_counter(), ML_DSA_65.sign(sk_d, msg), time.perf_counter() - t)[
            2
        ]
        * 1000
        for _ in range(iterations)
    ]
    v_d = [
        (
            t := time.perf_counter(),
            ML_DSA_65.verify(pk_d, msg, sig),
            time.perf_counter() - t,
        )[2]
        * 1000
        for _ in range(iterations)
    ]

    # ML-KEM-768
    pk_k, sk_k = ML_KEM_768.keygen()
    ss, ct = ML_KEM_768.encaps(pk_k)
    e_k = [
        (t := time.perf_counter(), ML_KEM_768.encaps(pk_k), time.perf_counter() - t)[2]
        * 1000
        for _ in range(iterations)
    ]
    d_k = [
        (
            t := time.perf_counter(),
            ML_KEM_768.decaps(sk_k, ct),
            time.perf_counter() - t,
        )[2]
        * 1000
        for _ in range(iterations)
    ]

    return mean(s_d), mean(v_d), mean(e_k), mean(d_k)


def run_benchmark() -> None:
    print("=== Phase 3: Post-Quantum Performance ===")
    sd, vd, ek, dk = measure_pqc_latency()
    print(f"ML-DSA-65 Sign:   {sd:.2f} ms")
    print(f"ML-DSA-65 Verify: {vd:.2f} ms")
    print(f"ML-KEM-768 Encaps: {ek:.2f} ms")
    print(f"ML-KEM-768 Decaps: {dk:.2f} ms")


if __name__ == "__main__":
    run_benchmark()
