"""Dashboard contract, fail-closed authorization and isolation checks.

Offline tests use dependency overrides; PostgreSQL tests require the CI database.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_actor_context, get_db
from application.dashboard import TicketDashboardService
from security.context import ActorContext


def _headers():  # intentionally no access tokens in tests
    return {}


@pytest.fixture
def controlled_client(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    actor = ActorContext(
        tenant_id=uuid4(), actor_id=uuid4(),
        role="SUPERVISOR", external_subject="test:supervisor",
    )
    app.dependency_overrides[get_actor_context] = lambda: actor
    app.dependency_overrides[get_db] = lambda: object()
    try:
        yield TestClient(app), actor
    finally:
        app.dependency_overrides.clear()


def test_dashboard_requires_real_auth_when_not_overridden(monkeypatch):
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "disabled")
    monkeypatch.setenv("SUPPORT_ENV", "dev")
    response = TestClient(app).get(
        "/v1/dashboards/tickets/summary?start=2026-10-01&end=2026-10-02"
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "start,end", [
        ("2026-10-01", "2026-10-01"),
        ("2026-10-02", "2026-10-01"),
        ("2026-01-01", "2026-10-13"),
    ],
)
def test_dashboard_rejects_invalid_or_expensive_windows(controlled_client, start, end):
    client, _ = controlled_client
    response = client.get(
        "/v1/dashboards/tickets/summary",
        params={"start": start, "end": end},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("role", ["SUPPORT_AGENT", "CUSTOMER", "SYSTEM_WORKER"])
def test_dashboard_denies_unprivileged_roles(controlled_client, role):
    client, actor = controlled_client
    app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id,
        role=role, external_subject="test:user",
    )
    response = client.get(
        "/v1/dashboards/tickets/summary?start=2026-10-01&end=2026-10-02"
    )
    assert response.status_code == 403


def test_dashboard_returns_safe_summary_no_pii(controlled_client, monkeypatch):
    client, actor = controlled_client
    captured = {}

    def fake_summary(self, *, actor, start, end):
        captured["tenant_id"] = actor.tenant_id
        return {
            "start": start, "end": end, "timezone": "UTC",
            "cohort_definition": "TICKETS_CREATED_IN_WINDOW_CURRENT_STATE",
            "total_created": 1,
            "status_counts": {
                "OPEN": 1, "IN_PROGRESS": 0, "WAITING_CUSTOMER": 0,
                "RESOLVED": 0, "CLOSED": 0,
            },
            "priority_counts": {
                "LOW": 0, "MEDIUM": 1, "HIGH": 0, "CRITICAL": 0,
            },
            "created_by_day": [{"day": start, "count": 1}],
            "generated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr(TicketDashboardService, "get_summary", fake_summary)
    response = client.get(
        "/v1/dashboards/tickets/summary?start=2026-10-01&end=2026-10-02"
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total_created"] == 1
    assert result["timezone"] == "UTC"
    assert "subject" not in str(result)
    assert "customer_id" not in str(result)
    assert captured["tenant_id"] == actor.tenant_id


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_OWNER"),
    reason="PostgreSQL integration database not configured",
)
def test_dashboard_real_postgres_tenant_isolation_and_cohort(monkeypatch):
    from tests.test_postgres_foundation import seed

    tenant_a, tenant_b, user_a, user_b, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    created = client.post(
        "/v1/tickets",
        headers={
            "X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
            "X-Role": "SUPPORT_AGENT", "Idempotency-Key": "dashboard-tenant-a",
        },
        json={"customer_id": str(customer_a), "subject": "Private", "body": "Secret"},
    )
    assert created.status_code == 201
    a = client.get(
        "/v1/dashboards/tickets/summary",
        params={"start": start, "end": end},
        headers={
            "X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
            "X-Role": "SUPERVISOR",
        },
    )
    b = client.get(
        "/v1/dashboards/tickets/summary",
        params={"start": start, "end": end},
        headers={
            "X-Tenant-ID": str(tenant_b), "X-Actor-ID": str(user_b),
            "X-Role": "SUPERVISOR",
        },
    )
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["total_created"] == 1
    assert a.json()["status_counts"]["OPEN"] == 1
    assert b.json()["total_created"] == 0
    assert "Private" not in str(a.json())
    assert "Secret" not in str(a.json())
