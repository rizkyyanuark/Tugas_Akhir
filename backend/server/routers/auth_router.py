import re
import uuid
from yunesa.utils import logger

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import User, Department
from yunesa.repositories.user_repository import UserRepository
from yunesa.repositories.department_repository import DepartmentRepository
from server.utils.auth_middleware import (
    get_admin_user,
    get_superadmin_user,
    get_current_user,
    get_db,
    get_required_user,
)
from server.utils.auth_utils import AuthUtils
from server.utils.user_utils import generate_unique_user_id, validate_username, is_valid_phone_number
from server.utils.common_utils import log_operation
from yunesa.storage.minio import aupload_file_to_minio
from yunesa.utils.datetime_utils import utc_now_naive

# OIDC authenticationrelatedimport
from yunesa.services.oidc_service import (
    get_oidc_config_handler,
    oidc_callback_handler,
    oidc_exchange_code_handler,
    oidc_login_url_handler,
)

# Create router.
auth = APIRouter(prefix="/auth", tags=["authentication"])


# Request and response models.
class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    user_id_login: str  # user_id used for login
    phone_number: str | None = None
    avatar: str | None = None
    role: str
    department_id: int | None = None
    department_name: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    phone_number: str | None = None
    department_id: int | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None
    phone_number: str | None = None
    avatar: str | None = None
    department_id: int | None = None


class UserProfileUpdate(BaseModel):
    username: str | None = None
    phone_number: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    user_id: str
    phone_number: str | None = None
    avatar: str | None = None
    role: str
    department_id: int | None = None
    department_name: str | None = None  # departmentname
    created_at: str
    last_login: str | None = None


class InitializeAdmin(BaseModel):
    user_id: str  # direct input user ID
    password: str
    phone_number: str | None = None


class UsernameValidation(BaseModel):
    username: str


class UserIdGeneration(BaseModel):
    username: str
    user_id: str
    is_available: bool


class OIDCConfigResponse(BaseModel):
    """OIDC configureresponse"""

    enabled: bool
    login_url: str | None = None
    provider_name: str | None = "OIDClogin"


class OIDCLoginResponse(BaseModel):
    """OIDC loginresponse"""

    access_token: str
    token_type: str
    user_id: int
    username: str
    user_id_login: str
    phone_number: str | None = None
    avatar: str | None = None
    role: str
    department_id: int | None = None
    department_name: str | None = None


# =============================================================================
# === Helper Functions ===
# =============================================================================


async def get_default_department_id(db: AsyncSession) -> int | None:
    """Get default department ID."""
    result = await db.execute(select(Department).filter(Department.name == "defaultdepartment"))
    default_dept = result.scalar_one_or_none()
    return default_dept.id if default_dept else None


# Route: login and get token
# =============================================================================
# === authenticationgroup ===
# =============================================================================


@auth.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    # Look up user by user_id or phone_number.
    # username field in OAuth2 form is used as login identifier
    login_identifier = form_data.username

    # Try lookup by user_id.
    result = await db.execute(select(User).filter(User.user_id == login_identifier))
    user = result.scalar_one_or_none()

    # If not found by user_id, try phone_number.
    if not user:
        result = await db.execute(select(User).filter(User.phone_number == login_identifier))
        user = result.scalar_one_or_none()

    # If user does not exist, return generic error to prevent username enumeration attacks.
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login identifier or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check whether user has been deleted.
    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is in login lockout state
    if user.is_login_locked():
        remaining_time = user.get_remaining_lock_time()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Login is locked. Please wait {remaining_time} seconds and try again",
            headers={"WWW-Authenticate": "Bearer",
                     "X-Lock-Remaining": str(remaining_time)},
        )

    # Verify password.
    if not AuthUtils.verify_password(user.password_hash, form_data.password):
        # Password error, increment failure count.
        user.increment_failed_login()
        await db.commit()

        # Record failed operation.
        await log_operation(db, user.id if user else None, "loginfailed", f"Password error, failed count: {user.login_failed_count}")

        # Check whether lockout is required.
        if user.is_login_locked():
            remaining_time = user.get_remaining_lock_time()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Too many failed login attempts, account locked for {remaining_time} seconds",
                headers={"WWW-Authenticate": "Bearer",
                         "X-Lock-Remaining": str(remaining_time)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Login successful, reset failure counter.
    user.reset_failed_login()
    user.last_login = utc_now_naive()
    await db.commit()

    # Generate access token.
    token_data = {"sub": str(user.id)}
    access_token = AuthUtils.create_access_token(token_data)

    # Record login operation.
    await log_operation(db, user.id, "login")

    # Get department name.
    department_name = None
    if user.department_id:
        result = await db.execute(select(Department.name).filter(Department.id == user.department_id))
        department_name = result.scalar_one_or_none()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.username,
        "user_id_login": user.user_id,
        "phone_number": user.phone_number,
        "avatar": user.avatar,
        "role": user.role,
        "department_id": user.department_id,
        "department_name": department_name,
    }


