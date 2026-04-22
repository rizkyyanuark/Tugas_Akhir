import hashlib
import hmac
import os
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

from yunesa.utils.datetime_utils import utc_now

# JWT Configuration
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "ta_know_secure_key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION = 7 * 24 * 60 * 60  # Expires in 7 days
PASSWORD_HASHER = PasswordHasher()


class AuthUtils:
    """Authentication utility class"""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using Argon2"""
        return PASSWORD_HASHER.hash(password)

    @staticmethod
    def verify_password(stored_password: str, provided_password: str) -> bool:
        """Verify password"""
        if stored_password.startswith("$argon2"):
            try:
                return PASSWORD_HASHER.verify(stored_password, provided_password)
            except (InvalidHash, VerifyMismatchError, VerificationError):
                return False

        # Compatible with historical SHA-256:salt format, avoiding existing account passwords from failing immediately after upgrade.
        if ":" not in stored_password:
            return False

        hashed, salt = stored_password.split(":", 1)
        check_hash = hashlib.sha256((provided_password + salt).encode()).hexdigest()
        return hmac.compare_digest(hashed, check_hash)

    @staticmethod
    def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """Create JWT access token"""
        to_encode = data.copy()

        # Set expiration time
        if expires_delta:
            expire = utc_now() + expires_delta
        else:
            expire = utc_now() + timedelta(seconds=JWT_EXPIRATION)

        to_encode.update({"exp": expire})

        # Encode JWT
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> dict[str, Any] | None:
        """Decode and verify JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.PyJWTError:
            return None

    @staticmethod
    def verify_access_token(token: str) -> dict[str, Any]:
        """Verify access token, raise exception if invalid"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")
