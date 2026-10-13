"""PostgreSQL-only adversarial evidence for flotaopd-del H-01..H-08.

Must run exclusively against an isolated disposable CI database. Never point
DATABASE_URL_OWNER or DATABASE_URL at any production environment.
Previously identified H-01/H-02 and H-05 XFAILs are now strict PASS expectations.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from api.main import app
from repositories.db import bind_tenant, get_engine

OWNER_URL = os.environ.get("DATABASE_URL_OWNER")
pytestmark = pytest.mark.skipif(
    not OWNER_URL, reason="Requires isolated PostgreSQL CI database"
)


def seed():
    """The same small two-tenant fixture as the existing G3 suite."""
    owner = create_engine(OWNER_URL, future=True)
    tenant_a, tenant_b = uuid4(), uuid4()
    user_a, user_b, secondary_a, customer_a = uuid4(), uuid4(), uuid4(), uuid4()
    with owner.begin() as con:
        con.execute(text("""
            TRUNCATE TABLE reconciliation_records, outbox_events, tool_intents,
                approval_requests, ticket_sla_state, ticket_tags,
                ticket_assignments, ticket_events, ticket_messages,
                audit_events, knowledge_sources, tickets, customers,
                users, tenants CASCADE
        """))
        con.execute(text("""
            INSERT INTO tenants(id, slug)
            VALUES (:ta, 'audit-tenant-a'), (:tb, 'audit-tenant-b')
        """), {"ta": tenant_a, "tb": tenant_b})
        con.execute(text("""
            INSERT INTO users(id, tenant_id, external_subject, role)
            VALUES (:ua,:ta,'audit-user-a','SUPPORT_AGENT'),
                   (:ub,:tb,'audit-user-b','SUPPORT_AGENT'),
                   (:sa,:ta,'audit-secondary-a','SUPPORT_AGENT')
        """), {"ua": user_a, "ub": user_b, "sa": secondary_a,
               "ta": tenant_a, "tb": tenant_b})
        con.execute(text("""
            INSERT INTO customers(id,tenant_id,external_ref,display_name)
            VALUES (:id,:ta,'customer-a','Audit fixture')
        """), {"id": customer_a, "ta": tenant_a})
    owner.dispose()
    return tenant_a, tenant_b, user_a, user_b, secondary_a, customer_a


def test_env(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")


def headers(tenant, user, role="SUPPORT_AGENT"):
    return {"X-Tenant-ID": str(tenant), "X-Actor-ID": str(user),
            "X-Role": role}


def make_ticket(client, tenant, user, customer):
    created = client.post(
        "/v1/tickets",
        headers={**headers(tenant, user), "Idempotency-Key": "audit-h1234-new"},
        json={"subject": "Audit ticket", "body": "Internal fixture",
              "customer_id": str(customer)},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_h01_h02_rls_foreign_reads_and_assignment_denial(monkeypatch):
    test_env(monkeypatch)
    ta, tb, ua, ub, _, customer = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer)
    assigned = client.patch(
        f"/v1/tickets/{tid}/assignment",
        headers=headers(ta, ua, "SUPERVISOR"),
        json={"assignee_user_id": str(ua), "expected_version": 1},
    )
    assert assigned.status_code == 200

    foreign_read = client.get(f"/v1/tickets/{tid}", headers=headers(tb, ub))
    foreign_write = client.patch(
        f"/v1/tickets/{tid}/assignment", headers=headers(tb, ub, "SUPERVISOR"),
        json={"assignee_user_id": str(ub), "expected_version": 2},
    )
    guessed_user = client.patch(
        f"/v1/tickets/{tid}/assignment", headers=headers(ta, ua, "SUPERVISOR"),
        json={"assignee_user_id": str(ub), "expected_version": 2},
    )
    assert foreign_read.status_code == 404
    assert foreign_write.status_code == 404
    assert guessed_user.status_code == 404

    # Independent RLS evidence: tenant B cannot read A's assignment or note.
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, tb)
            count = session.execute(text("""
                SELECT count(*) FROM ticket_assignments
                WHERE ticket_id = :tid
            """), {"tid": tid}).scalar_one()
    assert count == 0


def test_h04_concurrent_assignment_exactly_one_winner(monkeypatch):
    test_env(monkeypatch)
    ta, _, ua, _, second_a, customer = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer)
    endpoint = f"/v1/tickets/{tid}/assignment"

    def submit(i):
        with TestClient(app) as independent:
            return independent.patch(
                endpoint, headers=headers(ta, ua, "SUPERVISOR"),
                json={"assignee_user_id": str(ua if i % 2 else second_a),
                      "expected_version": 1},
            ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(submit, range(4)))
    assert codes.count(200) == 1, codes
    assert codes.count(409) == 3, codes
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as con:
        version = con.execute(text(
            "SELECT version FROM tickets WHERE id = :id"
        ), {"id": tid}).scalar_one()
        assert version == 2
        active = con.execute(text("""
            SELECT count(*) FROM ticket_assignments
            WHERE ticket_id = :id AND released_at IS NULL
        """), {"id": tid}).scalar_one()
        assert active == 1
        assert con.execute(text(
            "SELECT count(*) FROM ticket_events"
        )).scalar_one() == 2
    owner.dispose()


def test_h03_h05_h08_private_note_and_failure_no_exfiltration(monkeypatch):
    test_env(monkeypatch)
    ta, tb, ua, ub, _, customer = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer)
    marker = "G3-UNIQUE-PRIVATE-NOTE-NEVER-EXPOSE"
    endpoint = f"/v1/tickets/{tid}/internal-notes"
    ok = client.post(
        endpoint, headers=headers(ta, ua),
        json={"body": marker, "expected_version": 1},
    )
    stale = client.post(
        endpoint, headers=headers(ta, ua),
        json={"body": marker, "expected_version": 1},
    )
    cross = client.post(
        endpoint, headers=headers(tb, ub),
        json={"body": marker, "expected_version": 2},
    )
    assert ok.status_code == 201
    assert stale.status_code == 409
    assert cross.status_code == 404
    assert all(marker not in r.text for r in (ok, stale, cross))

    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as con:
        assert con.execute(text(
            "SELECT count(*) FROM ticket_messages WHERE body = :body"
        ), {"body": marker}).scalar_one() == 1
        event_data = con.execute(text(
            "SELECT payload::text FROM ticket_events"
        )).scalars().all()
        audit_data = con.execute(text(
            "SELECT data::text FROM audit_events"
        )).scalars().all()
        assert all(marker not in datum for datum in event_data + audit_data)
        audit_actor = con.execute(text("""
            SELECT count(*) FROM audit_events
            WHERE actor_id = :user AND tenant_id = :tenant
              AND action = 'ticket:internal_note'
        """), {"user": ua, "tenant": ta}).scalar_one()
        assert audit_actor == 1
        # Only creation has an outbox event. Notes never call an external adapter.
        assert con.execute(text(
            "SELECT count(*) FROM outbox_events"
        )).scalar_one() == 1
    owner.dispose()


def test_h05_audit_history_must_reject_runtime_delete(monkeypatch):
    test_env(monkeypatch)
    ta, _, ua, _, _, customer = seed()
    client = TestClient(app)
    make_ticket(client, ta, ua, customer)
    # Must fail because the runtime role has neither DELETE privilege nor mutation authority.
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, ta)
            with pytest.raises(SQLAlchemyError):
                session.execute(text("""
                    DELETE FROM audit_events WHERE tenant_id = :tenant
                """), {"tenant": ta})


def test_h01_direct_fk_must_reject_foreign_tenant_assignee(monkeypatch):
    test_env(monkeypatch)
    ta, _, ua, ub, _, customer = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer)
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, ta)
            # Route validation rejects this; DB-only writes may still allow it.
            with pytest.raises(SQLAlchemyError):
                session.execute(text("""
                    INSERT INTO ticket_assignments (id, tenant_id, ticket_id, user_id)
                    VALUES (:id, :tenant, :ticket, :foreign_user)
                """), {"id": uuid4(), "tenant": ta,
                       "ticket": tid, "foreign_user": ub})


def test_h06_duplicate_preexisting_assignments_block_unique_migration():
    """Synthetic duplicate fixture; not a claim about real production rows."""
    owner = create_engine(OWNER_URL, future=True)
    with owner.begin() as con:
        con.execute(text("""
            CREATE TEMP TABLE g3_migration_fixture
            (tenant_id uuid, ticket_id uuid, released_at timestamptz)
            ON COMMIT DROP
        """))
        ta, tid = uuid4(), uuid4()
        con.execute(text("""
            INSERT INTO g3_migration_fixture(tenant_id,ticket_id,released_at)
            VALUES (:ta,:tid,NULL),(:ta,:tid,NULL)
        """), {"ta": ta, "tid": tid})
        with pytest.raises(IntegrityError):
            with con.begin_nested():
                con.execute(text("""
                    CREATE UNIQUE INDEX g3_unique_index_preflight
                    ON g3_migration_fixture(tenant_id,ticket_id)
                    WHERE released_at IS NULL
                """))
    owner.dispose()
