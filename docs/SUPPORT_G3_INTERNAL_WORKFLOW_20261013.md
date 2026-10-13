# G3 — Internal workflow, tenant isolation & human review

Date: 2026-10-13. Status: **DRAFT / PRODUCTION_AUTHORIZED=false**.
Stacked on (not merged with): support-tickets PR #6, HEAD
`225885bc21304e8c419291a16bd1ef6a8b1d2acd`.
Review on the exact new HEAD only; any new commit invalidates prior approval.

## Scoped changes
- PATCH `/v1/tickets/{ticket_id}/assignment` (SUPERVISOR/ADMIN only).
  Body: `{"assignee_user_id":"<tenant user UUID or null>","expected_version":1}`.
  The assignee must belong to same tenant and hold SUPPORT_AGENT/SUPERVISOR/ADMIN role.
  Unassign using explicit JSON null. Unchanged assignment -> 409.
  CLOSED ticket -> 409. Every accepted change increments ticket version.
- POST `/v1/tickets/{ticket_id}/internal-notes` (internal human roles only).
  Body: `{"body":"private operational text","expected_version":2}`.
  Content saved to tenant-scoped PostgreSQL message table; only opaque note UUID
  returned, no note text or customer details echoed.
  This is **not a customer reply** and does not send email/chat/WhatsApp.
- Transactionally append event and audit rows *without note body*.
  Deliberately DO NOT create outbox events for these internal-only operations.
  A later external side-effect dispatcher must have a separate authorization,
  approval, idempotency and reconciliation contract.
- PostgreSQL partial unique index blocks multiple active assignments even if
  future code misses row locking. Use `SELECT ... FOR UPDATE` on ticket rows,
  and `expected_version` to reject stale concurrent writes.
- Explicit OPA and local-test policy restrictions.
- `Cache-Control: private, no-store` on new response endpoints.

## Adversarial test scenarios
- Deny unauthorized customer/service-worker roles, missing identity, missing
  policy, foreign ticket and foreign assignee.
- Deny tenant-local user with CUSTOMER role as assignee.
- One active assignment, clean unassign, optimistic concurrency conflict.
- Internal note text exists only in ticket_messages, not response/audit/event.
- Ticket version monotonic and auditable; no outbox delivery from internal notes.
- Run real CI PostgreSQL and OPA tests, migration upgrade/down/replay.
- Evaluate uniqueness index migration against existing production rows before
  any future deployment: duplicate active assignments would make DDL fail
  closed; this PR does NOT touch deployed databases.

## Remaining before any production claim
Real OIDC + OPA provisioned, secrets, tenant-scoped authenticated dashboard UI,
user-facing messages with approval gates, external outbox dispatcher and
reconciliation, SLA provenance, alerting, privacy/data retention and deletion,
backup/restore drills, capacity tests, human review, administrative branch
protection verification, staged rollout and rollback approval.

Sources: PostgreSQL row locking
https://www.postgresql.org/docs/17/explicit-locking.html
OWASP BOLA https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/
