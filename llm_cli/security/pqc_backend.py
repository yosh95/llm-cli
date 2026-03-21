"""
PQC Backend Abstraction.

This module defines abstract interfaces for Post-Quantum Cryptography backends.
This allows easy swapping between:
- Pure Python reference implementations (current, Termux-friendly)
- python-cryptography (when it adds official PQC support)
- liboqs-python (when actively maintained)

Current default: PurePythonPQCBackend
"""

import importlib.util
from abc import ABC, abstractmethod


class PQCBackend(ABC):
    """Abstract base class for PQC signature backends."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is available in current environment."""
        ...

    @abstractmethod
    def generate_keypair(self, variant: str = "ML-DSA-65") -> tuple[bytes, bytes]:
        """Generate (public_key, private_key) pair."""
        ...

    @abstractmethod
    def sign(
        self, message: bytes, private_key: bytes, variant: str = "ML-DSA-65"
    ) -> bytes:
        """Sign message and return signature."""
        ...

    @abstractmethod
    def verify(
        self,
        message: bytes,
        signature: bytes,
        public_key: bytes,
        variant: str = "ML-DSA-65",
    ) -> bool:
        """Verify signature. Return True if valid."""
        ...


class KEMBackend(ABC):
    """Abstract base class for KEM (Key Encapsulation) backends."""

    @abstractmethod
    def generate_keypair(self, variant: str = "ML-KEM-768") -> tuple[bytes, bytes]:
        """Generate KEM keypair."""
        ...

    @abstractmethod
    def encapsulate(
        self, public_key: bytes, variant: str = "ML-KEM-768"
    ) -> tuple[bytes, bytes]:
        """Return (ciphertext, shared_secret)."""
        ...

    @abstractmethod
    def decapsulate(
        self, ciphertext: bytes, private_key: bytes, variant: str = "ML-KEM-768"
    ) -> bytes:
        """Return shared_secret from ciphertext."""
        ...


class PurePythonPQCBackend(PQCBackend):
    """Current pure Python implementation using dilithium_py and kyber_py."""

    def is_available(self) -> bool:
        """Check if the pure Python PQC backend is available."""
        try:
            return importlib.util.find_spec("dilithium_py") is not None
        except Exception:
            return False

    def generate_keypair(self, variant: str = "ML-DSA-65") -> tuple[bytes, bytes]:
        from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87

        algo_map = {
            "ML-DSA-44": ML_DSA_44,
            "ML-DSA-65": ML_DSA_65,
            "ML-DSA-87": ML_DSA_87,
        }
        algo = algo_map.get(variant, ML_DSA_65)
        return algo.keygen()  # type: ignore[no-any-return]

    def sign(
        self, message: bytes, private_key: bytes, variant: str = "ML-DSA-65"
    ) -> bytes:
        from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87

        algo_map = {
            "ML-DSA-44": ML_DSA_44,
            "ML-DSA-65": ML_DSA_65,
            "ML-DSA-87": ML_DSA_87,
        }
        algo = algo_map.get(variant, ML_DSA_65)
        return algo.sign(private_key, message, deterministic=True)  # type: ignore[no-any-return]

    def verify(
        self,
        message: bytes,
        signature: bytes,
        public_key: bytes,
        variant: str = "ML-DSA-65",
    ) -> bool:
        from dilithium_py.ml_dsa import ML_DSA_44, ML_DSA_65, ML_DSA_87

        algo_map = {
            "ML-DSA-44": ML_DSA_44,
            "ML-DSA-65": ML_DSA_65,
            "ML-DSA-87": ML_DSA_87,
        }
        algo = algo_map.get(variant, ML_DSA_65)
        try:
            return algo.verify(public_key, message, signature)  # type: ignore[no-any-return]
        except Exception:
            return False


class PurePythonKEMBackend(KEMBackend):
    """Pure Python KEM backend using kyber_py."""

    def is_available(self) -> bool:
        """Check if the pure Python KEM backend is available."""
        try:
            return importlib.util.find_spec("kyber_py") is not None
        except Exception:
            return False

    def generate_keypair(self, variant: str = "ML-KEM-768") -> tuple[bytes, bytes]:
        from kyber_py.ml_kem import ML_KEM_512, ML_KEM_768, ML_KEM_1024

        algo_map = {
            "ML-KEM-512": ML_KEM_512,
            "ML-KEM-768": ML_KEM_768,
            "ML-KEM-1024": ML_KEM_1024,
        }
        algo = algo_map.get(variant, ML_KEM_768)
        return algo.keygen()  # type: ignore[no-any-return]

    def encapsulate(
        self, public_key: bytes, variant: str = "ML-KEM-768"
    ) -> tuple[bytes, bytes]:
        from kyber_py.ml_kem import ML_KEM_512, ML_KEM_768, ML_KEM_1024

        algo_map = {
            "ML-KEM-512": ML_KEM_512,
            "ML-KEM-768": ML_KEM_768,
            "ML-KEM-1024": ML_KEM_1024,
        }
        algo = algo_map.get(variant, ML_KEM_768)
        ss, ct = algo.encaps(public_key)
        return ct, ss

    def decapsulate(
        self, ciphertext: bytes, private_key: bytes, variant: str = "ML-KEM-768"
    ) -> bytes:
        from kyber_py.ml_kem import ML_KEM_512, ML_KEM_768, ML_KEM_1024

        algo_map = {
            "ML-KEM-512": ML_KEM_512,
            "ML-KEM-768": ML_KEM_768,
            "ML-KEM-1024": ML_KEM_1024,
        }
        algo = algo_map.get(variant, ML_KEM_768)
        return algo.decaps(private_key, ciphertext)  # type: ignore[no-any-return]


# Global registry - easy to swap default backend
_DEFAULT_PQC_BACKEND: PQCBackend = PurePythonPQCBackend()
_DEFAULT_KEM_BACKEND: KEMBackend = PurePythonKEMBackend()


def get_pqc_backend() -> PQCBackend:
    """Return the active PQC backend."""
    global _DEFAULT_PQC_BACKEND
    return _DEFAULT_PQC_BACKEND


def get_kem_backend() -> KEMBackend:
    """Return the active KEM backend."""
    global _DEFAULT_KEM_BACKEND
    return _DEFAULT_KEM_BACKEND


def set_pqc_backend(backend: PQCBackend) -> None:
    """Allow runtime backend swapping (useful for testing)."""
    global _DEFAULT_PQC_BACKEND
    _DEFAULT_PQC_BACKEND = backend


def set_kem_backend(backend: KEMBackend) -> None:
    """Allow runtime KEM backend swapping."""
    global _DEFAULT_KEM_BACKEND
    _DEFAULT_KEM_BACKEND = backend
