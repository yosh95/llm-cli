import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from llm_cli.security.pqc import PQCProvider


def benchmark_real_crypto():
    print("=== Real-World Crypto Benchmark for llm-cli ===")

    # 1. ML-DSA-65 (Real Implementation)
    print("Measuring ML-DSA-65 (dilithium-py)...")
    t0 = time.time()
    pk_pqc, sk_pqc = PQCProvider.generate_keypair()
    t_keygen_pqc = (time.time() - t0) * 1000

    msg = b"Model Context Protocol Payload for PQC Benchmarking"

    t0 = time.time()
    sig_pqc = PQCProvider.sign(msg, sk_pqc)
    t_sign_pqc = (time.time() - t0) * 1000

    t0 = time.time()
    is_valid_pqc = PQCProvider.verify(msg, sig_pqc, pk_pqc)
    t_verify_pqc = (time.time() - t0) * 1000

    # 2. RSA-2048 (Standard Cryptography)
    print("Measuring RSA-2048 (cryptography library)...")
    t0 = time.time()
    priv_rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_rsa = priv_rsa.public_key()
    t_keygen_rsa = (time.time() - t0) * 1000

    t0 = time.time()
    sig_rsa = priv_rsa.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256(),
    )
    t_sign_rsa = (time.time() - t0) * 1000

    t0 = time.time()
    try:
        pub_rsa.verify(
            sig_rsa,
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256(),
        )
        is_valid_rsa = True
    except:
        is_valid_rsa = False
    t_verify_rsa = (time.time() - t0) * 1000

    print("\n--- RESULTS ---")
    print("Metric              | RSA-2048             | ML-DSA-65")
    print("--------------------|----------------------|-------------------")
    print(f"KeyGen (ms)         | {t_keygen_rsa:>20.2f} | {t_keygen_pqc:>17.2f}")
    print(f"Sign (ms)           | {t_sign_rsa:>20.2f} | {t_sign_pqc:>17.2f}")
    print(f"Verify (ms)         | {t_verify_rsa:>20.2f} | {t_verify_pqc:>17.2f}")
    print(f"Sig Size (bytes)    | {len(sig_rsa):>20} | {len(sig_pqc):>17}")
    print(
        f"PK Size (bytes)     | {pub_rsa.public_numbers().n.bit_length() // 8:>20} | {len(pk_pqc):>17}"
    )


if __name__ == "__main__":
    try:
        benchmark_real_crypto()
    except ImportError as e:
        print(f"Error: Required library not found: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
