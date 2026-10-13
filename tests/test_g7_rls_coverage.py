"""G7: fail-closed tenant RLS regression controls on disposable PostgreSQL.

Never run this file against a persistent or production database.
The fixture uses owner-level TRUNCATE and writes synthetic tenant records.
CI provisions an isolated PostgreSQL 16 service and least-privilege runtime.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from repositories.db import bind_tenant, get_engine

OWNER_URL = os.environ.get("DATABASE_URL_OWNER")
RUNTIME_URL = os.environ.get("DATABASE_URL")

TENANT_TABLES = (
    "users", "customers", "tickets", "ticket_messages", "ticket_events",
    "ticket_assignments", "ticket_tags", "ticket_sla_state",
    "approval_requests", "tool_intents", "outbox_events",
    "reconciliation_records", "audit_events", "knowledge_sources",
)
ISOLATED_SCOPE = ("tenants",) + TENANT_TABLES

pytestmark = pytest.mark.skipif(
    not (OWNER_URL and RUNTIME_URL and os.environ.get("SUPPORT_ENV") == "test"),
    reason="G7 only runs with a dedicated disposable PostgreSQL CI environment",
)


def _assert_ci_database_shape():
    from sqlalchemy.engine.url import make_url

    admin = make_url(OWNER_URL)
    runtime = make_url(RUNTIME_URL)
    assert admin.host in {"127.0.0.1", "localhost"}
    assert runtime.host in {"127.0.0.1", "localhost"}
    assert admin.database == runtime.database == "support"
    assert admin.username == "postgres"
    assert runtime.username == "support_runtime"


@pytest.fixture
def seeded_tenants():
    """Two rows in EVERY tenant-scoped table, with only coherent references."""
    _assert_ci_database_shape()
    ids = {key: uuid4() for key in (
        "tenant_a", "tenant_b", "user_a", "user_b", "customer_a", "customer_b",
        "ticket_a", "ticket_b", "message_a", "message_b", "event_a", "event_b",
        "assignment_a", "assignment_b", "tag_a", "tag_b", "sla_a", "sla_b",
        "approval_a", "approval_b", "intent_a", "intent_b",
        "outbox_a", "outbox_b", "reconcile_a", "reconcile_b",
        "audit_a", "audit_b", "knowledge_a", "knowledge_b",
    )}
    owner = create_engine(OWNER_URL, future=True)
    with owner.begin() as conn:
        conn.execute(text("""
            TRUNCATE TABLE reconciliation_records, outbox_events, tool_intents,
              approval_requests, ticket_sla_state, ticket_tags, ticket_assignments,
              ticket_events, ticket_messages, audit_events, knowledge_sources,
              tickets, customers, users, tenants CASCADE
        """))
        for label in ("a", "b"):
            tenant = ids["tenant_" + label]
            user = ids["user_" + label]
            customer = ids["customer_" + label]
            ticket = ids["ticket_" + label]
            intent = ids["intent_" + label]
            params = {"tenant": tenant, "user": user, "customer": customer,
                      "ticket": ticket, "intent": intent,
                      "marker": label, **ids}
            conn.execute(text("""
                INSERT INTO tenants(id,slug) VALUES
                (:tenant,:marker)
            """), {"tenant": tenant, "marker": "g7-tenant-" + label})
            conn.execute(text("""
                INSERT INTO users(id,tenant_id,external_subject,role)
                VALUES (:user,:tenant,:subject,'SUPPORT_AGENT')
            """), {**params, "subject": "g7-agent-" + label})
            conn.execute(text("""
                INSERT INTO customers(id,tenant_id,external_ref)
                VALUES (:customer,:tenant,:ref)
            """), {**params, "ref": "g7-customer-" + label})
            conn.execute(text("""
                INSERT INTO tickets(id,tenant_id,customer_id,idempotency_key,subject)
                VALUES (:ticket,:tenant,:customer,:key,'G7 synthetic')
            """), {**params, "key": "g7-ticket-" + label})
            conn.execute(text("""
                INSERT INTO ticket_messages
                  (id,tenant_id,ticket_id,author_user_id,author_type,body)
                VALUES (:id,:tenant,:ticket,:user,'HUMAN_AGENT','G7 synthetic')
            """), {**params, "id": ids["message_" + label]})
            conn.execute(text("""
                INSERT INTO ticket_events
                  (id,tenant_id,ticket_id,event_type)
                VALUES (:id,:tenant,:ticket,'G7_OFFLINE')
            """), {**params, "id": ids["event_" + label]})
            conn.execute(text("""
                INSERT INTO ticket_assignments
                  (id,tenant_id,ticket_id,user_id)
                VALUES (:id,:tenant,:ticket,:user)
            """), {**params, "id": ids["assignment_" + label]})
            conn.execute(text("""
                INSERT INTO ticket_tags(id,tenant_id,ticket_id,tag)
                VALUES (:id,:tenant,:ticket,'g7')
            """), {**params, "id": ids["tag_" + label]})
            conn.execute(text("""
                INSERT INTO ticket_sla_state(ticket_id,tenant_id)
                VALUES (:ticket,:tenant)
            """), params)
            conn.execute(text("""
                INSERT INTO approval_requests
                  (id,tenant_id,ticket_id,action,requested_by)
                VALUES (:id,:tenant,:ticket,'G7_OFFLINE',:user)
            """), {**params, "id": ids["approval_" + label]})
            conn.execute(text("""
                INSERT INTO tool_intents
                  (id,tenant_id,ticket_id,tool_name,idempotency_key)
                VALUES (:intent,:tenant,:ticket,'g7-offline',:key)
            """), {**params, "key": "g7-intent-" + label})
            conn.execute(text("""
                INSERT INTO outbox_events
                  (id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
                VALUES (:id,:tenant,'ticket',:ticket,'g7.offline','{}'::jsonb)
            """), {**params, "id": ids["outbox_" + label]})
            conn.execute(text("""
                INSERT INTO reconciliation_records
                  (id,tenant_id,intent_id,state)
                VALUES (:id,:tenant,:intent,'UNKNOWN')
            """), {**params, "id": ids["reconcile_" + label]})
            conn.execute(text("""
                INSERT INTO audit_events
                  (id,tenant_id,actor_id,action,resource_type,resource_id)
                VALUES (:id,:tenant,:user,'g7:offline','ticket',:ticket)
            """), {**params, "id": ids["audit_" + label]})
            conn.execute(text("""
                INSERT INTO knowledge_sources
                  (id,tenant_id,source_ref,revision)
                VALUES (:id,:tenant,:ref,'g7')
            """), {**params, "id": ids["knowledge_" + label],
                   "ref": "g7-source-" + label})
    owner.dispose()
    return ids


def test_g7_every_tenant_table_rls_is_enabled_forced_and_fail_closed():
    _assert_ci_database_shape()
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        catalog = conn.execute(text("""
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relnamespace='public'::regnamespace
              AND relkind='r'
        """)).mappings().all()
        policies = conn.execute(text("""
            SELECT tablename, policyname, cmd, qual, with_check
            FROM pg_policies WHERE schemaname='public'
        """)).mappings().all()
    owner.dispose()
    found = {r["relname"]: r for r in catalog}
    scoped = set(ISOLATED_SCOPE)
    assert scoped <= set(found), "missing tenant table"
    for table in ISOLATED_SCOPE:
        assert found[table]["relrowsecurity"] is True, table
        assert found[table]["relforcerowsecurity"] is True, table
        scoped_policies = [p for p in policies if p["tablename"] == table]
        assert len(scoped_policies) == 1, table
        p = scoped_policies[0]
        assert p["policyname"] == "tenant_isolation", table
        assert p["cmd"] == "ALL", table
        expected_field = "id" if table == "tenants" else "tenant_id"
        for expr in (p["qual"], p["with_check"]):
            assert expr is not None and "app.tenant_id" in expr, table
            assert expected_field in expr, table


def test_g7_without_tenant_binding_sees_no_rows(seeded_tenants):
    with Session(get_engine()) as session:
        with session.begin():
            for table in ISOLATED_SCOPE:
                # Literal allowlisted table identifiers, not input.
                count = session.execute(
                    text(f"SELECT COUNT(*) FROM public.{table}")
                ).scalar_one()
                assert count == 0, table


@pytest.mark.parametrize("which", ("a", "b"))
def test_g7_each_tenant_sees_own_rows_not_other_tenant_rows(seeded_tenants, which):
    me = seeded_tenants["tenant_" + which]
    other = seeded_tenants["tenant_b" if which == "a" else "tenant_a"]
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, me)
            for table in TENANT_TABLES:
                own = session.execute(
                    text(f"SELECT COUNT(*) FROM public.{table} WHERE tenant_id=:tenant"),
                    {"tenant": me},
                ).scalar_one()
                foreign = session.execute(
                    text(f"SELECT COUNT(*) FROM public.{table} WHERE tenant_id=:tenant"),
                    {"tenant": other},
                ).scalar_one()
                assert own >= 1, (which, table)
                assert foreign == 0, (which, table)
            assert session.execute(text(
                "SELECT COUNT(*) FROM tenants WHERE id=:id"
            ), {"id": me}).scalar_one() == 1
            assert session.execute(text(
                "SELECT COUNT(*) FROM tenants WHERE id=:id"
            ), {"id": other}).scalar_one() == 0


def test_g7_binding_does_not_leak_across_transactions(seeded_tenants):
    with Session(get_engine()) as session:
        with session.begin():
            bind_tenant(session, seeded_tenants["tenant_a"])
            assert session.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        # The same Session starts a *new transaction* without SET LOCAL.
        with session.begin():
            assert session.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 0
            assert session.execute(text("SELECT COUNT(*) FROM tenants")).scalar_one() == 0


@pytest.mark.parametrize("statement", (
    "INSERT INTO knowledge_sources(id,tenant_id,source_ref,revision) "
    "VALUES (:id,:foreign,'g7-denied-insert','bad')",
    "UPDATE knowledge_sources SET tenant_id=:foreign WHERE id=:id",
))
def test_g7_cross_tenant_writes_are_denied_by_rls(seeded_tenants, statement):
    with Session(get_engine()) as session:
        with pytest.raises(SQLAlchemyError) as denied:
            with session.begin():
                bind_tenant(session, seeded_tenants["tenant_a"])
                session.execute(text(statement), {
                    "id": seeded_tenants["knowledge_a"] if statement.startswith("UPDATE")
                          else uuid4(),
                    "foreign": seeded_tenants["tenant_b"],
                })
    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        assert conn.execute(text("""
            SELECT COUNT(*) FROM knowledge_sources
            WHERE id=:id AND tenant_id=:tenant
        """), {
            "id": seeded_tenants["knowledge_a"],
            "tenant": seeded_tenants["tenant_a"],
        }).scalar_one() == 1
    owner.dispose()


def test_g7_polymorphic_ids_remain_a_documented_not_yet_enforced_risk():
    # These 3 generic ID columns have no type-specific composite FKs.
    # This test records an explicit gap: *absence* cannot be a security PASS.
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname AS tablename, a.attname AS columnname
            FROM pg_class c
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE c.relnamespace = 'public'::regnamespace
              AND (c.relname, a.attname) IN (
                  ('outbox_events','aggregate_id'),
                  ('audit_events','resource_id'),
                  ('audit_events','actor_id')
              ) AND NOT a.attisdropped
            ORDER BY c.relname, a.attname
        """)).all()
    owner.dispose()
    assert set(rows) == {
        ("outbox_events", "aggregate_id"),
        ("audit_events", "resource_id"),
        ("audit_events", "actor_id"),
    }
    # No claim of FK safety for these polymorphic/non-FK references.
