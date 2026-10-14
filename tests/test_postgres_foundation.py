from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from api.main import app
from repositories.db import bind_tenant, get_engine
from security.context import _resolve_oidc_actor
from security.oidc import OIDCIdentity

OWNER_URL = os.environ.get("DATABASE_URL_OWNER")

pytestmark = pytest.mark.skipif(
    not OWNER_URL,
    reason="PostgreSQL integration database not configured",
)


def seed() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    owner = create_engine(OWNER_URL, future=True)
    tenant_a, tenant_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    customer_a = uuid4()

    with owner.begin() as conn:
        conn.execute(
            text(
                """
                TRUNCATE TABLE
                    reconciliation_records, outbox_events, tool_intents,
                    approval_requests, ticket_sla_state, ticket_tags,
                    ticket_assignments, ticket_events, ticket_messages,
                    audit_events, knowledge_sources, tickets, customers,
                    users, tenants
                CASCADE
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO tenants (id, slug) "
                "VALUES (:a, 'tenant-a'), (:b, 'tenant-b')"
            ),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, tenant_id, external_subject, role)
                VALUES
                    (:ua, :ta, 'user-a', 'SUPPORT_AGENT'),
                    (:ub, :tb, 'user-b', 'SUPPORT_AGENT')
                """
            ),
            {"ua": user_a, "ta": tenant_a, "ub": user_b, "tb": tenant_b},
        )
        conn.execute(
            text(
                """
                INSERT INTO customers (id, tenant_id, external_ref, display_name)
                VALUES (:id, :tenant_id, 'customer-a', 'Customer A')
                """
            ),
            {"id": customer_a, "tenant_id": tenant_a},
        )
    owner.dispose()
    return tenant_a, tenant_b, user_a, user_b, customer_a


def test_create_ticket_is_idempotent_and_emits_outbox(monkeypatch) -> None:
    tenant_a, _, user_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")

    client = TestClient(app)
    headers = {
        "X-Tenant-ID": str(tenant_a),
        "X-Actor-ID": str(user_a),
        "X-Role": "SUPPORT_AGENT",
        "Idempotency-Key": "idem-foundation-0001",
    }
    payload = {
        "customer_id": str(customer_a),
        "subject": "Cannot sign in",
        "body": "Login fails after password reset.",
        "priority": "HIGH",
    }

    first = client.post("/v1/tickets", headers=headers, json=payload)
    second = client.post("/v1/tickets", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        ticket_count = conn.execute(text("SELECT count(*) FROM tickets")).scalar_one()
        outbox_count = conn.execute(
            text("SELECT count(*) FROM outbox_events")
        ).scalar_one()
        audit_count = conn.execute(
            text("SELECT count(*) FROM audit_events")
        ).scalar_one()
    owner.dispose()

    assert ticket_count == 1
    assert outbox_count == 1
    assert audit_count == 1


def test_row_level_security_blocks_cross_tenant_read(monkeypatch) -> None:
    tenant_a, tenant_b, user_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")

    client = TestClient(app)
    response = client.post(
        "/v1/tickets",
        headers={
            "X-Tenant-ID": str(tenant_a),
            "X-Actor-ID": str(user_a),
            "X-Role": "SUPPORT_AGENT",
            "Idempotency-Key": "idem-foundation-0002",
        },
        json={
            "customer_id": str(customer_a),
            "subject": "Tenant isolation",
            "body": "This ticket belongs only to tenant A.",
        },
    )
    assert response.status_code == 201
    ticket_id = response.json()["id"]

    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, tenant_b)
            visible = session.execute(
                text("SELECT count(*) FROM tickets WHERE id = :id"),
                {"id": ticket_id},
            ).scalar_one()
    assert visible == 0


def test_oidc_subject_is_bound_to_existing_tenant_user() -> None:
    tenant_a, _, user_a, _, _ = seed()

    actor = _resolve_oidc_actor(
        OIDCIdentity(
            tenant_id=tenant_a,
            external_subject="user-a",
            role="SUPPORT_AGENT",
        )
    )

    assert actor.tenant_id == tenant_a
    assert actor.actor_id == user_a
    assert actor.role == "SUPPORT_AGENT"
    assert actor.external_subject == "user-a"


