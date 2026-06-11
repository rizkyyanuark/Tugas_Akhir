"""
Integration tests for authentication-related API routes.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_login_with_invalid_credentials(test_client):
    response = await test_client.post("/api/auth/token", data={"username": "invalid", "password": "invalid"})
    assert response.status_code == 401
    assert "detail" in response.json()


async def test_user_is_locked_after_repeated_failed_logins(test_client, standard_user):
    user_id = standard_user["user"]["user_id"]

    for attempt in range(1, 5):
        response = await test_client.post("/api/auth/token", data={"username": user_id, "password": "wrong-password"})
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Invalid login identifier or password"

    locked_response = await test_client.post("/api/auth/token", data={"username": user_id, "password": "wrong-password"})
    assert locked_response.status_code == 423, locked_response.text
    assert "X-Lock-Remaining" in locked_response.headers
    assert "Account has been locked" in locked_response.json()["detail"]

    still_locked_response = await test_client.post(
        "/api/auth/token",
        data={"username": user_id, "password": standard_user["password"]},
    )
    assert still_locked_response.status_code == 423, still_locked_response.text
    assert "X-Lock-Remaining" in still_locked_response.headers
    assert "Login is locked" in still_locked_response.json()["detail"]


async def test_admin_can_login_and_fetch_profile(test_client, admin_headers):
    profile_response = await test_client.get("/api/auth/me", headers=admin_headers)
    assert profile_response.status_code == 200
    data = profile_response.json()
    assert data["role"] in {"admin", "superadmin"}
    assert data["username"]
    assert data["user_id"]


async def test_admin_can_create_and_delete_user(test_client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "username": f"rtu_{suffix}",
        "password": "routerTest123!",
        "role": "user",
    }
    create_response = await test_client.post("/api/auth/users", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text

    created_user = create_response.json()
    assert created_user["username"] == payload["username"]
    assert created_user["role"] == payload["role"]

    delete_response = await test_client.delete(f"/api/auth/users/{created_user['id']}", headers=admin_headers)
    assert delete_response.status_code == 200, delete_response.text
    delete_payload = delete_response.json()
    assert delete_payload["success"] is True
    assert delete_payload["message"] == "User deleted"


async def test_create_user_rejects_weak_password(test_client, admin_headers):
    response = await test_client.post(
        "/api/auth/users",
        json={
            "username": f"weak_{uuid.uuid4().hex[:8]}",
            "password": "weak-password",
            "role": "user",
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert "uppercase" in response.json()["detail"]


async def test_regular_admin_cannot_escalate_roles_or_cross_departments(test_client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    department_a = {
        "name": f"pytest_auth_a_{suffix}",
        "description": "Authentication isolation test A",
        "admin_user_id": f"auth_admin_{suffix}",
        "admin_password": "DepartmentAdmin123!",
    }
    department_b = {
        "name": f"pytest_auth_b_{suffix}",
        "description": "Authentication isolation test B",
        "admin_user_id": f"other_admin_{suffix}",
        "admin_password": "OtherDepartment123!",
    }
    department_ids = []
    created_user_ids = []

    try:
        response_a = await test_client.post("/api/departments", json=department_a, headers=admin_headers)
        response_b = await test_client.post("/api/departments", json=department_b, headers=admin_headers)
        assert response_a.status_code == 201, response_a.text
        assert response_b.status_code == 201, response_b.text
        department_ids.extend([response_a.json()["id"], response_b.json()["id"]])

        login_response = await test_client.post(
            "/api/auth/token",
            data={
                "username": department_a["admin_user_id"],
                "password": department_a["admin_password"],
            },
        )
        assert login_response.status_code == 200, login_response.text
        regular_admin_headers = {
            "Authorization": f"Bearer {login_response.json()['access_token']}",
        }

        local_user_response = await test_client.post(
            "/api/auth/users",
            json={
                "username": f"local_user_{suffix}",
                "password": "LocalAcademic123!",
                "role": "user",
            },
            headers=regular_admin_headers,
        )
        assert local_user_response.status_code == 200, local_user_response.text
        local_user_id = local_user_response.json()["id"]
        created_user_ids.append(local_user_id)

        outsider_response = await test_client.post(
            "/api/auth/users",
            json={
                "username": f"outside_user_{suffix}",
                "password": "OutsideAcademic123!",
                "role": "user",
                "department_id": department_ids[1],
            },
            headers=admin_headers,
        )
        assert outsider_response.status_code == 200, outsider_response.text
        outsider_user_id = outsider_response.json()["id"]
        created_user_ids.append(outsider_user_id)

        escalation_response = await test_client.put(
            f"/api/auth/users/{local_user_id}",
            json={"role": "admin"},
            headers=regular_admin_headers,
        )
        assert escalation_response.status_code == 403, escalation_response.text

        cross_department_response = await test_client.get(
            f"/api/auth/users/{outsider_user_id}",
            headers=regular_admin_headers,
        )
        assert cross_department_response.status_code == 403, cross_department_response.text
    finally:
        users_response = await test_client.get("/api/auth/users", headers=admin_headers)
        if users_response.status_code == 200:
            department_admin_ids = {
                user["id"]
                for user in users_response.json()
                if user["user_id"] in {
                    department_a["admin_user_id"],
                    department_b["admin_user_id"],
                }
            }
            created_user_ids.extend(department_admin_ids)

        for user_id in dict.fromkeys(created_user_ids):
            await test_client.delete(f"/api/auth/users/{user_id}", headers=admin_headers)
        for department_id in department_ids:
            await test_client.delete(f"/api/departments/{department_id}", headers=admin_headers)


async def test_invalid_token_is_rejected(test_client):
    headers = {"Authorization": "Bearer not-a-real-token"}
    response = await test_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
