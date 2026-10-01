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
