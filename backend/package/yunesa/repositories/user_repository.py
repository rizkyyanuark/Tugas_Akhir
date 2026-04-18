"""User data access layer - Repository."""

from datetime import UTC
from datetime import datetime as dt
from typing import Annotated, Any

from sqlalchemy import func, select

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import User

# Use naive datetime to match PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns.
_utc_now = dt.now(UTC).replace(tzinfo=None)


class UserRepository:
    """User data access layer."""

    async def get_by_id(self, id: int) -> User | None:
        """Get user by numeric ID."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User).where(User.id == id))
            return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: str) -> User | None:
        """Get user by logical user_id."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        """Get user by phone number."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User).where(User.phone_number == phone))
            return result.scalar_one_or_none()

    async def list_users(
        self, skip: int = 0, limit: int = 100, department_id: int | None = None, role: str | None = None
    ) -> list[User]:
        """List users."""
        async with pg_manager.get_async_session_context() as session:
            query = select(User).where(User.is_deleted == 0)
            if department_id is not None:
                query = query.where(User.department_id == department_id)
            if role is not None:
                query = query.where(User.role == role)
            query = query.order_by(User.id.asc()).offset(skip).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def list_with_department(
        self, skip: int = 0, limit: int = 100, department_id: int | None = None, role: str | None = None
    ) -> Annotated[list[tuple[User, str | None]], "User list including department name"]:
        """List users with department names."""
        async with pg_manager.get_async_session_context() as session:
            from yunesa.storage.postgres.models_business import Department

            query = (
                select(User, Department.name.label("department_name"))
                .outerjoin(Department, User.department_id == Department.id)
                .where(User.is_deleted == 0)
            )
            if department_id is not None:
                query = query.where(User.department_id == department_id)
            if role is not None:
                query = query.where(User.role == role)
            query = query.order_by(User.id.asc()).offset(skip).limit(limit)
            result = await session.execute(query)
            return list(result.all())

    async def create(self, data: dict[str, Any]) -> User:
        """Create user."""
        async with pg_manager.get_async_session_context() as session:
            user = User(**data)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    async def update(self, id: int, data: dict[str, Any]) -> User | None:
        """Update user."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User).where(User.id == id, User.is_deleted == 0))
            user = result.scalar_one_or_none()
            if user is None:
                return None
            for key, value in data.items():
                if key != "id":
                    setattr(user, key, value)
        return user

    async def soft_delete(self, id: int, username: str | None = None, phone_number: str | None = None) -> bool:
        """Soft-delete user."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User).where(User.id == id, User.is_deleted == 0))
            user = result.scalar_one_or_none()
            if user is None:
                return False
            user.is_deleted = 1

            user.deleted_at = _utc_now()
            if username:
                import hashlib

                hash_suffix = hashlib.sha256(
                    user.user_id.encode()).hexdigest()[:4]
                user.username = f"logoutuser-{hash_suffix}"
            if phone_number:
                user.phone_number = None
        return True

    async def exists_by_user_id(self, user_id: str) -> bool:
        """Check whether user_id exists."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User.id).where(User.user_id == user_id))
            return result.scalar_one_or_none() is not None

    async def exists_by_phone(self, phone: str) -> bool:
        """Check whether phone number exists."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User.id).where(User.phone_number == phone))
            return result.scalar_one_or_none() is not None

    async def count(self, department_id: int | None = None) -> int:
        """Count users."""
        async with pg_manager.get_async_session_context() as session:
            query = select(func.count(User.id)).where(User.is_deleted == 0)
            if department_id is not None:
                query = query.where(User.department_id == department_id)
            result = await session.execute(query)
            return result.scalar() or 0

    async def get_all_user_ids(self) -> list[str]:
        """Get all user IDs."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(User.user_id))
            return [uid for (uid,) in result.all()]

    async def get_admin_count_in_department(self, department_id: int, exclude_user_id: int | None = None) -> int:
        """Count admins in a department."""
        async with pg_manager.get_async_session_context() as session:
            query = select(func.count(User.id)).where(
                User.department_id == department_id, User.role == "admin", User.is_deleted == 0
            )
            if exclude_user_id is not None:
                query = query.where(User.id != exclude_user_id)
            result = await session.execute(query)
            return result.scalar() or 0
