# Threat model — Support & Tickets

Status: initial foundation threat model.

## Protected assets

- Tenant ticket content and customer PII.
- Authorization and approval state.
- Durable ticket/event history.
- Tool intent and reconciliation state.
- Secrets and external connector credentials.
- Audit/evidence integrity.

## Trust boundaries

1. Public/client input -> edge/API.
2. API -> identity provider.
3. API/application -> policy engine.
4. Application -> PostgreSQL.
5. Worker/agent -> model provider.
6. Agent -> typed tools.
7. Tool -> external support platform.
8. Runtime -> secrets manager and telemetry backend.

All ticket, attachment, email, web, RAG and external API content is UNTRUSTED_DATA.

## Priority threats and controls

| Threat | Initial control | Remaining gate |
| --- | --- | --- |
| Cross-tenant read/write | tenant_id + FORCE RLS + OIDC subject/tenant binding tests | expand CRUD/property isolation tests |
| Unauthenticated access | OIDC/JWT verification + durable user binding, fail closed | provision/configure production IdP/JWKS |
| Policy bypass | remote OPA client + deny-by-default Rego + policy tests | provision/configure production OPA and policy delivery |
| Duplicate side effect | idempotency key + outbox foundation | worker idempotency + reconciliation |
| Prompt injection | no LLM authority exists yet | adversarial agent eval suite |
| Secret exfiltration | no model or connector credential introduced | OpenBao/workload identity |
| Audit tampering | append-only audit table foundation | immutable evidence export/attestation |
| Supply-chain compromise | pinned direct dependencies/base image | transitive lock, SBOM, provenance, scan |
| Data loss | durable schema foundation | encrypted backup and isolated restore drill |
| Privileged action without human approval | no external side-effect tool implemented | approval state machine and tool gate |

## Fail-closed invariants

- Missing identity => deny.
- Missing policy engine => deny.
- Missing tenant context => PostgreSQL RLS denies.
- Unknown external side-effect state => RECONCILE, never blind retry.
- Model output can never grant identity, policy or production authority.
