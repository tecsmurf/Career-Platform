"""
Backend Tests — API Integration Tests
======================================

Tests the full request lifecycle: HTTP → FastAPI → Service → Database → Response

Uses an in-memory SQLite database for testing (no PostgreSQL needed).
"""
import pytest
from httpx import AsyncClient

# Shared fixtures (test database, `client`, `auth_client`) live in conftest.py.


# ============================================================
# Auth Tests
# ============================================================
class TestAuth:
    async def test_register(self, client: AsyncClient):
        res = await client.post("/api/auth/register", json={
            "email": "alice@test.com",
            "password": "password123",
            "full_name": "Alice",
        })
        assert res.status_code == 201
        assert "access_token" in res.json()

    async def test_register_duplicate_email(self, client: AsyncClient):
        await client.post("/api/auth/register", json={
            "email": "dup@test.com", "password": "pass123", "full_name": "Dup",
        })
        res = await client.post("/api/auth/register", json={
            "email": "dup@test.com", "password": "pass123", "full_name": "Dup",
        })
        assert res.status_code == 409

    async def test_login(self, client: AsyncClient):
        # Register first
        await client.post("/api/auth/register", json={
            "email": "login@test.com", "password": "pass123", "full_name": "Login",
        })
        # Login
        res = await client.post("/api/auth/login", data={
            "username": "login@test.com", "password": "pass123",
        })
        assert res.status_code == 200
        assert "access_token" in res.json()

    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post("/api/auth/register", json={
            "email": "wrong@test.com", "password": "pass123", "full_name": "Wrong",
        })
        res = await client.post("/api/auth/login", data={
            "username": "wrong@test.com", "password": "wrongpass",
        })
        assert res.status_code == 401

    async def test_get_me(self, auth_client: AsyncClient):
        res = await auth_client.get("/api/auth/me")
        assert res.status_code == 200
        assert res.json()["email"] == "test@example.com"

    async def test_get_me_no_token(self, client: AsyncClient):
        res = await client.get("/api/auth/me")
        assert res.status_code == 401


# ============================================================
# Jobs Tests
# ============================================================
class TestJobs:
    async def test_create_job(self, auth_client: AsyncClient):
        res = await auth_client.post("/api/jobs", json={
            "company": "Google",
            "position": "ML Engineer",
            "status": "applied",
            "location": "Mountain View",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["company"] == "Google"
        assert data["position"] == "ML Engineer"

    async def test_list_jobs(self, auth_client: AsyncClient):
        # Create 2 jobs
        await auth_client.post("/api/jobs", json={"company": "Google", "position": "SWE"})
        await auth_client.post("/api/jobs", json={"company": "Meta", "position": "MLE"})

        res = await auth_client.get("/api/jobs")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        assert len(data["data"]) == 2

    async def test_filter_by_status(self, auth_client: AsyncClient):
        await auth_client.post("/api/jobs", json={"company": "A", "position": "X", "status": "applied"})
        await auth_client.post("/api/jobs", json={"company": "B", "position": "Y", "status": "interview"})

        res = await auth_client.get("/api/jobs", params={"status": "applied"})
        assert res.json()["total"] == 1
        assert res.json()["data"][0]["status"] == "applied"

    async def test_search_jobs(self, auth_client: AsyncClient):
        await auth_client.post("/api/jobs", json={"company": "Google", "position": "SWE"})
        await auth_client.post("/api/jobs", json={"company": "Meta", "position": "MLE"})

        res = await auth_client.get("/api/jobs", params={"search": "google"})
        assert res.json()["total"] == 1

    async def test_update_job(self, auth_client: AsyncClient):
        create_res = await auth_client.post("/api/jobs", json={"company": "Google", "position": "SWE"})
        job_id = create_res.json()["id"]

        res = await auth_client.put(f"/api/jobs/{job_id}", json={"status": "interview"})
        assert res.status_code == 200
        assert res.json()["status"] == "interview"

    async def test_delete_job(self, auth_client: AsyncClient):
        create_res = await auth_client.post("/api/jobs", json={"company": "Google", "position": "SWE"})
        job_id = create_res.json()["id"]

        res = await auth_client.delete(f"/api/jobs/{job_id}")
        assert res.status_code == 204

        # Verify deleted
        res = await auth_client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 404

    async def test_unauthorized_access(self, client: AsyncClient):
        res = await client.get("/api/jobs")
        assert res.status_code == 401

    async def test_cannot_access_other_users_jobs(self, auth_client: AsyncClient, client: AsyncClient):
        # Create job as test user
        create_res = await auth_client.post("/api/jobs", json={"company": "Google", "position": "SWE"})
        job_id = create_res.json()["id"]

        # Register another user
        res = await client.post("/api/auth/register", json={
            "email": "other@test.com", "password": "pass123", "full_name": "Other",
        })
        other_token = res.json()["access_token"]

        # Try to access with other user
        res = await client.get(f"/api/jobs/{job_id}", headers={
            "Authorization": f"Bearer {other_token}",
        })
        assert res.status_code == 403


# ============================================================
# Health Check Test
# ============================================================
class TestHealth:
    async def test_health(self, client: AsyncClient):
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    async def test_root(self, client: AsyncClient):
        res = await client.get("/")
        assert res.status_code == 200
        assert "AI Career Platform" in res.json()["app"]


# ============================================================
# Security / Validation Tests
# ============================================================
class TestSecurityAndValidation:
    async def test_invalid_email_domain_rejected(self, client: AsyncClient, monkeypatch):
        from app.services import auth_service

        async def _reject(domain: str) -> bool:
            return False

        monkeypatch.setattr(auth_service, "email_domain_deliverable", _reject)
        res = await client.post("/api/auth/register", json={
            "email": "nobody@totally-fake-domain.invalid",
            "password": "pass123",
            "full_name": "Nope",
        })
        assert res.status_code == 400

    async def test_invalid_status_rejected(self, auth_client: AsyncClient):
        res = await auth_client.post("/api/jobs", json={
            "company": "Google", "position": "SWE", "status": "banana",
        })
        assert res.status_code == 422

    async def test_saved_status_allowed(self, auth_client: AsyncClient):
        res = await auth_client.post("/api/jobs", json={
            "company": "Google", "position": "SWE", "status": "saved",
        })
        assert res.status_code == 201
        assert res.json()["status"] == "saved"

    async def test_salary_min_greater_than_max_rejected(self, auth_client: AsyncClient):
        res = await auth_client.post("/api/jobs", json={
            "company": "Google", "position": "SWE",
            "salary_min": 200000, "salary_max": 100000,
        })
        assert res.status_code == 422

    async def test_update_can_clear_nullable_field(self, auth_client: AsyncClient):
        create_res = await auth_client.post("/api/jobs", json={
            "company": "Google", "position": "SWE", "notes": "phone screen booked",
        })
        job_id = create_res.json()["id"]
        res = await auth_client.put(f"/api/jobs/{job_id}", json={"notes": None})
        assert res.status_code == 200
        assert res.json()["notes"] is None

    async def test_expired_token_rejected(self, client: AsyncClient):
        from app.services import auth_service
        token = auth_service.create_access_token(
            {"sub": "x@example.com", "user_id": 1}, expires_minutes=-1
        )
        res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    async def test_garbage_token_rejected(self, client: AsyncClient):
        res = await client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert res.status_code == 401