# Route: check whether admin initialization is required
@auth.get("/check-first-run")
async def check_first_run():
    is_first_run = await pg_manager.async_check_first_run()
    return {"first_run": is_first_run}


# Route: initialize admin account
@auth.post("/initialize", response_model=Token)
async def initialize_admin(admin_data: InitializeAdmin, db: AsyncSession = Depends(get_db)):
    # Check whether this is the first run.
    if not await pg_manager.async_check_first_run():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System is already initialized, cannot create initial admin again",
        )

    # Create admin account.
    hashed_password = AuthUtils.hash_password(admin_data.password)

    # Validate user ID format (letters, numbers, underscores only).
    if not re.match(r"^[a-zA-Z0-9_]+$", admin_data.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID can only contain letters, numbers, and underscores",
        )

    if len(admin_data.user_id) < 3 or len(admin_data.user_id) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID length must be between 3 and 20 characters",
        )

    # Validate phone number format (if provided).
    if admin_data.phone_number and not is_valid_phone_number(admin_data.phone_number):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="phone numberformat is incorrect")

    # Since this is first-time initialization, use input user_id directly.
    user_id = admin_data.user_id

    # Create default department.
    dept_repo = DepartmentRepository()
    default_department = await dept_repo.create(
        {
            "name": "defaultdepartment",
            "description": "Default department created during system initialization",
        }
    )

    # Create admin user.
    user_repo = UserRepository()
    new_admin = await user_repo.create(
        {
            "username": admin_data.user_id,
            "user_id": user_id,
            "phone_number": admin_data.phone_number,
            "avatar": None,
            "password_hash": hashed_password,
            "role": "superadmin",
            "department_id": default_department.id,
            "last_login": utc_now_naive(),
        }
    )

    # Generate access token.
    token_data = {"sub": str(new_admin.id)}
    access_token = AuthUtils.create_access_token(token_data)

    # Record operation.
    await log_operation(db, new_admin.id, "systeminitialize", "Create super admin account")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_admin.id,
        "username": new_admin.username,
        "user_id_login": new_admin.user_id,
        "phone_number": new_admin.phone_number,
        "avatar": new_admin.avatar,
        "role": new_admin.role,
    }


# Route: get current user info
# =============================================================================
# === User Info Group ===
# =============================================================================


@auth.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get current logged-in user info."""
    user_dict = current_user.to_dict()

    if current_user.department_id:
        result = await db.execute(select(Department.name).filter(Department.id == current_user.department_id))
        user_dict["department_name"] = result.scalar_one_or_none()

    return user_dict


# Route: update profile
@auth.put("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile."""
    update_details = []

    # Update username (only display name, not user_id).
    if profile_data.username is not None:
        # Validate username format.
        is_valid, error_msg = validate_username(profile_data.username)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )

        # Check whether username is already used by another user.
        result = await db.execute(
            select(User).filter(User.username ==
                                profile_data.username, User.id != current_user.id)
        )
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )

        current_user.username = profile_data.username
        update_details.append(f"Username: {profile_data.username}")

    # Update phone number.
    if profile_data.phone_number is not None:
        # If phone number is not empty, validate format.
        if profile_data.phone_number and not is_valid_phone_number(profile_data.phone_number):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="phone numberformat is incorrect")

        # Check whether phone number is used by another user.
        if profile_data.phone_number:
            result = await db.execute(
                select(User).filter(User.phone_number ==
                                    profile_data.phone_number, User.id != current_user.id)
            )
            existing_phone = result.scalar_one_or_none()
            if existing_phone:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="Phone number is already used by another user")

        current_user.phone_number = profile_data.phone_number
        update_details.append(
            f"Phone number: {profile_data.phone_number or 'cleared'}")

    await db.commit()

    # Record operation.
    if update_details:
        await log_operation(db, current_user.id, "update_profile", f"Update profile: {', '.join(update_details)}", request)

    return current_user.to_dict()


