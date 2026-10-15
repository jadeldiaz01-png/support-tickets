# G2 tenant integrity hardening design

Date: 2026-10-15  
Status: **DESIGN — awaiting user review; no implementation authorized by this document alone**  
Repository: `jadeldiaz01-png/support-tickets`  
Base: `main` at `44e3a878aa7c3e3a80ec7004d29986b8f718c7d5`

## Intent and current state

The requested first gate, G2, is already merged in PR #6. It provides tenant-scoped ticket creation, request fingerprints for idempotency, concurrent duplicate protection, and versioned status transitions. Its later adversarial review identified a remaining database-level integrity gap: several foreign keys validate a referenced row's ID without validating that its tenant matches the child row's tenant. The CI runtime role also has write access to audit records beyond insertion.

This increment closes those two database control gaps so API validation and row-level security have defense in depth. It is a source and isolated-CI change only. Production identity, deployment, customer data, external connectors, message delivery, and production authorization remain out of scope.

Evidence reviewed: [G3 H-01..H-09 audit at PR #8 HEAD `9911bf4`](https://github.com/jadeldiaz01-png/support-tickets/blob/9911bf42653176d2a9cebd46d36fad503289a9e4/docs/G3_H01_H09_REPRODUCIBLE_AUDIT_20261013.md); [G6 tenant-FK proposal PR #11 HEAD `50b9662`](https://github.com/jadeldiaz01-png/support-tickets/pull/11). These are proposals/CI evidence on their respective commits, not production certification.

## Options considered

1. **Keep application-only tenant checks.** Smallest patch, but direct database writes and future code paths can still create cross-tenant references. Rejected because it leaves the identified invariant unenforced at the storage boundary.
2. **Add composite tenant-scoped foreign keys with fail-closed migration preflight, and make runtime audit access append-only.** Uses PostgreSQL and Alembic already present, preserves RLS and current APIs, and blocks unsafe upgrades without deleting data. Recommended.
3. **Replace PostgreSQL or introduce a separate authorization/data service.** Adds operational complexity and does not remove the need for relational integrity controls. Rejected for this gate.

## Design

### Tenant-coupled foreign keys

For each tenant-scoped parent, add a unique key on `(tenant_id, id)` where needed. Replace ID-only foreign keys with tenant-coupled pairs for all 13 non-tenant-parent relationships:

| Child reference | Parent | Existing delete behavior |
| --- | --- | --- |
| `tickets.customer_id` | `customers` | Set only `customer_id` to NULL |
| `ticket_messages.ticket_id` | `tickets` | CASCADE |
| `ticket_messages.author_user_id` | `users` | Set only `author_user_id` to NULL |
| `ticket_events.ticket_id` | `tickets` | CASCADE |
| `ticket_assignments.ticket_id` | `tickets` | CASCADE |
| `ticket_assignments.user_id` | `users` | RESTRICT |
| `ticket_tags.ticket_id` | `tickets` | CASCADE |
| `ticket_sla_state.ticket_id` | `tickets` | CASCADE |
| `approval_requests.ticket_id` | `tickets` | CASCADE |
| `approval_requests.requested_by` | `users` | Set only `requested_by` to NULL |
| `approval_requests.decided_by` | `users` | Set only `decided_by` to NULL |
| `tool_intents.ticket_id` | `tickets` | CASCADE |
| `reconciliation_records.intent_id` | `tool_intents` | CASCADE |

Nullable references that currently use `SET NULL` use PostgreSQL 16's column-list form so deletion does not erase the non-null `tenant_id`. The schema explicitly uses `CASCADE` for nullable `approval_requests.ticket_id`; retain that behavior. The implementation must confirm each action against the migration before changing it; any ambiguity or mismatch is a design stop, not a reason to silently alter semantics. `outbox_events.aggregate_id` is polymorphic and remains outside ordinary FK enforcement; it needs a separately designed typed-reference contract before it can be constrained.

### Safe migration behavior

- A new Alembic migration inventories each legacy reference and checks for missing or cross-tenant parents before replacing constraints.
- Any incompatible row aborts the migration with a stable, sanitized error code. The migration does not delete, rewrite, null, or backfill customer records to make the constraint pass.
- Constraint creation and legacy constraint removal occur transactionally where PostgreSQL supports it. Tests prove the schema version and incompatible fixture rows remain unchanged after failure.
- Valid synthetic data must upgrade, downgrade, and replay deterministically. Downgrade removes tenant-coupled protection and is a security-weakening operation; it is for disposable CI/recovery rehearsal only, never an implicit production rollback.
- Add indexes/unique keys required by the referenced pairs. Do not add redundant indexes if PostgreSQL creates an equivalent unique index.

### Audit write boundary

- The application runtime role may read and insert `audit_events`; it may not update, delete, truncate, create triggers, or create schema objects. Existing minimum rights for other tables remain sufficient for the API and workflow.
- Add a database trigger that rejects row UPDATE and DELETE on `audit_events` as defense in depth. CI tests execute writes as the runtime role and verify insert succeeds while mutation fails.
- The database owner/superuser can still alter schema or truncate data. This change does not claim WORM storage, independently anchored signatures, external retention, or protection from a privileged database administrator.
- Audit errors must not expose tenant existence or record contents to API callers.

### Compatibility and operations

- Keep PostgreSQL 16, Alembic, current RLS policies, API contracts, request-fingerprint semantics, and the transactional ticket/event/outbox/audit boundary.
- Use only synthetic disposable PostgreSQL in local/CI validation. No live database URL or customer data is acceptable.
- Add no infrastructure service or runtime dependency.
- Keep `PRODUCTION_AUTHORIZED=false`; do not deploy, merge, provision credentials, or enable a support channel in this increment.

## Validation and acceptance

The implementation is acceptable only when all are true on the exact candidate SHA:

1. Catalog inspection in disposable PostgreSQL shows all 13 intended relationships have validated tenant-coupled FK columns; no legacy ID-only duplicate remains for those pairs.
2. Negative SQL tests attempt cross-tenant inserts for every pair and each is rejected; tests also cover all preserved CASCADE, RESTRICT, and nullable-delete behavior.
3. A synthetic legacy cross-tenant reference makes the migration abort, leaves the row intact, and leaves Alembic at its pre-upgrade revision. A clean compatible fixture upgrades, downgrades, and replays.
4. Runtime-role tests show audit SELECT/INSERT are allowed and UPDATE/DELETE/TRUNCATE/trigger/schema creation are denied, with no inherited privilege path in the CI role.
5. Existing G2 API idempotency, racing-request, cross-tenant and version-transition tests remain green; existing G3 tests remain green.
6. Exact-SHA CI passes compile/lint, Python tests, pinned OPA checks, API/runtime container health and migration rehearsal. CI results do not replace independent security review or production evidence.
7. Documentation states remaining risks: privileged owner can alter/truncate audit; polymorphic outbox references remain unbound; live IdP/OPA, workers/reconciliation, observability/SLOs, backup/restore, load tests and release authorization are still unproven.

## Decision record

Use PostgreSQL composite foreign keys plus fail-closed, data-preserving migration preflight for tenant integrity. Restrict runtime audit privileges and reject row mutation in the database. Keep scope isolated to code and synthetic CI. Defer external evidence storage, provider configuration, customer rollout and production release to separately reviewed gates.

## Official reference

PostgreSQL 16 documents column-specific `ON DELETE SET NULL` for foreign-key actions, which allows a nullable reference to be cleared while retaining its tenant key: [CREATE TABLE / referential actions](https://www.postgresql.org/docs/16/sql-createtable.html).

