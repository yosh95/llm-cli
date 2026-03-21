import getpass
import logging
import os
import socket
import time
import uuid
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from llm_cli.consts import KEY_DIR
from llm_cli.security.pqc import HybridSigner, PQCProvider

logger = logging.getLogger(__name__)


class IdentityManager:
    """
    Manages identity and authentication tokens using hybrid keys (RSA + PQC).
    Provides verification mechanisms for tool execution and client authentication.
    """

    _ALGORITHM = "RS256"
    _ISSUER = "llm-cli-client"
    _KEY_DIR = KEY_DIR
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
    def _ensure_keys(cls, force: bool = False) -> None:
        """Ensure RSA, ML-DSA (all levels), and ML-KEM keys exist."""
        # Default to flexible mode (0) for seamless UX
        strict_mode = os.getenv("LLM_CLI_STRICT_SECURITY", "0") == "1"

        # If force is True, we bypass strict mode (e.g., during explicit keygen command)
        if force:
            strict_mode = False

        if not cls._KEY_DIR.exists():
            if strict_mode:
                raise FileNotFoundError(
                    f"Security Check: Key directory {cls._KEY_DIR} not found. "
                    "In Strict Mode, keys must be pre-provisioned."
                )
            cls._KEY_DIR.mkdir(parents=True, exist_ok=True)

        # Classical RSA Keys
        if not cls._PRIVATE_KEY_PATH.exists():
            if strict_mode:
                raise FileNotFoundError(
                    f"Security Check: RSA key missing at {cls._PRIVATE_KEY_PATH}. "
                    "In Strict Mode, keys must be pre-provisioned."
                )
            logger.info("Initializing your secure identity (TOFU)...")
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            # Save Private Key
            with cls._PRIVATE_KEY_PATH.open("wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            # Save Public Key
            public_key = private_key.public_key()
            with cls._PUBLIC_KEY_PATH.open("wb") as f:
                f.write(
                    public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )

        # Post-Quantum Keys (ML-DSA) - Agility Levels L2, L3, L5
        for v in ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]:
            priv_p, pub_p = cls._get_pqc_paths(v)
            if not priv_p.exists():
                if strict_mode:
                    raise FileNotFoundError(f"Security Check: {v} key missing.")
                logger.info(f"Generating new Post-Quantum ({v}) key pair...")
                pub_pqc, priv_pqc = PQCProvider.generate_keypair(variant=v)
                with priv_p.open("wb") as f:
                    f.write(priv_pqc)
                with pub_p.open("wb") as f:
                    f.write(pub_pqc)

        # Post-Quantum KEM Keys (ML-KEM)
        if not cls._PQC_KEM_PRIVATE_KEY_PATH.exists():
            if strict_mode:
                msg = (
                    f"Security Check: ML-KEM key missing at "
                    f"{cls._PQC_KEM_PRIVATE_KEY_PATH}. "
                    "Keys must be pre-provisioned."
                )
                raise FileNotFoundError(msg)
            logger.info("Generating new Post-Quantum (ML-KEM) key pair...")
            from llm_cli.security.pqc import KEMProvider

            pub_kem, priv_kem = KEMProvider.generate_keypair()
            with cls._PQC_KEM_PRIVATE_KEY_PATH.open("wb") as f:
                f.write(priv_kem)
            with cls._PQC_KEM_PUBLIC_KEY_PATH.open("wb") as f:
                f.write(pub_kem)

    @classmethod
    def _get_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        with cls._PRIVATE_KEY_PATH.open("rb") as f:
            return f.read()

    @classmethod
    def _get_pqc_private_key_content(cls, variant: str = "ML-DSA-65") -> bytes:
        cls._ensure_keys()
        priv_p, _ = cls._get_pqc_paths(variant)
        with priv_p.open("rb") as f:
            return f.read()

    @classmethod
    def _get_kem_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        with cls._PQC_KEM_PRIVATE_KEY_PATH.open("rb") as f:
            return f.read()

    @classmethod
    def _get_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        env_pub_key = os.getenv("LLM_CLI_PUBLIC_KEY")
        if env_pub_key:
            return env_pub_key.encode("utf-8")

        if cls._PUBLIC_KEY_PATH.exists():
            with cls._PUBLIC_KEY_PATH.open("rb") as f:
                return f.read()

        raise FileNotFoundError(f"Public key not found at {cls._PUBLIC_KEY_PATH}.")

    @classmethod
    def _get_pqc_public_key_content(cls, variant: str = "ML-DSA-65") -> bytes:
        cls._ensure_keys()
        # Allow environment override for specific variant if needed
        # Format: LLM_CLI_PQC_PUBLIC_KEY_ML_DSA_87
        env_key = f"LLM_CLI_PQC_PUBLIC_KEY_{variant.replace('-', '_')}"
        env_pqc_pub = os.getenv(env_key) or os.getenv("LLM_CLI_PQC_PUBLIC_KEY")
        if env_pqc_pub:
            import base64

            try:
                return base64.b64decode(env_pqc_pub)
            except Exception:
                pass

        _, pub_p = cls._get_pqc_paths(variant)
        if pub_p.exists():
            with pub_p.open("rb") as f:
                return f.read()

        return b""  # Fallback

    @classmethod
    def _get_kem_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        env_kem_pub = os.getenv("LLM_CLI_KEM_PUBLIC_KEY")
        if env_kem_pub:
            import base64

            return base64.b64decode(env_kem_pub)

        if cls._PQC_KEM_PUBLIC_KEY_PATH.exists():
            with cls._PQC_KEM_PUBLIC_KEY_PATH.open("rb") as f:
                return f.read()

        return b""  # Fallback

    @classmethod
    def get_local_identity(cls) -> str:
        """Get the local workload identity as user@hostname."""
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
    ) -> str:
        """
        Generate a signed Hybrid token (RSA + PQC) with Integrity Attestation.
        """
        now = time.time()
        uid = user_id or cls.get_local_identity()
        payload = {
            "iss": cls._ISSUER,
            "sub": uid,
            "iat": now,
            "exp": now + 600,
            "jti": str(uuid.uuid4()),
            "pqc": True,  # Flag indicating PQC coverage
            "pqc_kem_pub": cls.get_kem_public_key(),  # Advertise KEM capability
        }

        # Embed PQC Integrity Attestation (Remote Attestation)
        try:
            from pathlib import Path

            from llm_cli.security.integrity import IntegrityVerifier

            # Reach up to the project root where critical files are checked
            root_path = Path(__file__).resolve().parent.parent.parent
            verifier = IntegrityVerifier(root_path)
            payload["integrity_attestation"] = verifier.generate_attestation_token()
        except Exception as e:
            logger.warning(f"Could not attach integrity attestation to token: {e}")

        if audience:
            payload["aud"] = audience

        rsa_priv = cls._get_private_key_content()
        pqc_priv = cls._get_pqc_private_key_content()

        # Generate COSE-based hybrid token (binary)
        cose_token_bytes = HybridSigner.create_hybrid_token(payload, rsa_priv, pqc_priv)

        # Encode to Base64url for JSON-RPC transport compatibility
        import base64

        token = base64.urlsafe_b64encode(cose_token_bytes).decode().rstrip("=")

        logger.debug(f"Generated PQC-Hybrid identity token (COSE) for: {uid}")
        return token

    @classmethod
    def verify_token(
        cls, token: str, expected_audience: str | None = None
    ) -> dict | None:
        """
        Verify the validity of an incoming Hybrid token (RSA + PQC) in COSE format.
        """
        import base64

        try:
            rsa_pub = cls._get_public_key_content()

            # Decode from Base64url back to COSE binary
            padding = "=" * (4 - len(token) % 4)
            cose_token_bytes = base64.urlsafe_b64decode(token + padding)

            # Use HybridSigner for verification
            payload = HybridSigner.verify_hybrid_token(
                cose_token_bytes, rsa_pub, cls._get_pqc_public_key_content
            )

            if payload:
                # Additional audience check (normally handled inside jwt.decode,
                # but HybridSigner does it too, here we just ensure it matches context)
                target_aud = expected_audience or os.getenv("MCP_SERVER_NAME")
                if target_aud and "aud" in payload and payload["aud"] != target_aud:
                    logger.warning(
                        f"Audience mismatch: {payload['aud']} != {target_aud}"
                    )
                    return None
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