# Route: create user (admin permission)
# =============================================================================
# === usermanagementgroup ===
# =============================================================================


@auth.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin permission)."""
    user_repo = UserRepository()

    # Validate username.
    is_valid, error_msg = validate_username(user_data.username)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Check whether username already exists.
    users = await user_repo.list_users()
    if any(u.username == user_data.username for u in users):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Check whether phone number already exists (if provided).
    if user_data.phone_number:
        if await user_repo.exists_by_phone(user_data.phone_number):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="phone numberalready exists",
            )

    # Generate unique user_id.
    existing_user_ids = await user_repo.get_all_user_ids()
    user_id = generate_unique_user_id(user_data.username, existing_user_ids)

    # Create new user.
    hashed_password = AuthUtils.hash_password(user_data.password)

    # Check role permissions.
    # Forbid creating superadmin account (system should only have one superadmin).
    if user_data.role == "superadmin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create superadmin account",
        )

    # Admin can only create regular users.
    if current_user.role == "admin" and user_data.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin can only create regular user accounts",
        )

    # Department assignment logic.
    if current_user.role == "superadmin":
        # When superadmin creates user, use specified department or default department.
        department_id = user_data.department_id
        if department_id is None:
            # Get default department.
            dept_repo = DepartmentRepository()
            departments = await dept_repo.list_departments()
            default_dept = next(
                (d for d in departments if d.name == "defaultdepartment"), None)
            department_id = default_dept.id if default_dept else None
    else:
        # When regular admin creates user, inherit admin's department automatically.
        department_id = current_user.department_id
        # Non-superadmin cannot specify department.
        if user_data.department_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Regular admin cannot specify department",
            )

    new_user = await user_repo.create(
        {
            "username": user_data.username,
            "user_id": user_id,
            "phone_number": user_data.phone_number,
            "password_hash": hashed_password,
            "role": user_data.role,
            "department_id": department_id,
        }
    )

    # Record operation.
    await log_operation(
        db, current_user.id, "createuser", f"createuser: {user_data.username}, role: {user_data.role}", request
    )

    return new_user.to_dict()


# Route: get all users (admin permission)
@auth.get("/users", response_model=list[UserResponse])
async def read_users(
    skip: int = 0, limit: int = 100, current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)
):
    user_repo = UserRepository()

    # Department isolation logic.
    if current_user.role == "superadmin":
        # Superadmin can see all users.
        users_with_dept = await user_repo.list_with_department(skip=skip, limit=limit)
    else:
        # Regular admin can only see users in the same department.
        users_with_dept = await user_repo.list_with_department(
            skip=skip, limit=limit, department_id=current_user.department_id
        )

    users = []
    for user, dept_name in users_with_dept:
        user_dict = user.to_dict()
        user_dict["department_name"] = dept_name
        users.append(user_dict)
    return users


# Route: get specific user info (admin permission)
@auth.get("/users/{user_id}", response_model=UserResponse)
async def read_user(user_id: int, current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).filter(User.id == user_id, User.is_deleted == 0))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="userdoes not exist",
        )
    return user.to_dict()


async def check_department_admin_count(db: AsyncSession, department_id: int, exclude_user_id: int) -> int:
    """Check admin count in a department (excluding specified user)."""
    result = await db.execute(
        select(func.count(User.id)).filter(
            User.department_id == department_id,
            User.role == "admin",
            User.id != exclude_user_id,
        )
    )
    return result.scalar()


# Route: update user info (admin permission)
@auth.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).filter(User.id == user_id, User.is_deleted == 0))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="userdoes not exist",
        )

    # checkpermission
    if user.role == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin can modify superadmin accounts",
        )

    # Superadmin account cannot be downgraded (except by another superadmin).
    if user.role == "superadmin" and user_data.role and user_data.role != "superadmin" and current_user.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot downgrade superadmin account",
        )

    # Update fields.
    update_details = []

    if user_data.username is not None:
        # Check whether username is used by another user.
        result = await db.execute(select(User).filter(User.username == user_data.username, User.id != user_id))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )
        user.username = user_data.username
        update_details.append(f"Username: {user_data.username}")

    if user_data.password is not None:
        user.password_hash = AuthUtils.hash_password(user_data.password)
        update_details.append("Password updated")

    if user_data.role is not None:
        # Check whether admin is being downgraded to regular user.
        if user.role == "admin" and user_data.role == "user" and user.department_id is not None:
            admin_count = await check_department_admin_count(db, user.department_id, user_id)
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot downgrade admin to user because this user is the only admin in the current department",
                )
        user.role = user_data.role
        update_details.append(f"role: {user_data.role}")

    if user_data.phone_number is not None:
        user.phone_number = user_data.phone_number
        update_details.append(
            f"Phone number: {user_data.phone_number or 'cleared'}")

    if user_data.avatar is not None:
        user.avatar = user_data.avatar
        update_details.append(f"Avatar: {user_data.avatar or 'cleared'}")

    # Department modification permission control (only superadmin can modify user department).
    if user_data.department_id is not None and user_data.department_id != user.department_id:
        if current_user.role != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only superadmin can modify user department",
            )

        # Check whether this user is the only admin in current department.
        if user.role == "admin" and user.department_id is not None:
            admin_count = await check_department_admin_count(db, user.department_id, user_id)
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot modify this user's department because this user is the only admin in the current department",
                )

        user.department_id = user_data.department_id
        update_details.append(f"departmentID: {user_data.department_id}")

    await db.commit()

    # Record operation.
    await log_operation(db, current_user.id, "updateuser", f"updateuserID {user_id}: {', '.join(update_details)}", request)

    return user.to_dict()


# Route: delete user (admin permission)
@auth.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: int, request: Request, current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).filter(User.id == user_id, User.is_deleted == 0))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="userdoes not exist",
        )

    # Cannot delete superadmin account.
    if user.role == "superadmin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete superadmin account",
        )

    # Check whether this is the only admin in the department.
    if user.role == "admin" and current_user.role != "superadmin":
        result = await db.execute(
            select(func.count(User.id)).filter(
                User.department_id == user.department_id, User.role == "admin", User.is_deleted == 0
            )
        )
        admin_count = result.scalar()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the only admin in the department",
            )

    # Cannot delete own account.
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    # Check whether already deleted.
    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user has already been deleted",
        )

    deletion_detail = f"deleteuser: {user.username}, ID: {user.id}, role: {user.role}"

    # Soft delete: mark deletion status and desensitize fields.
    import hashlib

    # Generate 4-character hash (based on user_id + id) to avoid naming collisions.
    hash_suffix = hashlib.sha256(
        f"{user.user_id}:{user.id}".encode()).hexdigest()[:4]

    user.is_deleted = 1
    user.deleted_at = utc_now_naive()
    user.username = f"deactivated-user-{hash_suffix}"
    # Clear phone number so it can be reused by other users.
    user.phone_number = None
    user.password_hash = "DELETED"  # Disable login.
    user.avatar = None  # Clear avatar.

    await db.commit()

    # Record operation.
    await log_operation(db, current_user.id, "deleteuser", deletion_detail, request)

    return {"success": True, "message": "User deleted"}


# Route: validate username and generate user_id
@auth.post("/validate-username", response_model=UserIdGeneration)
async def validate_username_and_generate_user_id(
    validation_data: UsernameValidation,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate username format and generate available user_id."""
    # Validate username format.
    is_valid, error_msg = validate_username(validation_data.username)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Check whether username already exists.
    result = await db.execute(select(User).filter(User.username == validation_data.username))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Generate unique user_id.
    result = await db.execute(select(User.user_id))
    existing_user_ids = [user_id for (user_id,) in result.all()]
    user_id = generate_unique_user_id(
        validation_data.username, existing_user_ids)

    return UserIdGeneration(username=validation_data.username, user_id=user_id, is_available=True)


