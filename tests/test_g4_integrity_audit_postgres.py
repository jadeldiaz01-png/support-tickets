"""Security G4: previously XFAIL tenant FK and audit mutation are PASS gates.

All database tests use disposable CI PostgreSQL. No production credentials,
production data, or external requests.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session

from api.main import app
from repositories.db import get_engine, bind_tenant
from tests.test_g3_audit_postgres import seed, test_env, make_ticket, headers, OWNER_URL

pytestmark = pytest.mark.skipif(
    not OWNER_URL, reason="Require disposable isolated PostgreSQL CI database"
)


def test_h01_direct_cross_tenant_ticket_assignment_is_rejected(monkeypatch):
    test_env(monkeypatch)
    ta, tb, ua, ub, _, customer_a = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer_a)
    # A tenant-B row points at tenant-A ticket (the old plain FK allowed it).
    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError):
            with session.begin():
                bind_tenant(session, tb)
                session.execute(text("""
                    INSERT INTO ticket_assignments
                    (id,tenant_id,ticket_id,user_id)
                    VALUES (:id,:tenant,:ticket,:user)
                """), {"id":uuid4(),"tenant":tb,"ticket":tid,"user":ub})
    owner = create_engine(OWNER_URL,future=True)
    with owner.connect() as con:
        assert con.execute(text("SELECT count(*) FROM ticket_assignments")).scalar_one() == 0
    owner.dispose()


def test_h02_existing_assignment_cannot_rebind_to_foreign_user(monkeypatch):
    test_env(monkeypatch)
    ta, tb, ua, ub, _, customer_a = seed()
    client = TestClient(app)
    tid = make_ticket(client, ta, ua, customer_a)
    assigned = client.patch(
        f"/v1/tickets/{tid}/assignment",
        headers=headers(ta,ua,"SUPERVISOR"),
        json={"assignee_user_id":str(ua),"expected_version":1},
    )
    assert assigned.status_code == 200
    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError):
            with session.begin():
                bind_tenant(session,ta)
                session.execute(text("""
                    UPDATE ticket_assignments SET user_id=:foreign
                    WHERE tenant_id=:tenant AND ticket_id=:ticket
                """), {"foreign":ub,"tenant":ta,"ticket":tid})
    owner=create_engine(OWNER_URL,future=True)
    with owner.connect() as con:
        original=con.execute(text("""
            SELECT user_id FROM ticket_assignments WHERE ticket_id=:tid
        """),{"tid":tid}).scalar_one()
    owner.dispose()
    assert original == ua


def test_h05_runtime_audit_can_append_but_cannot_update_delete_truncate(monkeypatch):
    test_env(monkeypatch)
    ta, _, ua, _, _, customer_a = seed()
    created=TestClient(app).post(
        "/v1/tickets",
        headers={**headers(ta,ua),"Idempotency-Key":"g4-audit-append-only"},
        json={"customer_id":str(customer_a),"subject":"Sample","body":"No outbound"},
    )
    assert created.status_code == 201
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, ta)
            row=session.execute(text("""
                SELECT id FROM audit_events WHERE tenant_id=:tenant
            """),{"tenant":ta}).scalar_one()
            can_insert=session.execute(text("""
                SELECT has_table_privilege(current_user,
                    'audit_events','INSERT')
            """)).scalar_one()
            can_update=session.execute(text("""
                SELECT has_table_privilege(current_user,
                    'audit_events','UPDATE')
            """)).scalar_one()
            can_delete=session.execute(text("""
                SELECT has_table_privilege(current_user,
                    'audit_events','DELETE')
            """)).scalar_one()
            can_truncate=session.execute(text("""
                SELECT has_table_privilege(current_user,
                    'audit_events','TRUNCATE')
            """)).scalar_one()
    assert can_insert is True
    assert can_update is False
    assert can_delete is False
    assert can_truncate is False
    for forbidden_sql in (
        "UPDATE audit_events SET action='altered' WHERE id=:id",
        "DELETE FROM audit_events WHERE id=:id",
    ):
        with Session(get_engine()) as session:
            with pytest.raises(SQLAlchemyError):
                with session.begin():
                    bind_tenant(session, ta)
                    session.execute(text(forbidden_sql),{"id":row})
    owner=create_engine(OWNER_URL,future=True)
    with owner.connect() as con:
        assert con.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1
    owner.dispose()


def test_h05_owner_dml_cannot_silently_mutate_audit_rows(monkeypatch):
    test_env(monkeypatch)
    ta, _, ua, _, _, customer_a = seed()
    tid=make_ticket(TestClient(app),ta,ua,customer_a)
    owner=create_engine(OWNER_URL,future=True)
    for statement in (
        "UPDATE audit_events SET action='tampered'",
        "DELETE FROM audit_events",
    ):
        with pytest.raises(SQLAlchemyError):
            with owner.begin() as con:
                con.execute(text(statement))
    with owner.connect() as con:
        assert con.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1
    owner.dispose()


def test_h01_h02_composite_constraints_present_and_validated():
    owner=create_engine(OWNER_URL,future=True)
    with owner.connect() as con:
        rows=con.execute(text("""
            SELECT conname, convalidated
            FROM pg_constraint WHERE conrelid='ticket_assignments'::regclass
              AND conname IN ('fk_assignments_tenant_user',
                              'fk_assignments_tenant_ticket')
        """)).all()
    owner.dispose()
    assert {name for name, _ in rows} == {
        "fk_assignments_tenant_user", "fk_assignments_tenant_ticket",
    }
    assert all(valid for _,valid in rows)
