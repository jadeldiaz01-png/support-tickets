# G3 H-01..H-09 — reproducible adversarial audit package

**Dated:** 2026-10-13
**Scope:** `jadeldiaz01-png/support-tickets` only.
**Reviewed original:** PR #7 `675c3658e31f14eded626f38afed4542b5ac7e76` (flotaopd-del review `COMMENTED/HOLD`).
**This package:** successor *stacked* audit branch/PR with its **own HEAD/CI**.
**Authorization:** read code, add tests, documents, isolated CI only; `PRODUCTION_AUTHORIZED=false`. No merge, no staging/prod migration, no real credential, no messages.

## Evidence and interpretation
- `PASS` means a narrowly scoped automated test passed on its exact HEAD in CI;
  it is NOT proof that the real production environment satisfies the control.
- `XFAIL` means a deliberately unsatisfied security assertion in an isolated
  PostgreSQL fixture; it is a **known gap**, not a PASS. Strict XPASS fails CI
  so a fixed control must be reviewed and the marker removed.
- `BLOCKED` requires infrastructure, administrative privileges, customer data,
  outside reviewer reproduction or other separately authorized access.
- `HOLD` remains until independent reviewer certifies appropriate evidence
  and necessary security gaps are repaired or formally risk-accepted.

## Traceability matrix

| ID | Evidence already in PR #7 | New adversarial evidence | Remaining limitation / disposition |
|---|---|---|---|
| H-01 | RLS, explicit tenant predicates; cross-tenant HTTP 404 | Foreign read/write and assignment visibility under RLS; direct foreign-user FK negative **XFAIL** | Schema permits cross-tenant association via direct DB insert; composite (tenant_id,id) FK needed; **HOLD** |
| H-02 | Supervisor/admin `ticket:assign`, user-role check | Foreign assignee + forbidden roles + direct FK negative XFAIL | Real OIDC/OPA policy distribution unproven; **HOLD** |
| H-03 | Notes response returns UUID only; event metadata without text | Success/error/cross-tenant note text response, no text in event/audit; schema rejects unexpected fields | Log backend/error middleware/browser UI/exports not verified; **PARTIAL** |
| H-04 | `FOR UPDATE`, optimistic version, one-active unique index | Four concurrent assignment attempts share one version: only one success, others conflict | Sustained workload, latency and lock-failure drills pending; **PARTIAL** |
| H-05 | Actor/ticket/version/event and audit in one transaction | Verify no text in audit; runtime DELETE assertion marked **XFAIL** | Runtime CI role has DELETE on audit table; no append-only/immutable offsite export; **CONFIRMED GAP — HOLD** |
| H-06 | Alembic 0004 unique partial index; migration replay CI | Synthetic preexisting duplicates must prevent index build; read-only preflight SQL | Actual tenant DB state and isolated representative restore not inspected; **BLOCKED** |
| H-07 | OIDC/JWKS verifier, OPA fail-closed contract, CI policy tests | Production test-header injection blocked; missing policy and malformed URL denied | Real IdP/JWKS/OPA outage, rotation, mTLS and work identity not certified; **BLOCKED** |
| H-08 | No external delivery adapter in G3; internal note does not write outbox | API route absence + outbox count unchanged after note | External workflows not configured; future workers must get explicit gate; **PARTIAL** |
| H-09 | CI 38 pytest/20 OPA/3 jobs on PR #7; reviewer COMMENTED/HOLD | Exact refs + evidence template below | GitHub branch protection endpoints inaccessible to integration; no independent reproduced verdict or approval; **BLOCKED** |

## Baseline commands for independent reviewer

1. In an isolated environment, obtain exact immutable source:
   ```sh
   git clone https://github.com/jadeldiaz01-png/support-tickets.git
   cd support-tickets
   git fetch origin <AUDIT_HEAD_SHA>
   git checkout --detach <AUDIT_HEAD_SHA>
   git rev-parse HEAD
   python3 --version
   docker --version
   ```
   Do not record secrets or PII in posted logs. Reviewer must personally
   run the commands and record hashes; CI alone is not their attestation.