# Route: check whether user_id is available
@auth.get("/check-user-id/{user_id}")
async def check_user_id_availability(
    user_id: str, current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)
):
    """Check whether user_id is available."""
    result = await db.execute(select(User).filter(User.user_id == user_id))
    existing_user = result.scalar_one_or_none()
    return {"user_id": user_id, "is_available": existing_user is None}


# Route: upload user avatar
@auth.post("/upload-avatar")
async def upload_user_avatar(
    file: UploadFile = File(...), current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """Upload user avatar."""
    # Check file type.
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Only image files can be uploaded")

    # Check file size (5MB limit).
    file_size = 0
    file_content = await file.read()
    file_size = len(file_content)

    if file_size > 5 * 1024 * 1024:  # 5MB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="filesizecannot exceed5MB")

    try:
        # Get file extension.
        file_extension = file.filename.split(
            ".")[-1].lower() if file.filename and "." in file.filename else "jpg"

        # Upload to MinIO.
        file_name = f"avatar/{current_user.id}/{uuid.uuid4()}.{file_extension}"
        avatar_url = await aupload_file_to_minio("public", file_name, file_content)

        # Update user avatar.
        current_user.avatar = avatar_url
        await db.commit()

        # Record operation.
        await log_operation(db, current_user.id, "uploadavatar", f"updateavatar: {avatar_url}")

        return {"success": True, "avatar_url": avatar_url, "message": "avataruploadsuccessful"}

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"avataruploadfailed: {str(e)}")


