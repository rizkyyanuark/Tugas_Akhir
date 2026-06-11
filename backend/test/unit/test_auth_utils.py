from __future__ import annotations

import hashlib

import jwt
import pytest

from server.utils.auth_utils import (
    AuthUtils,
    JWT_AUDIENCE,
    JWT_ISSUER,
    validate_password_strength,
)


def test_hash_password_uses_argon2():
    hashed = AuthUtils.hash_password("secret-password")

    assert hashed.startswith("$argon2")
    assert AuthUtils.verify_password(hashed, "secret-password") is True
    assert AuthUtils.verify_password(hashed, "wrong-password") is False


def test_verify_password_accepts_legacy_sha256_format():
    legacy_hash = hashlib.sha256(b"secret-passwordsalt").hexdigest()

    assert AuthUtils.verify_password(f"{legacy_hash}:salt", "secret-password") is True
    assert AuthUtils.verify_password(f"{legacy_hash}:salt", "wrong-password") is False


def test_validate_password_strength_requires_all_character_groups():
    assert validate_password_strength("AcademicGraph1!")[0] is True
    assert validate_password_strength("short1!A")[0] is False
    assert validate_password_strength("ACADEMICGRAPH1!")[0] is False
    assert validate_password_strength("academicgraph1!")[0] is False
    assert validate_password_strength("AcademicGraph!!")[0] is False
    assert validate_password_strength("AcademicGraph12")[0] is False


def test_access_token_contains_scoped_claims(monkeypatch):
    monkeypatch.setenv("YUNESA_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)

    token = AuthUtils.create_access_token({"sub": "42"})
    payload = jwt.decode(
        token,
        "a" * 64,
        algorithms=["HS256"],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
    )

    assert payload["sub"] == "42"
    assert payload["iss"] == JWT_ISSUER
    assert payload["aud"] == JWT_AUDIENCE


def test_production_requires_persistent_jwt_secret(monkeypatch):
    monkeypatch.setenv("YUNESA_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be configured"):
        AuthUtils.create_access_token({"sub": "42"})
