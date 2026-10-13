# G7 — RLS regression and polymorphic-reference inventory (test-only)

**Base:** G6.1 PR #12, SHA `48fb8d1b2018fab021747ac6d8f731db29f17314`.
The user waived **optional independent review requests** for continued
technical implementation. This does not override the current GitHub
`main` ruleset (one approval, code-owner review, required CI and thread
resolution), permit direct main writes, or authorize merge/deployment.

## Security checks in G7

- Catalog exact set of 14 tenant-bearing tables plus `tenants`.
  `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` must both
  remain true, with a fail-closed tenant-isolation policy including
  `USING` and `WITH CHECK`.
- On a disposable PostgreSQL 16 database, create **two synthetic tenants**
  with a valid row for *every* scoped table. Test that an unbound runtime
  session sees zero rows, each tenant sees only its own rows, and that
  `set_config(..., true)` cannot leak across transactions.
- Verify a forbidden cross-tenant INSERT/UPDATE on `knowledge_sources`
  fails with the RLS-specific PostgreSQL SQLSTATE `42501` and leaves
  the original row untouched.
- Inventory residual fields: `outbox_events.aggregate_id`,
  `audit_events.resource_id`, `audit_events.actor_id`. These fields
  cannot be considered tenant-safe merely because their *containing*
  tables have RLS. A human needs to examine type-specific checks,
  historical deleted resources, actor lifetime semantics, and potential
  enforcement without breaking audit/outbox retention. **Do not
  attach a broad FK to these fields without investigating retention.**
- `ops/G7_POLYMORPHIC_REFS_READONLY.sql` is read-only and shows only
  grouped counts. It is **not executed on real infrastructure**, and
  historical missing rows need analysis rather than automatic deletion.

The tests are guarded by `SUPPORT_ENV=test`, local-owner and runtime URL
shapes. Localhost alone does NOT establish real disposal; only use the
isolated GitHub Actions PostgreSQL service or a separately certified
ephemeral test environment. Tests use owner-level `TRUNCATE ... CASCADE`,
so never run them on production/tunneled/local persistent data.

## Release conditions not changed

`HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false`.
Representative restored data, external tamper-evident audit, actual
production privileges, and changing main's administrative branch
rules are **separate, explicitly gated decisions**.
No secrets, outreach, payments, production migrations or deployment.
