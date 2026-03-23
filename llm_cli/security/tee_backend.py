"""
Simulated Trusted Execution Environment (TEE) Backend.

Provides a mock implementation of PQC signing within an enclave to protect
the TCB from host OS compromise.
"""

import logging
from abc import ABC, abstractmethod

from llm_cli.security.pqc_backend import PQCBackend, PurePythonPQCBackend

logger = logging.getLogger(__name__)


class Enclave(ABC):
    """Abstract interface for a secure enclave (e.g. Intel SGX, AWS Nitro)."""

    @abstractmethod
    def seal(self, data: bytes) -> bytes:
        """Seal data (encrypt with enclave-specific key)."""
        ...

    @abstractmethod
    def unseal(self, sealed_blob: bytes) -> bytes:
        """Unseal data (decrypt with enclave-specific key)."""
        ...

    @abstractmethod
    def sign(self, message: bytes, sealed_key: bytes, variant: str) -> bytes:
        """Sign message using a sealed key inside the enclave."""
        ...


class SimulatedEnclave(Enclave):
    """
    A simulated enclave that logs its operations and uses a mock
    enclave-level master key for sealing.
    """

    def __init__(self) -> None:
        # In a real TEE, this master key is burned into the hardware.
        self._master_key = b"ENCLAVE_MASTER_KEY_V1_2026_SIMULATED"
        self._backend = PurePythonPQCBackend()

    def seal(self, data: bytes) -> bytes:
        logger.debug("[TEE] Sealing key for secure storage.")
        # Simple XOR-based "encryption" for simulation purposes
        # In reality, this would use AES-GCM with a hardware key.
        return bytes(
            a ^ b
            for a, b in zip(
                data,
                self._master_key * (len(data) // len(self._master_key) + 1),
                strict=False,
            )
        )

    def unseal(self, sealed_blob: bytes) -> bytes:
        logger.debug("[TEE] Unsealing key within secure boundary.")
        return bytes(
            a ^ b
            for a, b in zip(
                sealed_blob,
                self._master_key * (len(sealed_blob) // len(self._master_key) + 1),
                strict=False,
            )
        )

    def sign(self, message: bytes, sealed_key: bytes, variant: str) -> bytes:
        logger.debug(
            f"[TEE] Performing {variant} signature in isolated enclave memory."
        )
        # Key never leaves the enclave; unsealing and signing happens in one step.
        raw_key = self.unseal(sealed_key)
        signature = self._backend.sign(message, raw_key, variant)
        return bytes(signature)


class TEEPQCBackend(PQCBackend):
    """
    PQC Backend that leverages a TEE for all signing operations.
    """

    def __init__(self, enclave: Enclave | None = None):
        self._enclave = enclave or SimulatedEnclave()
        self._fallback = PurePythonPQCBackend()

    def is_available(self) -> bool:
        # In a real scenario, check if /dev/sgx or AWS Nitro driver is present.
        return True

    def generate_keypair(self, variant: str = "ML-DSA-65") -> tuple[bytes, bytes]:
        # Generate raw keypair, then seal the private key before returning.
        pub, priv = self._fallback.generate_keypair(variant)
        sealed_priv = self._enclave.seal(priv)
        logger.info(f"[TEE] Generated and sealed {variant} keypair.")
        return pub, sealed_priv

    def sign(
        self, message: bytes, sealed_private_key: bytes, variant: str = "ML-DSA-65"
    ) -> bytes:
        # Pass the sealed key to the enclave.
        return self._enclave.sign(message, sealed_private_key, variant)

    def verify(
        self,
        message: bytes,
        signature: bytes,
        public_key: bytes,
        variant: str = "ML-DSA-65",
    ) -> bool:
        # Verification doesn't strictly need a TEE, so we can use the fallback.
        return self._fallback.verify(message, signature, public_key, variant)
