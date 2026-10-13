# Support & Tickets

Production foundation for the Jadel Tech RD support service.

Current state: **FOUNDATION / PRODUCTION_AUTHORIZED=false**.

The original Streamlit UI remains available as a non-authoritative interface while a
separate FastAPI + PostgreSQL backend is being introduced behind explicit identity,
policy and deployment gates.

See:

- `docs/ARCHITECTURE.md`
- `docs/THREAT-MODEL.md`
- `docs/ADR-001-production-foundation.md`
- `docs/BRANCH-GOVERNANCE-CONTRACT.md`

No repository code, health check or model output grants production authority.

## G1 Dashboard integration (Draft; not deployed)

The isolated `feat/governed-ticket-dashboard-g1-20261013` branch proposes
a read-only, tenant-scoped ticket summary endpoint for authorized supervisors
and administrators, plus adversarial authorization and PostgreSQL tests.

- Contract: `GET /v1/dashboards/tickets/summary?start=YYYY-MM-DD&end=YYYY-MM-DD`
- UTC end-exclusive, 1–90 day window, current ticket statuses for created cohort.
- Metrics are SQL-derived; no synthetic Streamlit data or SLA values are used.
- Separate `dashboard:read` OPA decision and RLS enforcement.
- The client-facing dashboard UI, real identity provider, policy runtime, observability,
  reconciliation and backup/restore certification remain **BLOCKED / NOT DONE**.

See `docs/SUPPORT_DASHBOARDS_G1_PRODUCTION_READINESS_20261013.md` for
quantitative targets, source references, unverified gates and the integration contract.
This branch must pass CI and independent review before merging. No product launch
or financial/production permission is conferred.
