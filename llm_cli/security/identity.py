import getpass
import logging
import os
import socket
import time
import uuid

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from llm_cli.consts import KEY_DIR
from llm_cli.security.pqc import HybridSigner, PQCProvider

logger = logging.getLogger(__name__)


class IdentityManager:
    """
    Manages Workload Identity and Authentication Tokens using Hybrid Keys (RSA + PQC).
    Implements Post-Quantum Zero Trust Identity Propagation for MCP.
    """

    _ALGORITHM = "RS256"
    _ISSUER = "llm-cli-client"
    _KEY_DIR = KEY_DIR
    _PRIVATE_KEY_PATH = _KEY_DIR / "id_rsa"
    _PUBLIC_KEY_PATH = _KEY_DIR / "id_rsa.pub"
    _PQC_PRIVATE_KEY_PATH = _KEY_DIR / "id_pqc.key"
    _PQC_PUBLIC_KEY_PATH = _KEY_DIR / "id_pqc.pub"

    @classmethod
    def _ensure_keys(cls, force: bool = False) -> None:
        """Ensure RSA and PQC keys exist, generate them if not (unless strict mode)."""
        # Default to strict mode (1) unless explicitly disabled (0)
        strict_mode = os.getenv("LLM_CLI_STRICT_SECURITY", "1") == "1"

        # If force is True, we bypass strict mode (e.g., during explicit keygen command)
        if force:
            strict_mode = False

        if not cls._KEY_DIR.exists():
            if strict_mode:
                raise FileNotFoundError(
                    f"Strict Mode: Key directory {cls._KEY_DIR} not found. "
                    "Keys must be pre-provisioned."
                )
            cls._KEY_DIR.mkdir(parents=True, exist_ok=True)

        # Classical RSA Keys
        if not cls._PRIVATE_KEY_PATH.exists():
            if strict_mode:
                raise FileNotFoundError(
                    f"Strict Mode: RSA key missing at {cls._PRIVATE_KEY_PATH}. "
                    "Keys must be pre-provisioned."
                )
            logger.info(f"Generating new RSA key pair in {cls._KEY_DIR}...")
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

        # Post-Quantum Keys (ML-DSA)
        if not cls._PQC_PRIVATE_KEY_PATH.exists():
            if strict_mode:
                raise FileNotFoundError(
                    f"Strict Mode: PQC key missing at {cls._PQC_PRIVATE_KEY_PATH}. "
                    "Keys must be pre-provisioned."
                )
            logger.info("Generating new Post-Quantum (PQC) key pair...")
            pub_pqc, priv_pqc = PQCProvider.generate_keypair()
            with cls._PQC_PRIVATE_KEY_PATH.open("wb") as f:
                f.write(priv_pqc)
            with cls._PQC_PUBLIC_KEY_PATH.open("wb") as f:
                f.write(pub_pqc)

    @classmethod
    def _get_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        with cls._PRIVATE_KEY_PATH.open("rb") as f:
            return f.read()

    @classmethod
    def _get_pqc_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        with cls._PQC_PRIVATE_KEY_PATH.open("rb") as f:
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
    def _get_pqc_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        env_pqc_pub = os.getenv("LLM_CLI_PQC_PUBLIC_KEY")
        if env_pqc_pub:
            import base64

            return base64.b64decode(env_pqc_pub)

        if cls._PQC_PUBLIC_KEY_PATH.exists():
            with cls._PQC_PUBLIC_KEY_PATH.open("rb") as f:
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
        roles: list[str] | None = None,
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
            "roles": roles or ["user"],
            "pqc": True,  # Flag indicating PQC coverage
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

        token = HybridSigner.create_hybrid_token(payload, rsa_priv, pqc_priv)
        logger.debug(f"Generated PQC-Hybrid identity token for: {uid}")
        return token

    @classmethod
    def verify_token(
        cls, token: str, expected_audience: str | None = None
    ) -> dict | None:
        """
        Verify the validity of an incoming Hybrid token (RSA + PQC).
        """
        try:
            rsa_pub = cls._get_public_key_content()
            pqc_pub = cls._get_pqc_public_key_content()

            # Use HybridSigner for verification
            payload = HybridSigner.verify_hybrid_token(token, rsa_pub, pqc_pub)

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


# Create a singleton instance for backward compatibility or easier access if needed
id_manager = IdentityManager()
