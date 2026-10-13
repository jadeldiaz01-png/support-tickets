"""G5 disposable PostgreSQL 16 Alembic migration failure/recovery rehearsal.

Synthetic data only; never connects to public services or production databases.
Runs in a new GitHub Actions PostgreSQL service after unit/integration tests.
"""
from __future__ import annotations

import os
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

REV_PRE = "0004_active_assignment_index"
REV_NEW = "0005_tenant_audit_guard"


def assert_disposable() -> str:
    url = os.environ.get("DATABASE_URL_OWNER", "")
    if not url:
        raise RuntimeError("G5_NO_DATABASE_URL")
    parsed = make_url(url)
    safe = (
        os.environ.get("SUPPORT_ENV") == "test"
        and os.environ.get("G5_ISOLATED_CI_REHEARSAL") == "1"
        and parsed.host in {"127.0.0.1", "localhost"}
        and parsed.database == "support"
        and parsed.username == "postgres"
    )
    if not safe:
        raise RuntimeError("G5_NOT_DISPOSABLE_DATABASE_ABORT")
    os.environ["PGOPTIONS"] = "-c lock_timeout=5000 -c statement_timeout=30000"
    return url


def version(conn):
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def migrate(config, revision):
    start = time.perf_counter()
    command.downgrade(config, revision) if revision == REV_PRE else command.upgrade(config, revision)
    elapsed = time.perf_counter() - start
    print(f"G5_MIGRATE_TARGET={revision} SECONDS={elapsed:.3f}", flush=True)


def main():
    url = assert_disposable()
    cfg = Config("alembic.ini")
    engine = create_engine(url, future=True)
    ta, tb = uuid4(), uuid4()
    ua, ub, ticket_id, invalid_id, good_id = (uuid4() for _ in range(5))
    try:
        with engine.connect() as c:
            assert version(c) == REV_NEW
        migrate(cfg, REV_PRE)
        with engine.begin() as c:
            assert version(c) == REV_PRE
            c.execute(
                text("INSERT INTO tenants(id,slug) VALUES (:ta,:sa),(:tb,:sb)"),
                {"ta": ta, "tb": tb,
                 "sa": "g5-migration-a-" + ta.hex, "sb": "g5-migration-b-" + tb.hex},
            )
            c.execute(text("""
                INSERT INTO users(id,tenant_id,external_subject,role)
                VALUES (:ua,:ta,'g5-agent-a','SUPPORT_AGENT'),
                       (:ub,:tb,'g5-agent-b','SUPPORT_AGENT')
            """), {"ua":ua,"ub":ub,"ta":ta,"tb":tb})
            c.execute(text("""
                INSERT INTO tickets(id,tenant_id,idempotency_key,subject)
                VALUES (:ticket,:ta,'g5-restore-fixture','G5 synthetic ticket')
            """), {"ticket":ticket_id,"ta":ta})
            # Deliberately accepted by 0004 because its plain user_id FK
            # does not verify tenant. 0005 must fail closed with this row.
            c.execute(text("""
                INSERT INTO ticket_assignments(id,tenant_id,ticket_id,user_id)
                VALUES (:id,:ta,:ticket,:foreign_user)
            """), {"id":invalid_id,"ta":ta,"ticket":ticket_id,"foreign_user":ub})

        failure = None
        try:
            migrate(cfg, REV_NEW)
        except Exception as exc:
            failure = str(exc)
        if not failure or "H01_H02_EXISTING_FOREIGN_TENANT_ASSIGNMENT_USER" not in failure:
            raise AssertionError("G5_MISMATCHED_PREEXISTING_DATA_NOT_REJECTED")

        with engine.connect() as c:
            assert version(c) == REV_PRE
            preserved = c.execute(text("""
                SELECT count(*) FROM ticket_assignments
                WHERE id=:id AND tenant_id=:ta AND user_id=:ub
            """), {"id":invalid_id,"ta":ta,"ub":ub}).scalar_one()
            assert preserved == 1
            absent = c.execute(text("""
                SELECT count(*) FROM pg_constraint WHERE
                    conname='fk_assignments_tenant_user'
            """)).scalar_one()
            assert absent == 0
        print("G5_INCOMPATIBLE_RESTORE_ABORT_ATOMIC=PASS",flush=True)

        with engine.begin() as c:
            c.execute(
                text("DELETE FROM ticket_assignments WHERE id=:id"),
                {"id":invalid_id},
            )
            c.execute(text("""
                INSERT INTO ticket_assignments(id,tenant_id,ticket_id,user_id)
                VALUES (:id,:ta,:ticket,:same_tenant_user)
            """), {"id":good_id,"ta":ta,"ticket":ticket_id,"same_tenant_user":ua})
        migrate(cfg, REV_NEW)
        with engine.connect() as c:
            assert version(c) == REV_NEW
            checked = c.execute(text("""
                SELECT count(*) FROM pg_constraint
                WHERE conname IN (
                    'fk_assignments_tenant_user',
                    'fk_assignments_tenant_ticket'
                ) AND convalidated
            """)).scalar_one()
            assert checked == 2
            assert c.execute(text("""
                SELECT count(*) FROM ticket_assignments WHERE id=:id
            """), {"id":good_id}).scalar_one() == 1
        print("G5_VALID_PREEXISTING_DATA_UPGRADE=PASS",flush=True)

        migrate(cfg, REV_PRE)
        with engine.connect() as c:
            assert version(c) == REV_PRE
            assert c.execute(text(
                "SELECT count(*) FROM ticket_assignments WHERE id=:id"
            ), {"id":good_id}).scalar_one() == 1
        print("G5_DOWNGRADE_PRESERVED_FIXTURE=PASS",flush=True)
        migrate(cfg, REV_NEW)
        with engine.connect() as c:
            assert version(c) == REV_NEW
            assert c.execute(text(
                "SELECT count(*) FROM ticket_assignments WHERE id=:id"
            ), {"id":good_id}).scalar_one() == 1
        print("G5_REUPGRADE_PRESERVED_FIXTURE=PASS",flush=True)

        # Only delete synthetic records created by this script; no TRUNCATE.
        with engine.begin() as c:
            c.execute(text(
                "DELETE FROM ticket_assignments WHERE id=:id"
            ), {"id":good_id})
            c.execute(text("DELETE FROM tickets WHERE id=:id"), {"id":ticket_id})
            c.execute(text("DELETE FROM users WHERE id IN (:ua,:ub)"),
                      {"ua":ua,"ub":ub})
            c.execute(text("DELETE FROM tenants WHERE id IN (:ta,:tb)"),
                      {"ta":ta,"tb":tb})
        print("G5_SYNTHETIC_REHEARSAL=PASS NO_PRODUCTION_DATA=TRUE",flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
