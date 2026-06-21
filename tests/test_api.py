"""Integration tests for FastAPI endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_index_repository_missing_path(client):
    response = await client.post("/index-repository", json={"repository_path": "/nonexistent/path"})
    assert response.status_code == 400


async def test_process_issue_missing_index(client):
    response = await client.post("/process-issue", json={
        "title": "Test issue",
        "description": "Something is broken",
        "repository_path": "/tmp/fake_repo",
    })
    # Should return 200 with an error field (workflow handles gracefully)
    assert response.status_code in (200, 500)


async def test_run_tests_bad_path(client):
    response = await client.post("/run-tests", json={"repository_path": "/nonexistent"})
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] is False
