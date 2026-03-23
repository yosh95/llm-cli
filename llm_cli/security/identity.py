import getpass
import hashlib
import logging
import os
import socket
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from llm_cli.consts import KEY_DIR
from llm_cli.security.pqc import PQCProvider
from llm_cli.security.pqc_cose import HybridSigner
from llm_cli.security.trust import get_trust_resolver

logger = logging.getLogger(__name__)


class IdentityManager:
    """
    Manages identity and authentication tokens using hybrid keys (RSA + PQC).
    Provides verification mechanisms for tool execution and client authentication.
    """

    _ALGORITHM = "RS256"
    _ISSUER = "llm-cli-client"
    _KEY_DIR = KEY_DIR
    _TRUSTED_DIR = KEY_DIR / "trusted"
    _PRIVATE_KEY_PATH = _KEY_DIR / "id_rsa"
    _PUBLIC_KEY_PATH = _KEY_DIR / "id_rsa.pub"
    _PQC_PRIVATE_KEY_PATH = _KEY_DIR / "id_pqc_l3.key"  # Default (Level 3)
    _PQC_PUBLIC_KEY_PATH = _KEY_DIR / "id_pqc_l3.pub"
    _PQC_PRIVATE_KEY_L2_PATH = _KEY_DIR / "id_pqc_l2.key"  # ML-DSA-44
    _PQC_PUBLIC_KEY_L2_PATH = _KEY_DIR / "id_pqc_l2.pub"
    _PQC_PRIVATE_KEY_L5_PATH = _KEY_DIR / "id_pqc_l5.key"  # ML-DSA-87
    _PQC_PUBLIC_KEY_L5_PATH = _KEY_DIR / "id_pqc_l5.pub"
    _PQC_KEM_PRIVATE_KEY_PATH = _KEY_DIR / "id_kem.key"
    _PQC_KEM_PUBLIC_KEY_PATH = _KEY_DIR / "id_kem.pub"

    # In-process cache: avoid re-running _ensure_keys() on every key access
    _keys_ensured: bool = False
    _key_cache: dict[str, bytes] = {}

    @classmethod
    def use_tee(cls) -> None:
        """Switch to TEE-protected PQC signing."""
        from llm_cli.security.pqc_backend import set_pqc_backend
        from llm_cli.security.tee_backend import TEEPQCBackend

        logger.info("Enabling Hardware Sovereignty: Switching to TEE-protected PQC.")
        set_pqc_backend(TEEPQCBackend())

    @classmethod
    def _get_pqc_paths(cls, variant: str) -> tuple[Path, Path]:
        """Map variant name to file paths."""
        if variant == "ML-DSA-44":
            return cls._PQC_PRIVATE_KEY_L2_PATH, cls._PQC_PUBLIC_KEY_L2_PATH
        elif variant == "ML-DSA-87":
            return cls._PQC_PRIVATE_KEY_L5_PATH, cls._PQC_PUBLIC_KEY_L5_PATH
        else:
            return cls._PQC_PRIVATE_KEY_PATH, cls._PQC_PUBLIC_KEY_PATH

    @classmethod
    def _check_private_file_permissions(cls, path: Path) -> None:
        """Check if private file permissions are restricted to owner only (0600)."""
        if not path.exists():
            return

        stat = path.stat()
        mode = stat.st_mode
        # Check if any permissions for group (0o070) or others (0o007) are set
        if mode & 0o077:
            error_msg = (
                f"Permissions for '{path}' are too open. "
                "Private keys MUST NOT be accessible by others. "
                f"Please run: chmod 600 {path}"
            )
            logger.critical(error_msg)
            raise PermissionError(error_msg)

    @classmethod
    def _ensure_keys(cls, force: bool = False) -> None:
        """Ensure RSA, ML-DSA (all levels), and ML-KEM keys exist."""
        # Auto-generation is always enabled for better UX.
        # Security is enforced at the verification layer (Trusted Directory),
        # not the generation layer.

        # Skip repeated filesystem checks within the same process unless forced.
        # We also check if the private key exists to handle cases where the directory
        # was wiped or changed (e.g. in tests).
        if cls._keys_ensured and not force and cls._PRIVATE_KEY_PATH.exists():
            return

        if force:
            cls._keys_ensured = False
            logger.info("Force regeneration requested (not implemented).")

        if not cls._KEY_DIR.exists():
            cls._KEY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        else:
            # Fix existing directory permissions
            if (cls._KEY_DIR.stat().st_mode & 0o777) != 0o700:
                cls._KEY_DIR.chmod(0o700)

        # Classical RSA Keys
        if not cls._PRIVATE_KEY_PATH.exists():
            logger.info("Initializing your secure identity (Auto-gen)...")
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            # Save Private Key (mode 0o600)
            with os.fdopen(
                os.open(cls._PRIVATE_KEY_PATH, os.O_WRONLY | os.O_CREAT, 0o600), "wb"
            ) as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            # Save Public Key
            with os.fdopen(
                os.open(cls._PUBLIC_KEY_PATH, os.O_WRONLY | os.O_CREAT, 0o600), "wb"
            ) as f:
                f.write(
                    private_key.public_key().public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )

        # Post-Quantum Keys (ML-DSA) - Agility Levels L2, L3, L5
        for v in ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]:
            priv_p, pub_p = cls._get_pqc_paths(v)
            if not priv_p.exists():
                logger.info(f"Generating new Post-Quantum ({v}) key pair...")
                pub_pqc, priv_pqc = PQCProvider.generate_keypair(variant=v)
                with os.fdopen(
                    os.open(priv_p, os.O_WRONLY | os.O_CREAT, 0o600), "wb"
                ) as f:
                    f.write(priv_pqc)
                with os.fdopen(
                    os.open(pub_p, os.O_WRONLY | os.O_CREAT, 0o600), "wb"
                ) as f:
                    f.write(pub_pqc)

        # Post-Quantum KEM Keys (ML-KEM)
        if not cls._PQC_KEM_PRIVATE_KEY_PATH.exists():
            logger.info("Generating new Post-Quantum (ML-KEM) key pair...")
            from llm_cli.security.pqc import KEMProvider

            pub_kem, priv_kem = KEMProvider.generate_keypair()
            with os.fdopen(
                os.open(cls._PQC_KEM_PRIVATE_KEY_PATH, os.O_WRONLY | os.O_CREAT, 0o600),
                "wb",
            ) as f:
                f.write(priv_kem)
            with os.fdopen(
                os.open(cls._PQC_KEM_PUBLIC_KEY_PATH, os.O_WRONLY | os.O_CREAT, 0o600),
                "wb",
            ) as f:
                f.write(pub_kem)

        # Mark as completed so subsequent calls within the same process are no-ops
        cls._keys_ensured = True

    @classmethod
    def _get_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        if "rsa_priv" not in cls._key_cache:
            cls._check_private_file_permissions(cls._PRIVATE_KEY_PATH)
            with cls._PRIVATE_KEY_PATH.open("rb") as f:
                cls._key_cache["rsa_priv"] = f.read()
        return cls._key_cache["rsa_priv"]

    @classmethod
    def _get_pqc_private_key_content(cls, variant: str = "ML-DSA-65") -> bytes:
        cls._ensure_keys()
        cache_key = f"pqc_priv_{variant}"
        if cache_key not in cls._key_cache:
            priv_p, _ = cls._get_pqc_paths(variant)
            cls._check_private_file_permissions(priv_p)
            with priv_p.open("rb") as f:
                cls._key_cache[cache_key] = f.read()
        return cls._key_cache[cache_key]

    @classmethod
    def _get_kem_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        if "kem_priv" not in cls._key_cache:
            cls._check_private_file_permissions(cls._PQC_KEM_PRIVATE_KEY_PATH)
            with cls._PQC_KEM_PRIVATE_KEY_PATH.open("rb") as f:
                cls._key_cache["kem_priv"] = f.read()
        return cls._key_cache["kem_priv"]

    @classmethod
    def _get_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        if "rsa_pub" not in cls._key_cache:
            env_pub_key = os.getenv("LLM_CLI_PUBLIC_KEY")
            if env_pub_key:
                cls._key_cache["rsa_pub"] = env_pub_key.encode("utf-8")
            elif cls._PUBLIC_KEY_PATH.exists():
                with cls._PUBLIC_KEY_PATH.open("rb") as f:
                    cls._key_cache["rsa_pub"] = f.read()
            else:
                raise FileNotFoundError(
                    f"Public key not found at {cls._PUBLIC_KEY_PATH}."
                )
        return cls._key_cache["rsa_pub"]

    @classmethod
    def _get_pqc_public_key_content(cls, variant: str = "ML-DSA-65") -> bytes:
        cls._ensure_keys()
        cache_key = f"pqc_pub_{variant}"
        if cache_key not in cls._key_cache:
            # Allow environment override for specific variant if needed
            env_key = f"LLM_CLI_PQC_PUBLIC_KEY_{variant.replace('-', '_')}"
            env_pqc_pub = os.getenv(env_key) or os.getenv("LLM_CLI_PQC_PUBLIC_KEY")
            if env_pqc_pub:
                import base64

                try:
                    cls._key_cache[cache_key] = base64.b64decode(env_pqc_pub)
                except Exception:
                    pass

            if cache_key not in cls._key_cache:
                _, pub_p = cls._get_pqc_paths(variant)
                if pub_p.exists():
                    with pub_p.open("rb") as f:
                        cls._key_cache[cache_key] = f.read()
                else:
                    cls._key_cache[cache_key] = b""
        return cls._key_cache[cache_key]

    @classmethod
    def _get_kem_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        if "kem_pub" not in cls._key_cache:
            env_kem_pub = os.getenv("LLM_CLI_KEM_PUBLIC_KEY")
            if env_kem_pub:
                import base64

                try:
                    cls._key_cache["kem_pub"] = base64.b64decode(env_kem_pub)
                except Exception:
                    pass

            if "kem_pub" not in cls._key_cache:
                if cls._PQC_KEM_PUBLIC_KEY_PATH.exists():
                    with cls._PQC_KEM_PUBLIC_KEY_PATH.open("rb") as f:
                        cls._key_cache["kem_pub"] = f.read()
                else:
                    cls._key_cache["kem_pub"] = b""
        return cls._key_cache["kem_pub"]

    @classmethod
    def get_local_identity(cls) -> str:
        """Get the local workload identity as user@hostname (Fixed)."""
        try:
            user = getpass.getuser()
            hostname = socket.gethostname()
            return f"{user}@{hostname}"
        except Exception:
            return "unknown_workload"

    @classmethod
    def generate_token(
        cls,
        user_id: str | None = None,
        audience: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        args: dict | None = None,
    ) -> str:
        """Generate a signed Hybrid token (RSA + PQC) with ABAC claims."""
        now = time.time()
        uid = user_id or cls.get_local_identity()
        payload = {
            "iss": cls._ISSUER,
            "sub": uid,
            "iat": now,
            "exp": now + 600,
            "jti": str(uuid.uuid4()),
            "pqc": True,
            "pqc_kem_pub": cls.get_kem_public_key(),
        }

        # --- ABAC Claims ---
        if tool_name:
            payload["tool"] = tool_name
        if risk_level:
            payload["risk_level"] = risk_level

        # Workspace binding (SHA-256 of the current working directory)
        payload["workspace"] = hashlib.sha256(
            Path.cwd().as_posix().encode()
        ).hexdigest()

        # Embed PQC Integrity Attestation (Remote Attestation)
        try:
            from llm_cli.security.integrity import IntegrityVerifier

            root_path = Path(__file__).resolve().parent.parent.parent
            verifier = IntegrityVerifier(root_path)
            payload["integrity_attestation"] = verifier.generate_attestation_token()
        except Exception as e:
            logger.warning(f"Could not attach integrity attestation to token: {e}")

        if audience:
            payload["aud"] = audience

        # --- PQC Agility: Select ML-DSA variant based on risk ---
        from llm_cli.security.pqc import PQCAgilityManager

        variant = "ML-DSA-65"  # Default
        if tool_name:
            variant = PQCAgilityManager.get_required_level(tool_name, args=args)

        rsa_priv = cls._get_private_key_content()
        pqc_priv = cls._get_pqc_private_key_content(variant=variant)

        # Generate COSE-based hybrid token (binary)
        cose_token_bytes = HybridSigner.create_hybrid_token(
            payload, rsa_priv, pqc_priv, variant=variant
        )

        # Encode to Base64url for JSON-RPC transport compatibility
        import base64

        token = base64.urlsafe_b64encode(cose_token_bytes).decode().rstrip("=")

        logger.debug(f"Generated PQC-Hybrid identity token ({variant}) for: {uid}")
        return token

    @classmethod
    def _get_trusted_pqc_public_key(cls, entity_id: str, variant: str) -> bytes:
        """
        Resolve the trusted PQC public key for a given entity and variant.
        Uses the configured TrustResolver.
        """
        # Fallback to current local identity if entity_id matches local identity
        if entity_id == cls.get_local_identity():
            return cls._get_pqc_public_key_content(variant=variant)

        # Use the configured TrustResolver
        resolver = get_trust_resolver()
        key = resolver.resolve_pqc_public_key(entity_id, variant)
        if key:
            return key

        logger.warning(f"No trusted PQC {variant} key found for entity: {entity_id}")
        return b""

    @classmethod
    def verify_token(
        cls,
        token: str,
        expected_audience: str | None = None,
        rsa_pub_key: bytes | None = None,
        pqc_pub_key_getter: "Callable[[str], bytes] | None" = None,
    ) -> dict | None:
        """
        Verify the validity of an incoming Hybrid token (RSA + PQC).

        :param token: The Base64url-encoded COSE token string.
        :param expected_audience: The audience (aud) to check against.
        :param rsa_pub_key: Optional explicit RSA public key (bytes).
        :param pqc_pub_key_getter: Optional callback to get PQC public key.
        """
        import base64

        import cbor2

        try:
            # 1. PRE-VERIFICATION (UNSECURE DECODE) to extract subject (sub).
            # Extract sender identity to resolve the correct verification key.
            padding = "=" * (4 - len(token) % 4)
            cose_token_bytes = base64.urlsafe_b64decode(token + padding)

            # COSE_Sign structure (RFC 9052):
            # [protected, unprotected, payload, signatures]
            # It might be wrapped in a CBOR Tag 98.
            tagged_data = cbor2.loads(cose_token_bytes)

            if hasattr(tagged_data, "value"):
                decoded_cose = tagged_data.value
            else:
                decoded_cose = tagged_data

            # Payload is the 3rd element (index 2).
            payload_raw = cbor2.loads(decoded_cose[2])
            entity_id = payload_raw.get("sub", "unknown")

            # 2. KEY RESOLUTION
            resolver = get_trust_resolver()

            # RSA Public Key Resolution
            if not rsa_pub_key:
                # Try TrustResolver first
                rsa_pub = resolver.resolve_rsa_public_key(entity_id)
                if not rsa_pub:
                    # Fallback to local keys if it's us, otherwise fail.
                    if entity_id == cls.get_local_identity():
                        rsa_pub = cls._get_public_key_content()
                    else:
                        logger.warning(f"Untrusted entity: {entity_id}")
                        return None
            else:
                rsa_pub = rsa_pub_key

            # PQC Public Key Resolution (Getter)
            pqc_getter: Callable[[str], bytes]
            if not pqc_pub_key_getter:
                # Dynamically resolve PQC key based on the sender's identity (entity_id)
                def dynamic_pqc_getter(variant: str) -> bytes:
                    return cls._get_trusted_pqc_public_key(entity_id, variant)

                pqc_getter = dynamic_pqc_getter
            else:
                pqc_getter = pqc_pub_key_getter

            # 3. CRYPTOGRAPHIC VERIFICATION (Hybrid RSA + PQC)
            payload = HybridSigner.verify_hybrid_token(
                cose_token_bytes, rsa_pub, pqc_getter
            )

            if payload:
                # 4. Audience check
                target_aud = expected_audience or os.getenv("MCP_SERVER_NAME")
                if target_aud and "aud" in payload and payload.get("aud") != target_aud:
                    logger.warning(
                        f"Audience mismatch: {payload.get('aud')} != {target_aud}"
                    )
                    return None

                # 5. Integrity Attestation (Remote Attestation) Check
                # The server should compare the payload's 'integrity_attestation'
                # against a local whitelist of 'Golden Manifests'.
                attestation = payload.get("integrity_attestation")
                if attestation:
                    logger.debug("Integrity attestation present in token.")
                else:
                    logger.debug("No integrity attestation in token.")

                return payload

            return None
        except Exception as e:
            logger.warning(f"Authentication failed: {e}")
            return None

    @classmethod
    def get_current_context(cls) -> dict:
        """
        Retrieve current execution context to be sent with MCP requests.
        """
        return {
            "authorization": f"Bearer {cls.generate_token()}",
            "trace_id": str(uuid.uuid4()),
        }

    @classmethod
    def get_public_key(cls) -> str:
        """Expose the public key for distribution to remote servers."""
        return cls._get_public_key_content().decode("utf-8")

    @classmethod
    def get_pqc_public_key(cls) -> str:
        """Expose the PQC public key for distribution to remote servers."""
        import base64

        return base64.b64encode(cls._get_pqc_public_key_content()).decode("utf-8")

    @classmethod
    def get_kem_public_key(cls) -> str:
        """Expose the ML-KEM public key for distribution to remote servers."""
        import base64

        return base64.b64encode(cls._get_kem_public_key_content()).decode("utf-8")


# Create a singleton instance for backward compatibility or easier access if needed
id_manager = IdentityManager()
