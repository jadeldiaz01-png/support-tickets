"""G5: verifiable role privileges and residual audit/schema limits.

Tests use ONLY disposable PostgreSQL from GitHub Actions or an approved isolated
local test database. This does not certify permissions in real infrastructure.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

OWNER_URL = os.environ.get("DATABASE_URL_OWNER")
RUNTIME_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not (OWNER_URL and RUNTIME_URL and os.environ.get("SUPPORT_ENV") == "test"),
    reason="Only run with disposable PostgreSQL test roles",
)


def test_g5_effective_runtime_role_without_inherited_privilege_escalation():
    # Query as the authenticated role, not information_schema grant rows alone:
    # has_table_privilege resolves privileges from role memberships and PUBLIC.
    with create_engine(RUNTIME_URL, future=True).connect() as c:
        current = c.execute(text("SELECT current_user")).scalar_one()
        assert current == "support_runtime"
        effective = c.execute(text("""
            SELECT
              has_table_privilege(current_user, 'public.audit_events', 'SELECT'),
              has_table_privilege(current_user, 'public.audit_events', 'INSERT'),
              has_table_privilege(current_user, 'public.audit_events', 'UPDATE'),
              has_table_privilege(current_user, 'public.audit_events', 'DELETE'),
              has_table_privilege(current_user, 'public.audit_events', 'TRUNCATE'),
              has_table_privilege(current_user, 'public.audit_events', 'TRIGGER'),
              has_schema_privilege(current_user, 'public', 'CREATE')
        """)).one()
    assert tuple(effective) == (True, True, False, False, False, False, False)

    with create_engine(OWNER_URL, future=True).connect() as c:
        role = c.execute(text("""
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit
              FROM pg_roles WHERE rolname = 'support_runtime'
        """)).one()
        # Any memberships require an explicit audit of effective privileges.
        memberships = c.execute(text("""
            SELECT COUNT(*)
            FROM pg_auth_members m
            JOIN pg_roles r ON r.oid = m.member
            WHERE r.rolname = 'support_runtime'
        """)).scalar_one()
    assert tuple(role) == (False, False, False, False, False)
    assert memberships == 0


def test_g5_inventory_all_tenant_child_foreign_keys(capsys):
    # This is discovery, not a blanket certification: e.g. user/ticket
    # references on other child tables may still lack tenant-coupled FKs.
    with create_engine(OWNER_URL, future=True).connect() as c:
        constraints = c.execute(text("""
            SELECT child.relname AS child_table,
                   parent.relname AS parent_table,
                   con.conname,
                   COALESCE(
                     (SELECT bool_or(att.attname = 'tenant_id')
                        FROM unnest(con.conkey) AS k(attnum)
                        JOIN pg_attribute att ON att.attrelid=con.conrelid
                           AND att.attnum=k.attnum), false) AS tenant_coupled,
                   con.convalidated
            FROM pg_constraint con
            JOIN pg_class child ON child.oid=con.conrelid
            JOIN pg_class parent ON parent.oid=con.confrelid
            WHERE con.contype='f'
              AND child.relnamespace='public'::regnamespace
              AND parent.relname <> 'tenants'
              AND EXISTS (
                  SELECT 1 FROM pg_attribute ca
                  WHERE ca.attrelid=con.conrelid AND ca.attname='tenant_id'
                    AND NOT ca.attisdropped
              )
            ORDER BY child.relname, parent.relname, con.conname
        """)).mappings().all()
    assert constraints
    protected = {
        (row["child_table"], row["parent_table"])
        for row in constraints
        if row["tenant_coupled"] and row["convalidated"]
    }
    assert ("ticket_assignments", "users") in protected
    assert ("ticket_assignments", "tickets") in protected
    uncoupled = [
        f'{row["child_table"]}->{row["parent_table"]}'
        for row in constraints if not row["tenant_coupled"]
    ]
    print(
        f"G5_TENANT_FK_INVENTORY total={len(constraints)} "
        f"tenant_coupled={len(constraints)-len(uncoupled)} "
        f"uncoupled={len(uncoupled)} names={','.join(uncoupled)}"
    )
    assert all(row["convalidated"] for row in constraints)


def test_g5_owner_truncate_bypasses_row_delete_trigger_in_rolled_back_txn():
    # Demonstrates a residual hazard explicitly; never labels storage WORM.
    tenant_id = uuid4()
    event_id = uuid4()
    engine = create_engine(OWNER_URL, future=True)
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO tenants(id,slug)
            VALUES (:id,:slug)
        """), {"id": tenant_id, "slug": "g5-owner-truncate-" + tenant_id.hex})
        c.execute(text("""
            INSERT INTO audit_events(id,tenant_id,action,resource_type)
            VALUES (:id,:tenant,'g5.canary','ticket')
        """), {"id": event_id, "tenant": tenant_id})
    with engine.connect() as c:
        txn = c.begin()
        try:
            before = c.execute(
                text("SELECT count(*) FROM audit_events WHERE id=:id"),
                {"id": event_id},
            ).scalar_one()
            assert before == 1
            c.execute(text("TRUNCATE TABLE audit_events"))
            after = c.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
            assert after == 0  # bypasses row triggers: demonstrable owner risk
            print("G5_OWNER_TRUNCATE_RESIDUAL_RISK=CONFIRMED_TEST_ONLY")
        finally:
            txn.rollback()  # explicit rollback, never persist the truncation
    with engine.begin() as c:
        still = c.execute(
            text("SELECT count(*) FROM audit_events WHERE id=:id"),
            {"id": event_id},
        ).scalar_one()
        assert still == 1
        # Can clean up the canary only after confirming rollback. A deletion
        # of the guarded audit_events row is not permitted; leave it until
        # the disposable CI database is destroyed.
    engine.dispose()
