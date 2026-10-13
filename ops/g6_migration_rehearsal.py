"""G6 foreign-tenant legacy-data migration guard: disposable CI only.

A historical approval_requests reference is valid under 0005's legacy plain
FK but invalid under 0006. A failed 0006 upgrade must be atomic and preserve
that record until a human-approved remediation.
"""
from __future__ import annotations

import os
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

OLD = "0005_tenant_audit_guard"
HEAD = "0006_tenant_fks"


def main():
    url = os.getenv("DATABASE_URL_OWNER", "")
    if not url:
        raise RuntimeError("G6_ISOLATED_OWNER_REQUIRED")
    u=make_url(url)
    if not (os.getenv("SUPPORT_ENV") == "test"
            and os.getenv("G6_DISPOSABLE_TEST_ONLY") == "YES"
            and u.host in ("localhost","127.0.0.1")
            and u.database == "support" and u.username == "postgres"):
        raise RuntimeError("G6_NON_DISPOSABLE_DATABASE_ABORT")
    # Localhost might be tunneled: caller must verify physical isolation.
    os.environ["PGOPTIONS"]="-c lock_timeout=5000 -c statement_timeout=30000"
    e=create_engine(url,future=True)
    cfg=Config("alembic.ini")
    ta,tb,ua,ub,approval=(uuid4() for _ in range(5))
    try:
        with e.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==HEAD
        start=time.monotonic()
        command.downgrade(cfg,OLD)
        with e.begin() as c:
            c.execute(text("INSERT INTO tenants(id,slug) VALUES (:a,:sa),(:b,:sb)"),
                      {"a":ta,"b":tb,"sa":"g6-test-"+ta.hex,"sb":"g6-test-"+tb.hex})
            c.execute(text("""
                INSERT INTO users(id,tenant_id,external_subject,role)
                VALUES (:a,:ta,'g6-rehearsal-a','SUPPORT_AGENT'),
                       (:b,:tb,'g6-rehearsal-b','SUPPORT_AGENT')
            """),{"a":ua,"b":ub,"ta":ta,"tb":tb})
            c.execute(text("""
                INSERT INTO approval_requests(id,tenant_id,action,requested_by)
                VALUES (:id,:tb,'g6-fixture-mismatch',:foreign_a)
            """),{"id":approval,"tb":tb,"foreign_a":ua})
        # Note: mismatch only possible on original plain FK without tenant link.
        raised=False
        try:
            command.upgrade(cfg,HEAD)
        except Exception as exc:
            raised="G6_EXISTING_CROSS_TENANT_REFERENCE" in str(exc)
        assert raised,"G6_LEGACY_TENANT_DRIFT_MUST_ABORT"
        with e.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==OLD
            retained=c.execute(text("""
                SELECT count(*) FROM approval_requests
                WHERE id=:id AND requested_by=:ua
            """),{"id":approval,"ua":ua}).scalar_one()
            assert retained==1,"G6_MIGRATION_FAILED_TO_PRESERVE_LEGACY_RECORD"
        print("G6_INCOMPATIBLE_APPROVAL_PREEXISTING_ROW_FAIL_CLOSED=PASS",flush=True)
        with e.begin() as c:
            c.execute(text("""
                UPDATE approval_requests SET requested_by=:same_tenant
                WHERE id=:id
            """),{"same_tenant":ub,"id":approval})
        command.upgrade(cfg,HEAD)
        with e.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==HEAD
            assert c.execute(text("""
                SELECT count(*) FROM approval_requests
                WHERE id=:id AND requested_by=:ub
            """),{"id":approval,"ub":ub}).scalar_one()==1
        print("G6_VALID_APPROVAL_REFERENCE_UPGRADE=PASS",flush=True)
        command.downgrade(cfg,OLD)
        with e.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==OLD
            assert c.execute(text("""
                SELECT count(*) FROM approval_requests WHERE id=:id
            """),{"id":approval}).scalar_one()==1
        print("G6_DOWNGRADE_WITH_EXISTING_VALID_ROW=PASS",flush=True)
        command.upgrade(cfg,HEAD)
        with e.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==HEAD
            assert c.execute(text("""
                SELECT count(*) FROM approval_requests WHERE id=:id
            """),{"id":approval}).scalar_one()==1
        print("G6_REUPGRADE_PRESERVED_VALID_ROW=PASS",flush=True)
        with e.begin() as c:
            c.execute(text("DELETE FROM approval_requests WHERE id=:id"),{"id":approval})
            c.execute(text("DELETE FROM users WHERE id IN (:a,:b)"),{"a":ua,"b":ub})
            c.execute(text("DELETE FROM tenants WHERE id IN (:a,:b)"),{"a":ta,"b":tb})
        print(f"G6_SYNTHETIC_MIGRATION_REHEARSAL=PASS seconds={time.monotonic()-start:.3f}",flush=True)
    finally:
        e.dispose()


if __name__ == "__main__":
    main()
