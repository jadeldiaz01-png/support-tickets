"""CI-only read-only role/FK inventory. Not a production certification."""
from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url


def main():
    owner = os.environ.get("DATABASE_URL_OWNER", "")
    runtime = os.environ.get("DATABASE_URL", "")
    if not owner or not runtime:
        raise RuntimeError("G5_INVENTORY_DB_NOT_CONFIGURED")
    owner_url, runtime_url = make_url(owner), make_url(runtime)
    if not (
        os.environ.get("SUPPORT_ENV") == "test"
        and os.environ.get("G5_ISOLATED_CI_REHEARSAL") == "1"
        and owner_url.host in ("localhost", "127.0.0.1")
        and runtime_url.host in ("localhost", "127.0.0.1")
        and owner_url.database == runtime_url.database == "support"
        and owner_url.username == "postgres"
        and runtime_url.username == "support_runtime"
    ):
        raise RuntimeError("G5_INVENTORY_NON_DISPOSABLE_ABORT")

    ro = create_engine(owner_url, future=True)
    rt = create_engine(runtime_url, future=True)
    try:
        with rt.connect() as c:
            role = c.execute(text("SELECT current_user")).scalar_one()
            privileges = c.execute(text("""
                SELECT has_table_privilege(current_user, 'public.audit_events', 'SELECT'),
                       has_table_privilege(current_user, 'public.audit_events', 'INSERT'),
                       has_table_privilege(current_user, 'public.audit_events', 'UPDATE'),
                       has_table_privilege(current_user, 'public.audit_events', 'DELETE'),
                       has_table_privilege(current_user, 'public.audit_events', 'TRUNCATE'),
                       has_table_privilege(current_user, 'public.audit_events', 'TRIGGER'),
                       has_schema_privilege(current_user, 'public', 'CREATE')
            """)).one()
        cols = ("select", "insert", "update", "delete", "truncate", "trigger", "schema_create")
        flags = dict(zip(cols, list(privileges)))
        if flags != dict(zip(cols, (True, True, False, False, False, False, False))):
            raise AssertionError("G5_RUNTIME_AUDIT_PRIVILEGE_DRIFT")

        with ro.connect() as c:
            attrs = c.execute(text("""
                SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit
                FROM pg_roles WHERE rolname='support_runtime'
            """)).one()
            members = c.execute(text("""
                SELECT parent.rolname, membership.inherit_option, membership.set_option
                FROM pg_auth_members membership
                JOIN pg_roles member ON member.oid=membership.member
                JOIN pg_roles parent ON parent.oid=membership.roleid
                WHERE member.rolname='support_runtime' ORDER BY parent.rolname
            """)).all()
            fkrows = c.execute(text("""
                SELECT child.relname AS child_name,
                       parent.relname AS parent_name,
                       f.conname,
                       COALESCE(
                         (SELECT bool_or(a.attname='tenant_id')
                          FROM unnest(f.conkey) AS k(attnum)
                          JOIN pg_attribute a
                          ON a.attrelid=f.conrelid AND a.attnum=k.attnum),false
                       ) AS coupled,
                       f.convalidated
                FROM pg_constraint f
                JOIN pg_class child ON child.oid=f.conrelid
                JOIN pg_class parent ON parent.oid=f.confrelid
                WHERE f.contype='f'
                AND child.relnamespace='public'::regnamespace
                AND parent.relname <> 'tenants'
                AND EXISTS (SELECT 1 FROM pg_attribute a
                            WHERE a.attrelid=f.conrelid
                            AND a.attname='tenant_id' AND NOT a.attisdropped)
                ORDER BY child.relname,parent.relname,f.conname
            """)).mappings().all()
            version = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            audit_owner = c.execute(text("""
                SELECT pg_get_userbyid(relowner)
                FROM pg_class WHERE oid='public.audit_events'::regclass
            """)).scalar_one()
            trigger = c.execute(text("""
                SELECT tgname,tgenabled FROM pg_trigger
                WHERE tgrelid='public.audit_events'::regclass AND NOT tgisinternal
            """)).all()
        if version != "0005_tenant_audit_guard":
            raise AssertionError("G5_UNEXPECTED_SCHEMA_VERSION")
        if role != "support_runtime" or any(attrs) or members:
            raise AssertionError("G5_UNEXPECTED_RUNTIME_ROLE_OR_MEMBERSHIP")
        if not {("ticket_assignments", "users"),("ticket_assignments", "tickets")}.issubset(
            {(f["child_name"],f["parent_name"]) for f in fkrows if f["coupled"] and f["convalidated"]}
        ):
            raise AssertionError("G5_ASSIGNMENT_FK_UNVERIFIED")
        if ("audit_events_append_only_rows", "O") not in trigger:
            raise AssertionError("G5_AUDIT_TRIGGER_MISSING")

        uncoupled = sorted(
            f'{f["child_name"]}.{f["conname"]}->{f["parent_name"]}'
            for f in fkrows if not f["coupled"]
        )
        report = {
            "scope": "SYNTHETIC_DISPOSABLE_CI_ONLY",
            "schema_version": version,
            "audit_role": role,
            "audit_owner_role": audit_owner,
            "audit_effective_privileges": flags,
            "audit_role_memberships": [
                {"name": n, "inherit": i, "set": s} for n, i, s in members
            ],
            "tenant_fk_total": len(fkrows),
            "tenant_fk_uncoupled_count": len(uncoupled),
            "tenant_fk_uncoupled": uncoupled,
            "audit_trigger_rows": [
                {"name":n,"enabled":e} for n,e in trigger
            ],
            "known_residual_risk": "SCHEMA_OWNER_CAN_TRUNCATE_OR_ALTER",
        }
        print("G5_READONLY_SCHEMA_PRIVILEGE_EVIDENCE=" + json.dumps(report, sort_keys=True))
    finally:
        ro.dispose()
        rt.dispose()


if __name__ == "__main__":
    main()