# Route: impersonate user login (superadmin only)
@auth.post("/impersonate/{user_id}", response_model=Token)
async def impersonate_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Superadmin impersonates another user login."""
    # Find target user.
    result = await db.execute(select(User).filter(User.id == user_id, User.is_deleted == 0))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="userdoes not exist",
        )

    # Cannot impersonate superadmin.
    if target_user.role == "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot impersonate superadmin account",
        )

    # Generate access token.
    token_data = {"sub": str(target_user.id)}
    access_token = AuthUtils.create_access_token(token_data)

    # Get department name.
    department_name = None
    if target_user.department_id:
        result = await db.execute(select(Department.name).filter(Department.id == target_user.department_id))
        department_name = result.scalar_one_or_none()

    # Record operation (dangerous operation marker).
    await log_operation(db, current_user.id, "dangerous_impersonate_user", f"Impersonate user: {target_user.username}", request)

    # Console warning log.
    logger.warning(
        f"[Dangerous operation] superadmin {current_user.username} impersonated user: {target_user.username}"
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": target_user.id,
        "username": target_user.username,
        "user_id_login": target_user.user_id,
        "phone_number": target_user.phone_number,
        "avatar": target_user.avatar,
        "role": target_user.role,
        "department_id": target_user.department_id,
        "department_name": department_name,
    }


# =============================================================================
# === OIDC authenticationgroup ===
# =============================================================================

@auth.get("/oidc/config", response_model=OIDCConfigResponse)
async def get_oidc_config():
    """Get OIDC configuration (for frontend use)."""
    return await get_oidc_config_handler()


@auth.get("/oidc/login-url")
async def get_oidc_login_url(redirect_path: str = "/"):
    """get OIDC login URL"""
    return await oidc_login_url_handler(redirect_path)


@auth.get("/oidc/callback", response_class=RedirectResponse)
async def oidc_callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """Process OIDC callback - redirect to frontend Vue route."""
    return await oidc_callback_handler(code, state, db, request)


@auth.post("/oidc/exchange-code", response_model=OIDCLoginResponse)
async def oidc_exchange_code(code: str = Body(..., embed=True)):
    """Exchange one-time code for OIDC login data."""
    return await oidc_exchange_code_handler(code)
