"""
Trust Resolution and Centralized KMS Integration.

This module provides abstractions for resolving trusted identities and keys,
supporting both local (filesystem-based) and enterprise (KMS/HSM) models.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from llm_cli.consts import KEY_DIR

logger = logging.getLogger(__name__)


class TrustResolver(ABC):
    """Abstract interface for resolving trusted keys for remote identities."""

    @abstractmethod
    def resolve_rsa_public_key(self, entity_id: str) -> bytes | None:
        """Resolve the classical RSA public key for an entity."""
        ...

    @abstractmethod
    def resolve_pqc_public_key(self, entity_id: str, variant: str) -> bytes | None:
        """Resolve the PQC (ML-DSA) public key for an entity and variant."""
        ...


class LocalTrustResolver(TrustResolver):
    """
    Default resolver using a local directory structure:
    ~/.llm_cli/trusted/<entity_id>/id_rsa.pub
    ~/.llm_cli/trusted/<entity_id>/id_pqc_<l2/l3/l5>.pub
    """

    def __init__(self, trusted_dir: Path | None = None):
        self.trusted_dir = trusted_dir or (KEY_DIR / "trusted")

    def resolve_rsa_public_key(self, entity_id: str) -> bytes | None:
        path = self.trusted_dir / entity_id / "id_rsa.pub"
        if path.exists():
            return path.read_bytes()
        return None

    def resolve_pqc_public_key(self, entity_id: str, variant: str) -> bytes | None:
        if variant == "ML-DSA-44":
            suffix = "l2"
        elif variant == "ML-DSA-87":
            suffix = "l5"
        else:
            suffix = "l3"

        path = self.trusted_dir / entity_id / f"id_pqc_{suffix}.pub"
        if path.exists():
            return path.read_bytes()
        return None


class KMSTrustResolver(TrustResolver):
    """
    Simulated Enterprise KMS Resolver.
    In a real implementation, this would call a remote API
    (AWS KMS, HashiCorp Vault, etc.) or use a Hardware Security Module (HSM).
    """

    def __init__(self, kms_endpoint: str):
        self.kms_endpoint = kms_endpoint
        logger.info(f"Initialized Enterprise KMS Resolver at {kms_endpoint}")

    def resolve_rsa_public_key(self, entity_id: str) -> bytes | None:
        # SIMULATION: In a real scenario, this would be an authenticated HTTPS request.
        logger.debug(f"Fetching RSA key for {entity_id} from KMS...")
        # For simulation, we might fall back to local or use a mock registry.
        return None

    def resolve_pqc_public_key(self, entity_id: str, variant: str) -> bytes | None:
        logger.debug(f"Fetching PQC {variant} key for {entity_id} from KMS...")
        return None


# Global resolver registry
_ACTIVE_RESOLVER: TrustResolver = LocalTrustResolver()


def get_trust_resolver() -> TrustResolver:
    return _ACTIVE_RESOLVER


def set_trust_resolver(resolver: TrustResolver) -> None:
    global _ACTIVE_RESOLVER
    _ACTIVE_RESOLVER = resolver
