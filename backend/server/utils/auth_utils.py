import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

from yunesa.utils.datetime_utils import utc_now

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION = 7 * 24 * 60 * 60
JWT_AUDIENCE = "yunesa-knowledge-api"
JWT_ISSUER = "yunesa:tugas-akhir"
PUBLIC_DEFAULT_JWT_SECRET_KEYS = {
    "ta_know_secure_key",
    "yuxi_know_secure_key",
}
PASSWORD_HASHER = PasswordHasher()
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


def _is_production_env() -> bool:
    environment = os.environ.get("YUNESA_ENV") or os.environ.get("ENVIRONMENT") or "development"
    return environment.strip().lower() in {"prod", "production"}


def _get_jwt_secret_key() -> str:
    secret_key = os.environ.get("JWT_SECRET_KEY", "").strip()
    if not secret_key:
        if _is_production_env():
            raise ValueError("JWT_SECRET_KEY must be configured in production.")
        secret_key = secrets.token_hex(32)
        os.environ["JWT_SECRET_KEY"] = secret_key

    if _is_production_env() and secret_key in PUBLIC_DEFAULT_JWT_SECRET_KEYS:
        raise ValueError("JWT_SECRET_KEY must not use a public default value in production.")
    if len(secret_key) < 32:
        raise ValueError("JWT_SECRET_KEY must contain at least 32 characters.")
    return secret_key


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """Validate passwords used for account creation and password changes."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must contain at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return False, f"Password must contain at most {PASSWORD_MAX_LENGTH} characters."
    if not any(character.islower() for character in password):
        return False, "Password must contain a lowercase letter."
    if not any(character.isupper() for character in password):
        return False, "Password must contain an uppercase letter."
    if not any(character.isdigit() for character in password):
        return False, "Password must contain a number."
    if not any(not character.isalnum() for character in password):
        return False, "Password must contain a symbol."
    return True, None


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

        if expires_delta:
            expire = utc_now() + expires_delta
        else:
            expire = utc_now() + timedelta(seconds=JWT_EXPIRATION)

        to_encode.update(
            {
                "exp": expire,
                "iss": JWT_ISSUER,
                "aud": JWT_AUDIENCE,
            }
        )
        encoded_jwt = jwt.encode(to_encode, _get_jwt_secret_key(), algorithm=JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> dict[str, Any] | None:
        """Decode and verify JWT token"""
        try:
            payload = jwt.decode(
                token,
                _get_jwt_secret_key(),
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
            return payload
        except (jwt.PyJWTError, ValueError):
            return None

    @staticmethod
    def verify_access_token(token: str) -> dict[str, Any]:
        """Verify access token, raise exception if invalid"""
        try:
            payload = jwt.decode(
                token,
                _get_jwt_secret_key(),
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")
