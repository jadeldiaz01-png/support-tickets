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
