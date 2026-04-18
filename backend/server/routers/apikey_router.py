"""API Key management routes."""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.storage.postgres.models_business import User, APIKey
from server.utils.auth_middleware import get_db, get_required_user, get_superadmin_user
from yunesa.utils.datetime_utils import coerce_any_to_utc_datetime, utc_now_naive

apikey_router = APIRouter(prefix="/apikey", tags=["apikey"])


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns: (full_key, key_hash, key_prefix)
    - full_key: Full secret key, returned only once at creation time.
    - key_hash: Hash value stored in the database.
    - key_prefix: Prefix used for display.
    """
    random_part = secrets.token_hex(24)
    full_key = f"yxkey_{random_part}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:12]
    return full_key, key_hash, key_prefix


class APIKeyCreate(BaseModel):
    name: str
    user_id: int | None = None
    department_id: int | None = None
    expires_at: str | None = None


class APIKeyUpdate(BaseModel):
    name: str | None = None
    expires_at: str | None = None
    is_enabled: bool | None = None


class APIKeyResponse(BaseModel):
    id: int
    key_prefix: str
    name: str
    user_id: int | None
    department_id: int | None
    expires_at: str | None
    is_enabled: bool
    last_used_at: str | None
    created_by: str
    created_at: str


class APIKeyCreateResponse(BaseModel):
    api_key: APIKeyResponse
    secret: str


@apikey_router.get("/", response_model=dict)
async def list_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """List API keys visible to the current user."""
    # Regular users can only view their own API keys.
    if current_user.role == "superadmin":
        # Superadmin can view all API keys.
        result = await db.execute(select(APIKey).order_by(APIKey.created_at.desc()).offset(skip).limit(limit))
        api_keys = result.scalars().all()
        total_result = await db.execute(select(func.count(APIKey.id)))
    else:
        # Regular users can only view their own API keys.
        result = await db.execute(
            select(APIKey)
            .filter(APIKey.user_id == current_user.id)
            .order_by(APIKey.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        api_keys = result.scalars().all()
        total_result = await db.execute(
            select(func.count(APIKey.id)).filter(
                APIKey.user_id == current_user.id)
        )
    total = total_result.scalar()

    return {
        "api_keys": [key.to_dict() for key in api_keys],
        "total": total,
    }


@apikey_router.post("/", response_model=APIKeyCreateResponse)
async def create_api_key(
    data: APIKeyCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key (secret is returned only once here)."""
    # Generate key.
    full_key, key_hash, key_prefix = generate_api_key()

    # Regular users can only create API keys for themselves.
    if data.user_id and data.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="No permission to create API keys for other users")

    # Verify associated user.
    if data.user_id:
        result = await db.execute(select(User).filter(User.id == data.user_id))
        user = result.scalar_one_or_none()
        if not user or user.is_deleted:
            raise HTTPException(
                status_code=404, detail="Associated user does not exist")
    else:
        # Auto-bind to current logged-in user.
        data.user_id = current_user.id

    # Parse expiration time (convert to naive datetime to match DB field type).
    expires_at = None
    if data.expires_at:
        aware_dt = coerce_any_to_utc_datetime(data.expires_at)
        if aware_dt:
            expires_at = aware_dt.replace(tzinfo=None)

    # Create record.
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=data.name,
        user_id=data.user_id,
        department_id=data.department_id,
        expires_at=expires_at,
        created_by=str(current_user.id),
    )

    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        api_key=APIKeyResponse(**api_key.to_dict()),
        secret=full_key,
    )


@apikey_router.get("/{api_key_id}", response_model=dict)
async def get_api_key(
    api_key_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single API key (only own key unless superadmin)."""
    result = await db.execute(select(APIKey).filter(APIKey.id == api_key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key does not exist")

    # Permission check: own key only, unless superadmin.
    if api_key.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="No permission to operate on this API key")

    return {"api_key": api_key.to_dict()}


@apikey_router.put("/{api_key_id}", response_model=dict)
async def update_api_key(
    api_key_id: int,
    data: APIKeyUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an API key (only own key unless superadmin)."""
    result = await db.execute(select(APIKey).filter(APIKey.id == api_key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key does not exist")

    # Permission check: own key only, unless superadmin.
    if api_key.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="No permission to operate on this API key")

    if data.name is not None:
        api_key.name = data.name

    if data.expires_at is not None:
        aware_dt = coerce_any_to_utc_datetime(data.expires_at)
        api_key.expires_at = aware_dt.replace(
            tzinfo=None) if aware_dt else None

    if data.is_enabled is not None:
        api_key.is_enabled = data.is_enabled

    await db.commit()
    await db.refresh(api_key)

    return {"api_key": api_key.to_dict()}


@apikey_router.delete("/{api_key_id}", response_model=dict)
async def delete_api_key(
    api_key_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an API key (only own key unless superadmin)."""
    result = await db.execute(select(APIKey).filter(APIKey.id == api_key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key does not exist")

    # Permission check: own key only, unless superadmin.
    if api_key.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="No permission to operate on this API key")

    await db.delete(api_key)
    await db.commit()

    return {"success": True}


@apikey_router.post("/{api_key_id}/regenerate", response_model=APIKeyCreateResponse)
async def regenerate_api_key(
    api_key_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate API key secret (returned only once here, own key unless superadmin)."""
    result = await db.execute(select(APIKey).filter(APIKey.id == api_key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key does not exist")

    # Permission check: own key only, unless superadmin.
    if api_key.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="No permission to operate on this API key")

    # Generate new secret.
    full_key, key_hash, key_prefix = generate_api_key()

    api_key.key_hash = key_hash
    api_key.key_prefix = key_prefix

    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        api_key=APIKeyResponse(**api_key.to_dict()),
        secret=full_key,
    )
