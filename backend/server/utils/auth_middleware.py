import hashlib
import re

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import User, APIKey
from server.utils.auth_utils import AuthUtils
from yunesa.utils.datetime_utils import utc_now_naive

# Define OAuth2 password bearer, specify token URL
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/token", auto_error=False)

# Public paths list, accessible without login
PUBLIC_PATHS = [
    r"^/api/auth/token$",  # Login
    r"^/api/auth/check-first-run$",  # Check if first run
    r"^/api/auth/initialize$",  # Initialize system
    r"^/api$",  # Health Check
    r"^/api/system/health$",  # Health Check
    r"^/api/system/info$",  # Get system info config
]


# Get database session (async version)
async def get_db():
    async with pg_manager.get_async_session_context() as db:
        yield db


async def _verify_api_key(key: str, db: AsyncSession) -> tuple[User | None, APIKey | None]:
    """Verify API Key and return associated User and APIKey objects"""
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    result = await db.execute(select(APIKey).filter(APIKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        return None, None

    if not api_key.is_enabled:
        return None, None

    if api_key.expires_at and utc_now_naive() > api_key.expires_at:
        return None, None

    if api_key.user_id:
        result = await db.execute(select(User).filter(User.id == api_key.user_id))
        user = result.scalar_one_or_none()
        if user and not user.is_deleted:
            return user, api_key

    if api_key.department_id:
        result = await db.execute(
            select(User).filter(User.department_id == api_key.department_id,
                                User.role.in_(["admin", "superadmin"]))
        )
        user = result.scalar_one_or_none()
        if user and not user.is_deleted:
            return user, api_key

    result = await db.execute(select(User).filter(User.role == "superadmin", User.is_deleted == 0).limit(1))
    user = result.scalar_one_or_none()
    if user:
        return user, api_key

    return None, None


# Get current user (async version)
async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if authorization is None:
        return None

    if not authorization.startswith("Bearer "):
        return None

    token = authorization.split("Bearer ")[1]
    if not token:
        return None

    # Determine authentication method based on token prefix
    if token.startswith("yxkey_"):
        # API Key 认证
        user, api_key_obj = await _verify_api_key(token, db)
        if user is not None and api_key_obj is not None:
            api_key_obj.last_used_at = utc_now_naive()
            await db.commit()
        return user

    # JWT Token authentication
    try:
        payload = AuthUtils.verify_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).filter(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    return user


# Get logged-in user (throw 401 if not logged in)
async def get_required_user(user: User | None = Depends(get_current_user)):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in first",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.department_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not bound to a department",
        )
    return user


# Get admin user
async def get_admin_user(current_user: User = Depends(get_required_user)):
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# Get superadmin user
async def get_superadmin_user(current_user: User = Depends(get_required_user)):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin privileges required",
        )
    return current_user


# Check if path is a public path
def is_public_path(path: str) -> bool:
    path = path.rstrip("/")  # Remove trailing slash for matching
    for pattern in PUBLIC_PATHS:
        if re.match(pattern, path):
            return True
    return False
