import logging
import os
import time
import uuid
from typing import Dict, Optional

import jwt

logger = logging.getLogger(__name__)

class IdentityManager:
    """
    Manages Workload Identity and Authentication Tokens.
    Implements Identity Propagation for MCP.
    """

    # In a production environment, these keys would be managed by a KMS or Vault.
    # For this implementation, we use a session-specific secret or env var.
    _SECRET_KEY = os.getenv("LLM_CLI_SECRET_KEY", str(uuid.uuid4()))
    _ALGORITHM = "HS256"
    _ISSUER = "llm-cli-client"

    @classmethod
    def generate_token(cls, user_id: str = "local_user", roles: list = None) -> str:
        """
        Generate a signed JWT token representing the caller's identity.
        This token is propagated to MCP servers to assert identity.
        """
        now = time.time()
        payload = {
            "iss": cls._ISSUER,
            "sub": user_id,
            "iat": now,
            "exp": now + 3600,  # 1 hour expiration
            "jti": str(uuid.uuid4()),
            "roles": roles or ["user"]
        }

        token = jwt.encode(payload, cls._SECRET_KEY, algorithm=cls._ALGORITHM)
        logger.debug(f"Generated identity token for user: {user_id}")
        return token

    @classmethod
    def verify_token(cls, token: str) -> Optional[Dict]:
        """
        Verify the validity of an incoming identity token.
        Returns the decoded payload if valid, None otherwise.
        """
        try:
            payload = jwt.decode(
                token,
                cls._SECRET_KEY,
                algorithms=[cls._ALGORITHM],
                issuer=cls._ISSUER
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Authentication failed: Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Authentication failed: Invalid token - {e}")
            return None

    @classmethod
    def get_current_context(cls) -> Dict:
        """
        Retrieve current execution context to be sent with MCP requests.
        """
        return {
            "authorization": f"Bearer {cls.generate_token()}",
            "trace_id": str(uuid.uuid4())
        }

    @classmethod
    def get_secret_key(cls) -> str:
        """Expose the secret key for session propagation over SSH."""
        return cls._SECRET_KEY
