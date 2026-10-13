# G6.1 — exact conkey/confkey mapping and independent reproduction

Date: 2026-10-13. Original G6 PR #11 HEAD:
`50b966208a8f7940f56752d19524772d45f017f0`.
This PR is a **stacked review-only correction**; do not amend or merge
the earlier human-reviewed PR. **HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false**.

## Addressed review feedback

The G6 catalog test previously checked only that `tenant_id` appeared
in `conkey`. G6.1 inspects the ordered **`pg_constraint.conkey` and
`pg_constraint.confkey`** attribute lists and resolves them to both
child and parent column names using `pg_attribute` with ordinality.
For **every one of the 13 expected constraints**, it demands precisely:
- Child `tenant_id` maps to parent `tenant_id` in position one.
- Child target FK column maps to parent `id` in position two.
- Correct child table, parent table and **constraint name**.
- `convalidated = true` and no missing/duplicate/unexpected FKs.

Negative *meta-tests* mutate the synthetic mapping, including
`tenant_id -> id` and target column `-> tenant_id`, to show the
new catalog check rejects precisely the failure G6 reviewer highlighted.
Every one of the 13 direct-SQL cross-tenant INSERT tests now verifies
PostgreSQL `23503` and the expected `diag.constraint_name`, so a
different constraint's failure cannot create a false PASS.

## Exact HEAD vs GitHub merge test provenance

GitHub Actions `pull_request` checkouts default to a synthetic merge
commit. To avoid misattributing that merge to the author's exact SHA,
the **foundation** job now checks out the immutable
`github.event.pull_request.head.sha` (or push SHA), verifies
`git rev-parse HEAD` and logs `G61_EXACT_HEAD_TESTED`. The
`api-container` and `runtime-container` jobs continue exercising
the proposed integration merge; these are separate evidence types.
**CI is not personal independent reproduction, even for exact HEAD.**

## Access plan for flotaopd-del

No new PAT, SSH admin access, broad OAuth grants, secret sharing or
third-party accounts are needed. Existing authorized read-only GitHub
access can retrieve G6.1 via its own branch, PR, or commit permalink.

Preferred command (human uses their own workstation with functioning DNS):
```sh
git clone --filter=blob:none https://github.com/jadeldiaz01-png/support-tickets.git
cd support-tickets
git fetch origin <EXACT_G61_HEAD>
git checkout --detach <EXACT_G61_HEAD>
test "$(git rev-parse HEAD)" = "<EXACT_G61_HEAD>"
git show -s --format="%H %T %P" HEAD
```

If DNS fails, test DNS and outbound HTTPS to github.com without
disabling TLS validation, switching to an insecure mirror or using
someone else's credentials. With access through GitHub's own web UI,
the reviewer may inspect the immutable commit's files and sha and
download **read-only source**; however a downloaded ZIP is *not* a
verified Git checkout and cannot satisfy this script. To attest
reproduction the reviewer must obtain an independently verified
checkout of the specific commit in a functioning authorized environment.

Provision a **genuinely disposable** PostgreSQL 16 database, schema,
roles and pinned Python tools according to
`.github/workflows/runtime-container-ci.yml`. Verify `localhost`
is NOT forwarded to production or a remote persistent database. The
helper can TRUNCATE fixture tables and deliberately weakens schema
during migration drills. Then:

```sh
G61_EXPECTED_SHA=<EXACT_G61_HEAD> \
G6_DISPOSABLE_TEST_ONLY=YES SUPPORT_ENV=test \
bash ops/g61_reviewer_reproduce.sh
```

The helper checks exact commit, tracked-file cleanliness, commit object
connectivity, DB URLs and runs complete pytest plus G6 synthetic
migration rehearsal. Reviewer additionally runs pinned OPA checks
and logs every command, date, Python/PG/OPA versions, exit code,
actual source SHA/tree, PASS/FAIL/SKIP and limitations with redacted
evidence. **The implementer may not impersonate or sign for reviewer.**

## Subsequent gates: separate specific approval required

1. A scoped and lawful **representative restored database** with
   anonymization/access controls, resource estimate, lock monitoring,
   repair plan and reversible recovery drill.
2. Real role grants and PostgreSQL ownership in intended infrastructure.
3. Design and review of externally **tamper-evident** audit receipts:
   canonical records, signed hash-chain/Merkle manifests, independent
   key administration and retention-locked storage. No signing keys,
   external storage, deployment or vendor purchase in G6.1.
4. Branch administrative protection, OIDC/OPA deployment and
   human-reviewed integration release. **No merge, production migration,
   financial execution or customer outreach** under this authorization.