def test_oidc_subject_cannot_cross_tenant_boundary() -> None:
    tenant_a, _, _, _, _ = seed()

    with pytest.raises(HTTPException) as caught:
        _resolve_oidc_actor(
            OIDCIdentity(
                tenant_id=tenant_a,
                external_subject="user-b",
                role="SUPPORT_AGENT",
            )
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "IDENTITY_NOT_BOUND"


def test_oidc_role_must_match_durable_user_role() -> None:
    tenant_a, _, _, _, _ = seed()

    with pytest.raises(HTTPException) as caught:
        _resolve_oidc_actor(
            OIDCIdentity(
                tenant_id=tenant_a,
                external_subject="user-a",
                role="ADMIN",
            )
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "IDENTITY_NOT_BOUND"


def test_dashboard_postgres_isolation_and_no_pii(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    tenant_a, tenant_b, user_a, user_b, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)

    now = datetime.now(timezone.utc).date()
    params = {
        "start": (now - timedelta(days=1)).isoformat(),
        "end": (now + timedelta(days=1)).isoformat(),
    }
    result = client.post(
        "/v1/tickets",
        headers={
            "X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
            "X-Role": "SUPPORT_AGENT", "Idempotency-Key": "dashboard-isolation-a1",
        },
        json={
            "customer_id": str(customer_a),
            "subject": "Confidential customer subject",
            "body": "Confidential customer body",
        },
    )
    assert result.status_code == 201

    def get_summary(tenant, user):
        return client.get(
            "/v1/dashboards/tickets/summary", params=params,
            headers={
                "X-Tenant-ID": str(tenant),
                "X-Actor-ID": str(user),
                "X-Role": "SUPERVISOR",
            },
        )

    tenant_a_summary = get_summary(tenant_a, user_a)
    tenant_b_summary = get_summary(tenant_b, user_b)

    assert tenant_a_summary.status_code == 200
    assert tenant_b_summary.status_code == 200
    assert tenant_a_summary.json()["total_created"] == 1
    assert tenant_a_summary.json()["status_counts"]["OPEN"] == 1
    assert tenant_a_summary.json()["priority_counts"]["MEDIUM"] == 1
    assert tenant_b_summary.json()["total_created"] == 0
    assert "Confidential" not in str(tenant_a_summary.json())


def test_ticket_create_rejects_foreign_tenant_customer_reference(monkeypatch) -> None:
    tenant_a, tenant_b, _, user_b, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    response = TestClient(app).post(
        "/v1/tickets",
        headers={
            "X-Tenant-ID": str(tenant_b),
            "X-Actor-ID": str(user_b),
            "X-Role": "SUPPORT_AGENT",
            "Idempotency-Key": "deny-cross-tenant-reference",
        },
        json={
            "customer_id": str(customer_a),
            "subject": "Attempt to attach foreign customer",
            "body": "Must be rejected",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "CUSTOMER_NOT_FOUND"

    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM tickets")).scalar_one() == 0
    owner.dispose()


def test_ticket_idempotency_key_is_bound_to_full_intent(monkeypatch) -> None:
    tenant_a, _, user_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)
    headers = {
        "X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
        "X-Role": "SUPPORT_AGENT", "Idempotency-Key": "fingerprinted-request-1",
    }
    payload = {"customer_id": str(customer_a), "subject": "Original",
               "body": "Private original", "priority": "HIGH"}
    first = client.post("/v1/tickets", headers=headers, json=payload)
    repeat = client.post("/v1/tickets", headers=headers, json=payload)
    altered = client.post(
        "/v1/tickets", headers=headers, json={**payload, "body": "Altered intent"}
    )
    assert first.status_code == 201
    assert repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert altered.status_code == 409
    assert altered.json()["detail"] == "IDEMPOTENCY_KEY_REUSED"

    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM tickets")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM ticket_messages")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM outbox_events")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1
    owner.dispose()


def test_legacy_idempotency_key_fails_closed(monkeypatch) -> None:
    tenant_a, _, user_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    headers = {"X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
               "X-Role": "SUPPORT_AGENT", "Idempotency-Key": "old-unfingerprinted"}
    payload = {"customer_id": str(customer_a), "subject": "Before migration", "body": "One"}
    client = TestClient(app)
    created = client.post("/v1/tickets", headers=headers, json=payload)
    assert created.status_code == 201
    owner = create_engine(OWNER_URL, future=True)
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE tickets SET request_sha256 = NULL WHERE id = :ticket_id"),
            {"ticket_id": created.json()["id"]},
        )
    owner.dispose()
    replay = client.post("/v1/tickets", headers=headers, json=payload)
    assert replay.status_code == 409
    assert replay.json()["detail"] == "IDEMPOTENCY_LEGACY_KEY"


def test_ticket_status_transition_is_atomic_versioned_and_dashboard_consistent(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    tenant_a, tenant_b, user_a, user_b, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)

    def headers(tenant, user):
        return {"X-Tenant-ID": str(tenant), "X-Actor-ID": str(user),
                "X-Role": "SUPPORT_AGENT"}

    original = client.post(
        "/v1/tickets",
        headers={**headers(tenant_a, user_a), "Idempotency-Key": "transition-test-key"},
        json={"customer_id": str(customer_a), "subject": "Transition", "body": "Private"},
    )
    assert original.status_code == 201
    ticket_id = original.json()["id"]
    endpoint = f"/v1/tickets/{ticket_id}/status"

    invalid = client.patch(
        endpoint, headers=headers(tenant_a, user_a),
        json={"status": "CLOSED", "expected_version": 1},
    )
    cross_tenant = client.patch(
        endpoint, headers=headers(tenant_b, user_b),
        json={"status": "IN_PROGRESS", "expected_version": 1},
    )
    updated = client.patch(
        endpoint, headers=headers(tenant_a, user_a),
        json={"status": "IN_PROGRESS", "expected_version": 1},
    )
    stale = client.patch(
        endpoint, headers=headers(tenant_a, user_a),
        json={"status": "IN_PROGRESS", "expected_version": 1},
    )

    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "TICKET_INVALID_TRANSITION"
    assert cross_tenant.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["status"] == "IN_PROGRESS"
    assert stale.status_code == 409
    assert stale.json()["detail"] == "TICKET_VERSION_CONFLICT"

    now = datetime.now(timezone.utc).date()
    summary = client.get(
        "/v1/dashboards/tickets/summary",
        params={"start": (now - timedelta(days=1)).isoformat(),
                "end": (now + timedelta(days=1)).isoformat()},
        headers={**headers(tenant_a, user_a), "X-Role": "SUPERVISOR"},
    )
    assert summary.status_code == 200
    assert summary.json()["status_counts"]["IN_PROGRESS"] == 1
    assert summary.json()["status_counts"]["OPEN"] == 0
    assert summary.headers["cache-control"] == "private, no-store"

    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ticket_events")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM outbox_events")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 2
    owner.dispose()


def test_concurrent_retries_create_exactly_one_ticket_and_outbox(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    tenant_a, _, user_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")

    headers = {
        "X-Tenant-ID": str(tenant_a), "X-Actor-ID": str(user_a),
        "X-Role": "SUPPORT_AGENT", "Idempotency-Key": "concurrent-retry-0001",
    }
    payload = {
        "customer_id": str(customer_a), "subject": "Racing requests",
        "body": "Same intent must be persisted once", "priority": "HIGH",
    }

    def submit(_):
        with TestClient(app) as client:
            response = client.post("/v1/tickets", headers=headers, json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))

    assert all(status == 201 for status, _ in results)
    assert len({body["id"] for _, body in results}) == 1
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        for table in ("tickets", "ticket_messages", "ticket_events",
                      "outbox_events", "audit_events"):
            actual = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert actual == 1, (table, actual)
    owner.dispose()
