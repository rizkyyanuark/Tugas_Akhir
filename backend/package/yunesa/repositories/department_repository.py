"""Department data access layer - Repository."""

from typing import Any

from sqlalchemy import func, select

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import Department


class DepartmentRepository:
    """Department data access layer."""

    async def get_by_id(self, id: int) -> Department | None:
        """Get department by ID."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department).where(Department.id == id))
            return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Department | None:
        """Get department by name."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department).where(Department.name == name))
            return result.scalar_one_or_none()

    async def list_departments(self) -> list[Department]:
        """Get all departments."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department).order_by(Department.created_at.desc()))
            return list(result.scalars().all())

    async def list_with_user_count(self) -> list[dict[str, Any]]:
        """Get all departments with user count."""
        async with pg_manager.get_async_session_context() as session:
            from yunesa.storage.postgres.models_business import User

            result = await session.execute(select(Department).order_by(Department.created_at.desc()))
            departments = result.scalars().all()

            department_list = []
            for dep in departments:
                user_count_result = await session.execute(
                    select(func.count(User.id)).where(
                        User.department_id == dep.id, User.is_deleted == 0)
                )
                user_count = user_count_result.scalar()
                dep_dict = dep.to_dict()
                dep_dict["user_count"] = user_count
                department_list.append(dep_dict)

            return department_list

    async def create(self, data: dict[str, Any]) -> Department:
        """Create department."""
        async with pg_manager.get_async_session_context() as session:
            department = Department(**data)
            session.add(department)
        return department

    async def update(self, id: int, data: dict[str, Any]) -> Department | None:
        """Update department."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department).where(Department.id == id))
            department = result.scalar_one_or_none()
            if department is None:
                return None
            for key, value in data.items():
                if key != "id":
                    setattr(department, key, value)
        return department

    async def delete(self, id: int) -> bool:
        """Delete department."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department).where(Department.id == id))
            department = result.scalar_one_or_none()
            if department is None:
                return False
            await session.delete(department)
        return True

    async def count_users(self, id: int) -> int:
        """Count users in a department."""
        async with pg_manager.get_async_session_context() as session:
            from yunesa.storage.postgres.models_business import User

            result = await session.execute(
                select(func.count(User.id)).where(
                    User.department_id == id, User.is_deleted == 0)
            )
            return result.scalar() or 0

    async def exists_by_name(self, name: str) -> bool:
        """Check whether a department name exists."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(Department.id).where(Department.name == name))
            return result.scalar_one_or_none() is not None
