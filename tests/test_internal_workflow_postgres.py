"""PostgreSQL-backed multi-tenant workflow checks (requires isolated CI DB)."""
from __future__ import annotations

import os
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from api.main import app
from uuid import UUID
from sqlalchemy import text

OWNER_URL = os.environ.get("DATABASE_URL_OWNER")

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



pytestmark = pytest.mark.skipif(not OWNER_URL, reason="PostgreSQL test DB required")


def _headers(tenant, actor, role="SUPERVISOR"):
    return {
        "X-Tenant-ID": str(tenant), "X-Actor-ID": str(actor), "X-Role": role
    }


def _make_ticket(client, tenant, agent, customer):
    result = client.post(
        "/v1/tickets",
        headers={**_headers(tenant, agent, "SUPPORT_AGENT"),
                 "Idempotency-Key": "internal-workflow-fixture-a1"},
        json={"customer_id": str(customer), "subject": "A", "body": "Private body"},
    )
    assert result.status_code == 201
    return result.json()["id"]


def test_tenant_safe_assignment_and_internal_note_with_version(monkeypatch):
    tenant_a, tenant_b, agent_a, agent_b, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)
    ticket_id = _make_ticket(client, tenant_a, agent_a, customer_a)
    url = f"/v1/tickets/{ticket_id}"
    foreign = client.patch(
        url + "/assignment", headers=_headers(tenant_b, agent_b),
        json={"assignee_user_id": str(agent_b), "expected_version": 1},
    )
    invalid_assignee = client.patch(
        url + "/assignment", headers=_headers(tenant_a, agent_a),
        json={"assignee_user_id": str(agent_b), "expected_version": 1},
    )
    assert foreign.status_code == 404
    assert invalid_assignee.status_code == 404
    assert invalid_assignee.json()["detail"] == "ASSIGNEE_NOT_FOUND"

    assigned = client.patch(
        url + "/assignment", headers=_headers(tenant_a, agent_a),
        json={"assignee_user_id": str(agent_a), "expected_version": 1},
    )
    assert assigned.status_code == 200
    assert assigned.json()["version"] == 2
    assert assigned.json()["assignee_user_id"] == str(agent_a)
    assert assigned.headers["cache-control"] == "private, no-store"

    stale = client.patch(
        url + "/assignment", headers=_headers(tenant_a, agent_a),
        json={"assignee_user_id": None, "expected_version": 1},
    )
    assert stale.status_code == 409
    unassign = client.patch(
        url + "/assignment", headers=_headers(tenant_a, agent_a),
        json={"assignee_user_id": None, "expected_version": 2},
    )
    assert unassign.status_code == 200
    assert unassign.json()["version"] == 3

    foreign_note = client.post(
        url + "/internal-notes", headers=_headers(tenant_b, agent_b, "SUPPORT_AGENT"),
        json={"body": "Unauthorized", "expected_version": 3},
    )
    assert foreign_note.status_code == 404
    note = client.post(
        url + "/internal-notes", headers=_headers(tenant_a, agent_a, "SUPPORT_AGENT"),
        json={"body": "Highly confidential internal note", "expected_version": 3},
    )
    assert note.status_code == 201
    assert note.json()["version"] == 4
    assert "confidential" not in str(note.json()).lower()
    assert note.headers["cache-control"] == "private, no-store"

    note_repeat = client.post(
        url + "/internal-notes", headers=_headers(tenant_a, agent_a, "SUPPORT_AGENT"),
        json={"body": "Highly confidential internal note", "expected_version": 3},
    )
    assert note_repeat.status_code == 409
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as con:
        assert con.execute(text(
            "SELECT count(*) FROM ticket_assignments WHERE released_at IS NULL"
        )).scalar_one() == 0
        assert con.execute(text(
            "SELECT count(*) FROM ticket_messages"
        )).scalar_one() == 2
        assert con.execute(text(
            "SELECT count(*) FROM ticket_events"
        )).scalar_one() == 4
        assert con.execute(text(
            "SELECT count(*) FROM audit_events"
        )).scalar_one() == 4
        # Assignment + note do not enqueue messages to external delivery.
        assert con.execute(text(
            "SELECT count(*) FROM outbox_events"
        )).scalar_one() == 1
        events = con.execute(text(
            "SELECT payload::text FROM ticket_events"
        )).scalars().all()
        assert all("Highly confidential" not in e for e in events)
    owner.dispose()


def test_reject_customer_role_for_assignment_and_closed_tickets(monkeypatch):
    tenant_a, _, agent_a, _, customer_a = seed()
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    client = TestClient(app)
    ticket_id = _make_ticket(client, tenant_a, agent_a, customer_a)
    url = f"/v1/tickets/{ticket_id}"
    owner = create_engine(OWNER_URL, future=True)
    customer_user = uuid4()
    with owner.begin() as con:
        con.execute(text("""
            INSERT INTO users(id, tenant_id, external_subject, role)
            VALUES (:id, :tenant, 'test-customer', 'CUSTOMER')
        """), {"id": customer_user, "tenant": tenant_a})
    owner.dispose()
    bad = client.patch(
        url + "/assignment", headers=_headers(tenant_a, agent_a),
        json={"assignee_user_id": str(customer_user), "expected_version": 1},
    )
    assert bad.status_code == 404
    denied = client.patch(
        url + "/assignment", headers=_headers(tenant_a, customer_user, "CUSTOMER"),
        json={"assignee_user_id": str(agent_a), "expected_version": 1},
    )
    assert denied.status_code == 403
