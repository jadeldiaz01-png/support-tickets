# Support & Tickets production architecture

Status: FOUNDATION / NOT PRODUCTION AUTHORIZED.

## Authority

The Streamlit UI is not an authoritative system of record. PostgreSQL is the target
operational source of truth. Model output, browser state and health checks never grant
authorization.

## Target flow

Client / channel
-> public edge
-> Support API
-> OIDC identity
-> OPA authorization
-> application service
-> PostgreSQL
-> transactional outbox
-> worker / durable workflow
-> support agent
-> policy-gated tools
-> human approval for sensitive side effects
-> external adapter
-> reconciliation
-> immutable evidence + OpenTelemetry

## Foundation implemented in this increment

- Separate FastAPI surface.
- PostgreSQL schema and Alembic migration.
- Tenant-scoped Row Level Security policies.
- Idempotency key on ticket creation.
- Ticket event, transactional outbox event and audit event in one transaction.
- API and DB integration tests.
- Production fail-closed identity and policy placeholders.
- Separate hardened API image that is not wired into the live fleet.

## Explicitly not implemented yet

- Production OIDC/JWT verification.
- OPA/Rego remote decision integration.
- Workload identity/OpenBao integration.
- Outbox worker and external connector.
- Reconciliation worker.
- OpenTelemetry.
- Agent/LLM and tools.
- SLO/alerts, backup/restore certification and production deployment.

No item in this document changes PRODUCTION_AUTHORIZED=false.
