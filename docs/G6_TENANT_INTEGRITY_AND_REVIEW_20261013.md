# G6 — all tenant-bearing FK relationships: correction and human reproduction

**Prior review:** flotaopd-del G5 HOLD on PR #10 HEAD
`d7812cc3cf7669267871b2f74cfacab86643da94`.
**This PR is dependent/stacked, code-only, not deployable without approval.**
Status: `HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false`.

## Design scope: 13 remaining single-column foreign keys

G5 catalog identified **15** non-tenants parent references:
2 validated tenant-coupled assignment FKs plus 13 legacy uncoupled FKs.
G6 adds validated tenant-coupled references for the remaining **11** and
removes all **13** redundant plain FK constraints, including the two
originally superseded by G4. Result expected in disposable test schema:
13 tenant-coupled, zero plain FKs among listed direct tenant-bearing
parent-child references. Does not guarantee complete schema isolation
for polymorphic references or orphan non-FK identifiers.

| Child | Parent | Column | On delete |
|---|---|---|---|
| `ticket_assignments` | `tickets` | `ticket_id` | `CASCADE` |
| `ticket_assignments` | `users` | `user_id` | `RESTRICT` |
| `approval_requests` | `users` | `decided_by` | `SET NULL (decided_by)` |
| `approval_requests` | `users` | `requested_by` | `SET NULL (requested_by)` |
| `approval_requests` | `tickets` | `ticket_id` | `CASCADE` |
| `reconciliation_records` | `tool_intents` | `intent_id` | `CASCADE` |
| `ticket_events` | `tickets` | `ticket_id` | `CASCADE` |
| `ticket_messages` | `users` | `author_user_id` | `SET NULL (author_user_id)` |
| `ticket_messages` | `tickets` | `ticket_id` | `CASCADE` |
| `ticket_sla_state` | `tickets` | `ticket_id` | `CASCADE` |
| `ticket_tags` | `tickets` | `ticket_id` | `CASCADE` |
| `tickets` | `customers` | `customer_id` | `SET NULL (customer_id)` |
| `tool_intents` | `tickets` | `ticket_id` | `CASCADE` |

G6 migration `0006_tenant_fks` adds composite uniqueness for
`customers(tenant_id,id)`, `tool_intents(tenant_id,id)`, fails closed
for legacy tenant-incompatible references without exposing row identifiers,
adds all 11 new validated composite FKs, then removes 13 obsolete plain
constraints. The migration preserves prior ON DELETE semantics, especially
`SET NULL (author_user_id)`, `SET NULL (customer_id)`,
`SET NULL (requested_by)`, `SET NULL (decided_by)`:
**tenant_id never becomes NULL**. PostgreSQL 16 supports column-specific
SET NULL. Rollback deliberately weakens isolation and must not be executed
on production without its own approval.

## Negative tests
- Parametrized direct SQL attempts to associate a tenant-B row with a
  tenant-A parent for all 13 relationships; each must fail with a database
  foreign-key integrity error, not just a 404 from application policy.
- Schema catalog expected 13 validated tenant-coupled foreign keys.
- Deletion of optional parent user/customer keeps child `tenant_id` intact.
- Prior G3/G4/G5 tests must remain PASS with no XFAIL.
- Full PostgreSQL migration downgrade/replay, G5 synthetic mismatch
  rehearsal and unprivileged runtime audit role checks continue in CI.

## Reviewer access / DNS fallback (no secrets; no broad PAT)
The user-authorized human reviewer should obtain the exact repository
content from GitHub with their existing **read-only repository permission**:
```sh
git clone --filter=blob:none https://github.com/jadeldiaz01-png/support-tickets.git
cd support-tickets
git fetch origin <G6_HEAD_SHA>
git checkout --detach <G6_HEAD_SHA>
git rev-parse HEAD
```
If that fails due DNS, verify network DNS/HTTPS to `github.com` on the
reviewer's own machine; use a known-good network. Other authorized read-only
methods: GitHub Code → Download ZIP at exact SHA, or REST `/tarball/<SHA>`
using an allowed read-only GitHub connector. A ZIP without `.git` does
**not** itself prove exact commit identity; compare against GitHub's
immutable tree/blob hashes and code manifest before attesting.
No GitHub App token, PAT, account secret or credential should be posted
in a PR. Do NOT ask the implementer to impersonate the reviewer.
- In the independently obtained Git checkout at reviewed HEAD, execute
  `ops/g6_reviewer_reproduce.sh` with `G6_DISPOSABLE_TEST_ONLY=YES`
  and a disposable, isolated database. The script checks HEAD, target
  database URI shape, and runs negative tests. A localhost database
  **might be a proxy or a tunnel**: reviewer must independently ensure
  it is not linked to production.
- Record environment, SHA, timestamps, commands, exit codes and minimal
  redacted evidence. Publish `PASS/PASS_WITH_FINDINGS/FAIL/BLOCKED` only
  for steps actually executed. CI evidence is not independent attestation.

## Further blocked gates
1. Rehearse 0006 against separately authorized **representative restored**
   data with privacy/backup controls and a tested recovery plan.
2. Inventory all effective production privileges with authorized read-only
   scope; do not equate CI permissions with production.
3. Design tamper-evident and independently retained audit receipts:
   bounded batches of canonical audit events → SHA-256 digest →
   signed manifest by a least-privilege independent identity →
   write-once retention-capable store (provider, legal basis, retention,
   key rotation, cost and restoration subject to later approval) →
   periodic verification and discrepancy alerts. No external store or
   signing key is provisioned in G6. Hashing alone is not immutable.
4. Validate non-FK polymorphic IDs and application row-level filters and
   test restore/cascade semantics before production release.
5. Independent human review, updated ruleset approvals and separate
   merge/deployment human gates.

Primary reference: https://www.postgresql.org/docs/16/ddl-constraints.html

CI G5 synthetic rehearsal deliberately downgrades to 0004, tests 0005 and upgrades back to 0006. Reviewer helper requires the independently supplied exact `G6_EXPECTED_SHA`, never a self-changing hardcoded commit hash.

### G6 legacy migration negative rehearsal
The CI foundation job now downgrades `0006→0005` **only in disposable CI**, inserts a synthetic cross-tenant approval requester accepted by the old plain FK, verifies that re-upgrading 0006 fails atomically without losing the record, corrects the synthetic link, upgrades, downgrades and re-upgrades while retaining the row. The script requires `G6_DISPOSABLE_TEST_ONLY=YES`, local PostgreSQL 16, `SUPPORT_ENV=test`; no real snapshot or production data. This is not a license to alter historical customer rows.
