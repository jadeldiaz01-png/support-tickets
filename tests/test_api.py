from fastapi.testclient import TestClient

from api.main import app


def test_liveness_is_public_and_non_authoritative() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ticket_api_fails_closed_without_identity_provider(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_ENV", "dev")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "disabled")
    response = TestClient(app).post(
        "/v1/tickets",
        headers={"Idempotency-Key": "12345678"},
        json={"subject": "Example", "body": "Example body"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_NOT_CONFIGURED"


def test_production_rejects_test_header_authentication(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    response = TestClient(app).post(
        "/v1/tickets",
        headers={
            "Idempotency-Key": "12345678",
            "X-Tenant-ID": "11111111-1111-1111-1111-111111111111",
            "X-Actor-ID": "22222222-2222-2222-2222-222222222222",
            "X-Role": "ADMIN",
        },
        json={"subject": "Example", "body": "Example body"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_NOT_CONFIGURED"


def test_oidc_mode_requires_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "oidc")
    response = TestClient(app).post(
        "/v1/tickets",
        headers={"Idempotency-Key": "12345678"},
        json={"subject": "Example", "body": "Example body"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "BEARER_TOKEN_REQUIRED"
