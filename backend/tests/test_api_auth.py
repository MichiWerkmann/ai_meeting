from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.auth import AuthService


client = TestClient(app)


def _create_auth_service(tmp_path):
    return AuthService(file_path=tmp_path / "runtime_users_test.json", session_ttl_seconds=3600)


def test_register_and_get_current_user(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app.main.auth_service", _create_auth_service(tmp_path))

    register_response = client.post(
        "/api/auth/register",
        json={
            "name": "Max Mustermann",
            "email": "max@example.com",
            "password": "sehrsicher123",
        },
    )

    assert register_response.status_code == 200
    body = register_response.json()
    assert body["token"]
    assert body["user"]["email"] == "max@example.com"

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['token']}"},
    )
    assert me_response.status_code == 200
    me = me_response.json()
    assert me["name"] == "Max Mustermann"
    assert me["email"] == "max@example.com"


def test_login_rejects_invalid_password(monkeypatch, tmp_path):
    auth_service = _create_auth_service(tmp_path)
    auth_service.register_user(name="Max Mustermann", email="max@example.com", password="sehrsicher123")
    monkeypatch.setattr("backend.app.main.auth_service", auth_service)

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "max@example.com",
            "password": "falschpasswort",
        },
    )
    assert login_response.status_code == 401


def test_job_list_uses_authenticated_user_scope(monkeypatch, tmp_path):
    auth_service = _create_auth_service(tmp_path)
    user, token = auth_service.register_user(
        name="Max Mustermann",
        email="max@example.com",
        password="sehrsicher123",
    )
    monkeypatch.setattr("backend.app.main.auth_service", auth_service)

    captured = {}

    def _fake_list_jobs(owner_id):
        captured["owner_id"] = owner_id
        return []

    monkeypatch.setattr("backend.app.main.async_job_service.list_jobs", _fake_list_jobs)

    response = client.get(
        "/api/transcribe/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []
    assert captured["owner_id"] == user["id"]


def test_logout_invalidates_token(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app.main.auth_service", _create_auth_service(tmp_path))
    register_response = client.post(
        "/api/auth/register",
        json={
            "name": "Max Mustermann",
            "email": "max@example.com",
            "password": "sehrsicher123",
        },
    )
    token = register_response.json()["token"]

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_response.status_code == 204

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 401
