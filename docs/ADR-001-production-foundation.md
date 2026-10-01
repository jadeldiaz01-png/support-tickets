# ADR-001: PostgreSQL + transactional outbox foundation

Date: 2026-09-30
Status: Proposed in PR; not production authorized.

## Context

The current Streamlit template stores ticket state in process-local session state.
That cannot provide durability, multi-tenant isolation, idempotency, reconciliation
or auditable recovery.

## Decision

Use PostgreSQL as the authoritative operational store and Alembic for schema change.
Begin with a transactional outbox instead of Kafka or another broker. Keep Streamlit
as a future administrative client rather than an authority.

The API is FastAPI/Python to reuse the current language/runtime. Production identity
and policy remain fail-closed until OIDC and OPA are integrated and certified.

## Consequences

Positive:
- ACID boundary for ticket + event + outbox + audit.
- Minimal new infrastructure.
- RLS defense in depth for tenant isolation.
- Retry-safe path can be built without distributed transaction assumptions.

Costs:
- Outbox delivery/reconciliation worker remains to be implemented.
- PostgreSQL backup/HA/SLO are not certified by this ADR.
- OIDC/OPA integration is mandatory before any production API enablement.
