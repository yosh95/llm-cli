import getpass
import logging
import os
import socket
import time
import uuid
from typing import Dict, List, Optional

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from llm_cli.consts import KEY_DIR

logger = logging.getLogger(__name__)


class IdentityManager:
    """
    Manages Workload Identity and Authentication Tokens using Asymmetric Keys (RS256).
    Implements Zero Trust Identity Propagation for MCP.
    """

    _ALGORITHM = "RS256"
    _ISSUER = "llm-cli-client"
    _KEY_DIR = KEY_DIR
    _PRIVATE_KEY_PATH = _KEY_DIR / "id_rsa"
    _PUBLIC_KEY_PATH = _KEY_DIR / "id_rsa.pub"

    @classmethod
    def _ensure_keys(cls):
        """Ensure RSA keys exist, generate them if not."""
        if not cls._KEY_DIR.exists():
            cls._KEY_DIR.mkdir(parents=True, exist_ok=True)

        if not cls._PRIVATE_KEY_PATH.exists():
            logger.info(f"Generating new RSA key pair in {cls._KEY_DIR}...")
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            # Save Private Key
            with open(cls._PRIVATE_KEY_PATH, "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            # Save Public Key
            public_key = private_key.public_key()
            with open(cls._PUBLIC_KEY_PATH, "wb") as f:
                f.write(
                    public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )

    @classmethod
    def _get_private_key_content(cls) -> bytes:
        cls._ensure_keys()
        with open(cls._PRIVATE_KEY_PATH, "rb") as f:
            return f.read()

    @classmethod
    def _get_public_key_content(cls) -> bytes:
        cls._ensure_keys()
        # On a remote server, the public key might be injected via environment
        # or pre-placed file.
        env_pub_key = os.getenv("LLM_CLI_PUBLIC_KEY")
        if env_pub_key:
            return env_pub_key.encode("utf-8")

        if cls._PUBLIC_KEY_PATH.exists():
            with open(cls._PUBLIC_KEY_PATH, "rb") as f:
                return f.read()

        raise FileNotFoundError(
            f"Public key not found at {cls._PUBLIC_KEY_PATH}. "
            "Set LLM_CLI_PUBLIC_KEY env var or place the key file."
        )

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
        user_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        audience: Optional[str] = None,
    ) -> str:
        """
        Generate a signed JWT token using the private RSA key.
        :param user_id: Identity of the caller (defaults to local user@host).
        :param roles: List of roles assigned to this identity.
        :param audience: The intended recipient of this token (e.g., server name).
        """
        now = time.time()
        uid = user_id or cls.get_local_identity()
        payload = {
            "iss": cls._ISSUER,
            "sub": uid,
            "iat": now,
            "exp": now + 600,  # Short lived: 10 minutes
            "jti": str(uuid.uuid4()),
            "roles": roles or ["user"],
        }

        if audience:
            payload["aud"] = audience

        private_key = cls._get_private_key_content()
        token = jwt.encode(payload, private_key, algorithm=cls._ALGORITHM)
        logger.debug(f"Generated identity token for: {uid} (aud: {audience})")
        return token

    @classmethod
    def verify_token(
        cls, token: str, expected_audience: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Verify the validity of an incoming identity token using the public RSA key.
        """
        try:
            public_key = cls._get_public_key_content()
            # If audience is provided in the token, verify it matches
            # The audience can be injected into the server via env var
            target_aud = expected_audience or os.getenv("MCP_SERVER_NAME")

            payload = jwt.decode(
                token,
                public_key,
                algorithms=[cls._ALGORITHM],
                issuer=cls._ISSUER,
                audience=target_aud,
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Authentication failed: Token expired")
            return None
        except jwt.InvalidAudienceError as e:
            logger.warning(f"Authentication failed: Invalid audience - {e}")
            return None
        except Exception as e:
            logger.warning(f"Authentication failed: {e}")
            return None

    @classmethod
    def get_current_context(cls) -> Dict:
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
