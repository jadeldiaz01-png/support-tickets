# G5 — certification rehearsal and effective-permission evidence

**Scope:** G4 remediation PR #9 on immutable HEAD
`842ba2bf47fbe586a0aaafbb329af995ecfe2e0e`; this successor
branch must receive new review on its own exact HEAD.
**State:** `HUMAN_REVIEW_REQUIRED / HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false`.

## Purpose and limits

This package answers the requests in flotaopd-del's 2026-10-13
`COMMENTED/HOLD` review without claiming to impersonate or replace
the reviewer. It is a **synthetic isolated CI rehearsal**, NOT a
restoration of a representative real database, an infrastructure audit,
or an externally immutable storage design.

### Controls and evidence to gather
- **H-01/H-02:** enumerate all foreign keys among tenant-bearing tables, prove
  the two assignment composite constraints remain validated and identify
  uncoupled foreign keys still requiring risk assessment. Inventory output
  contains schema names only, never customer values.
- **H-05:** connect as the real isolated `support_runtime` database role,
  evaluate effective `has_table_privilege` (which includes role membership
  and PUBLIC), inspect `pg_auth_members`, role attributes, and the owner
  path. A rolled-back TRUNCATE demonstrates that the owner still has
  destructive ability despite a row UPDATE/DELETE trigger.
  **Do not declare immutable/WORM audit.**
- **H-06:** use `ops/g5_migration_rehearsal.py` ONLY against isolated
  PostgreSQL 16 CI service on 127.0.0.1 with support DB and explicit opt-in.
  Starting from 0005, downgrade to 0004, add synthetic valid and
  mismatched tenant assignments; verify 0005 aborts atomically without
  data loss on a mismatched row; replace with an allowed synthetic row;
  upgrade, downgrade and re-upgrade, verifying version and retained
  synthetic row after each step; delete script-owned synthetic rows.
  Enforce session lock timeout 5s and statement timeout 30s. Log timings
  as **CI-only samples**, not customer capacity/load evidence.
- **H-09:** read-only ruleset snapshot:
  `support-main-production-protection` active (ruleset ID 24338389),
  1 human approval / CODEOWNERS, 3 checks, thread resolution, no bypass.
  `dismiss_stale_reviews_on_push=false` and
  `require_last_push_approval=false` remain administrative risks;
  no permissions are changed in this branch.

## Reproduce (reviewer must execute personally)

Use disposable CI or deliberately isolated local PostgreSQL, not production.
The GitHub Actions workflow provisions PostgreSQL 16 and test roles; it
runs `pytest -q` and then the scripted migration rehearsal:

```sh
python3 -m pytest -q
G5_ISOLATED_CI_REHEARSAL=1 SUPPORT_ENV=test \
    python3 ops/g5_migration_rehearsal.py
```

The standalone script fails closed unless the owner URL is local
`postgres@localhost/support` or `postgres@127.0.0.1/support`,
the env is test and the explicit G5 flag is present.
Before reproduction, ensure the database is disposable, not a
production database tunneled through localhost.
Capture SHA, time, Python/PostgreSQL/Alembic versions, command
exit codes, 3 CI job outcomes, PASS/FAIL/SKIP/XFAIL and excerpts
without secrets or personal information.

### Acceptance gates (not an automatic release)

- Effective test runtime: SELECT/INSERT allowed, UPDATE/DELETE/TRUNCATE/
  TRIGGER and CREATE SCHEMA denied for audit.
- No direct or inherited membership expansion for disposable runtime role.
- Composite assignment foreign keys validated; catalog documents
  **all other uncoupled tenant relationships** with proposed priorities.
- Incompatible synthetic preexisting rows **must prevent** migration 0005,
  preserving 0004 and the record; compatible rows must upgrade, revert
  and upgrade again without loss.
- Deliberately rolled-back owner TRUNCATE demonstrates a **residual risk**,
  not a test of production audit immutability.
- Human reviewer must publish own commands and results. CI alone does
  not discharge the independence requirement.

## Still blocked by human and environment gates

Real representative restored data, actual production role membership
and secret provenance, high-volume migration locks and timings,
owner/superuser tamper-evident export, tenant constraints beyond
ticket_assignments, full OIDC/OPA, privacy retention and removal,
dashboard GUI, backups/restore, and independent gate approval.
No code change here touches production, payment, outbound messages,
repository rulesets or previous PR HEADs.

Primary references:
- PostgreSQL effective privileges:
  https://www.postgresql.org/docs/16/functions-info.html
- PostgreSQL role membership:
  https://www.postgresql.org/docs/16/role-membership.html
- PostgreSQL ownership limits:
  https://www.postgresql.org/docs/16/ddl-priv.html
- PostgreSQL pg_dump/restore caveats:
  https://www.postgresql.org/docs/16/app-pgdump.html
