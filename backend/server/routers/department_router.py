"""
Department management routes.
Provides department CRUD endpoints, accessible only to superadmin users.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import delete as sqlalchemy_delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.storage.postgres.models_business import APIKey, AgentConfig, Department, User
from yunesa.repositories.department_repository import DepartmentRepository
from yunesa.repositories.user_repository import UserRepository
from server.utils.auth_middleware import get_superadmin_user, get_admin_user, get_db
from server.utils.auth_utils import AuthUtils
from server.utils.common_utils import log_operation
from server.utils.user_utils import is_valid_phone_number

# Create router.
department = APIRouter(prefix="/departments", tags=["department"])


# =============================================================================
# === Request and Response Models ===
# =============================================================================


class DepartmentCreate(BaseModel):
    """Create department request."""

    name: str
    description: str | None = None
    # Required admin info.
    admin_user_id: str
    admin_password: str
    admin_phone: str | None = None


class DepartmentCreateWithoutAdmin(BaseModel):
    """Create department request (without admin, for compatibility)."""

    name: str
    description: str | None = None


class DepartmentUpdate(BaseModel):
    """Update department request."""

    name: str | None = None
    description: str | None = None


class DepartmentResponse(BaseModel):
    """Department response."""

    id: int
    name: str
    description: str | None = None
    created_at: str
    user_count: int = 0


# =============================================================================
# === Department Management Routes ===
# =============================================================================


@department.get("", response_model=list[DepartmentResponse])
async def get_departments(current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """Get all departments (admin accessible)."""
    dept_repo = DepartmentRepository()
    return await dept_repo.list_with_user_count()


@department.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(
    department_id: int, current_user: User = Depends(get_superadmin_user), db: AsyncSession = Depends(get_db)
):
    """Get details of the specified department."""
    result = await db.execute(select(Department).filter(Department.id == department_id))
    department = result.scalar_one_or_none()

    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Department does not exist")

    # Get user count under this department.
    user_count_result = await db.execute(
        select(func.count(User.id)).filter(
            User.department_id == department_id, User.is_deleted == 0)
    )
    user_count = user_count_result.scalar()

    return {**department.to_dict(), "user_count": user_count}


@department.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    department_data: DepartmentCreate,
    request: Request,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new department and its admin account."""
    dept_repo = DepartmentRepository()
    user_repo = UserRepository()

    # Check whether department name already exists.
    if await dept_repo.exists_by_name(department_data.name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Department name already exists")

    # Verify admin user_id format.
    admin_user_id = department_data.admin_user_id
    if not re.match(r"^[a-zA-Z0-9_]+$", admin_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID can only contain letters, numbers, and underscores",
        )

    if len(admin_user_id) < 3 or len(admin_user_id) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID length must be between 3 and 20 characters",
        )

    # Check whether user_id already exists.
    if await user_repo.exists_by_user_id(admin_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID already exists",
        )

    # Check whether phone number already exists (if provided).
    admin_phone = department_data.admin_phone
    if admin_phone:
        if not is_valid_phone_number(admin_phone):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Phone number format is invalid")
        if await user_repo.exists_by_phone(admin_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already exists",
            )

    # Create department.
    new_department = await dept_repo.create(
        {
            "name": department_data.name,
            "description": department_data.description,
        }
    )

    # Create admin user.
    hashed_password = AuthUtils.hash_password(department_data.admin_password)
    await user_repo.create(
        {
            "username": admin_user_id,
            "user_id": admin_user_id,
            "phone_number": admin_phone,
            "password_hash": hashed_password,
            "role": "admin",
            "department_id": new_department.id,
        }
    )

    # Record operation.
    await log_operation(
        db,
        current_user.id,
        "createdepartment",
        f"Create department: {department_data.name}, and create admin: {admin_user_id}",
        request,
    )

    return {**new_department.to_dict(), "user_count": 1}


@department.put("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: int,
    department_data: DepartmentUpdate,
    request: Request,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update department information."""
    result = await db.execute(select(Department).filter(Department.id == department_id))
    department = result.scalar_one_or_none()

    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Department does not exist")

    # If modifying name, check whether the new name already exists.
    if department_data.name and department_data.name != department.name:
        result = await db.execute(select(Department).filter(Department.name == department_data.name))
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Department name already exists")
        department.name = department_data.name

    if department_data.description is not None:
        department.description = department_data.description

    await db.commit()
    await db.refresh(department)

    # Record operation.
    await log_operation(db, current_user.id, "updatedepartment", f"Update department: {department.name}", request)

    # Get user count under this department.
    user_count_result = await db.execute(
        select(func.count(User.id)).filter(
            User.department_id == department_id, User.is_deleted == 0)
    )
    user_count = user_count_result.scalar()

    return {**department.to_dict(), "user_count": user_count}


@department.delete("/{department_id}", status_code=status.HTTP_200_OK)
async def delete_department(
    department_id: int,
    request: Request,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a department."""
    # Check whether department exists.
    result = await db.execute(select(Department).filter(Department.id == department_id))
    department = result.scalar_one_or_none()

    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Department does not exist")

    if department.id == 1:  # Default department ID is 1.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Default department cannot be deleted")

    department_name = department.name
    result = await db.execute(select(User).filter(User.department_id == department_id))
    department_users = result.scalars().all()

    if department_users:
        for user in department_users:
            user.department_id = 1  # Migrate users to the default department.

    await db.execute(sqlalchemy_delete(AgentConfig).where(AgentConfig.department_id == department_id))
    await db.execute(sqlalchemy_delete(APIKey).where(APIKey.department_id == department_id))
    await db.delete(department)
    await db.commit()

    # Record operation.
    if department_users:
        detail = f"Delete department: {department_name}, migrated {len(department_users)} users to default department"
    else:
        detail = f"Delete department: {department_name}"
    await log_operation(db, current_user.id, "deletedepartment", detail, request)

    return {"success": True, "message": "Department deleted"}