2. Verify static code and isolated non-DB tests:
   ```sh
   python3 -m pip install -r requirements-api.txt -r requirements-dev.txt
   python3 -m compileall -q api application repositories security policy migrations tests
   python3 -m ruff check --select E9,F63,F7,F82 api application repositories security policy tests
   python3 -m pytest -q tests/test_g3_audit_offline.py
   ```
3. Create disposable PostgreSQL 16 and configure `DATABASE_URL_OWNER`
   (schema owner) and `DATABASE_URL` (RLS-restricted `support_runtime`);
   use the pinned service, schema and role grants from
   `.github/workflows/runtime-container-ci.yml`. **Do not use live DB.**
   ```sh
   python3 -m alembic upgrade head
   python3 -m pytest -q tests/test_g3_audit_postgres.py
   python3 -m pytest -q
   python3 -m alembic downgrade base
   python3 -m alembic upgrade head
   ```
4. Check OPA with exactly pinned verifier in CI:
   ```sh
   /tmp/opa check --strict policy/support.rego policy/support_test.rego
   /tmp/opa test policy/support.rego policy/support_test.rego -v
   ```
5. Evaluate before/after counts of **synthetic** records; record all PASS,
   FAIL, XFAIL, XPASS, SKIP. Do not convert XFAIL to PASS. Confirm GitHub
   Actions three jobs and the *exact* audit SHA match.
6. **Administrative H-09:** repository administrator must read and evidence
   real `main` ruleset or branch protection, required checks, approvals, stale
   dismissal, codeowners, bypass users, force-push restrictions. An API 403
   is `UNKNOWN/BLOCKED`, not proof that controls are enabled or absent.
7. Report individually H-01..H-09 with timestamp/timezone, OS, versions,
   commands run, return codes, log links, hashes, concrete findings, risk
   severity **when reproduced**, and `PASS/PASS_WITH_FINDINGS/FAIL/BLOCKED`.
   Reviewer must state unexecuted steps explicitly.

## Priority findings requiring follow-up code changes (not silently accepted)

### Confirmed by repository code
- H-05: CI job grants `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES`
  including `audit_events` to runtime role. RLS confines tenancy but
  is *not* append-only integrity. Hardening will require restrictive grants,
  DB-level write prevention, approved retention/erasure design, independent
  tamper-evident export, and a new human-reviewed migration.
- H-01/H-02 structural gap: `ticket_assignments.user_id` references
  `users(id)` but has no composite foreign key verifying the user's
  `tenant_id`. App-layer membership validation protects the current API,
  but direct DB-writes bypass that rule. This can be corrected by composite
  `(tenant_id, id)` uniqueness + FK, after checking all child-table
  relationships and migration compatibility.
- H-03: `ticket_messages.author_type='HUMAN_AGENT'` for internal notes,
  without an explicit `visibility` discriminator. Although G3 exposes no
  message-fetch/customer reply API, a future adapter might accidentally expose
  those notes. Add enforceable internal-only visibility before enabling
  customer-facing readers or notifications.

### Evidence not yet available
- Real customer tenants/production datasets, production credential provenance,
  retention contracts, deployment configuration, OIDC/OPA failover, post-deploy
  observability, true UI, logs from independent reviewer, branch ruleset read.
- CI test counts are NOT a risk-weighted completion percentage.
- A DOC-only risk register cannot authorize actual customer operations.

## Reconciliation with official documentation
- PostgreSQL RLS does not automatically cover FK / referential-integrity checks:
  https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- PostgreSQL UNIQUE index creation rejects duplicate existing values:
  https://www.postgresql.org/docs/current/sql-createindex.html
- GitHub can dismiss stale reviews when code changes, depending on rules:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- OWASP API1 BOLA:
  https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/

**RELEASE STATUS:** `HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false`.
