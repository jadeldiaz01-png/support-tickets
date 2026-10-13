# G1 — Support & Tickets × Dashboards: quantitative production-readiness package

Date: 2026-10-13
Repos: `jadeldiaz01-png/support-tickets` (code), `jadeldiaz01-png/jadeltechrd.com` (commercial catalog)
Relation: revenue opportunity / growth issue `jadeldiaz01-png/ai-income-revenue-engine#126`

> **STATUS: PRE-PRODUCTION / PRODUCTION_AUTHORIZED=false.**
> This PR is a source-level contribution and does **not** certify production readiness,
> enable deployment, provision tenants/identities, publish a new service, contact buyers
> or authorize charging customers. Any previous Streamlit demo statistics are synthetic.

## 1. Scope completed in this branch (verify by actual CI before merge)

- New read-only `GET /v1/dashboards/tickets/summary?start=YYYY-MM-DD&end=YYYY-MM-DD`.
- Contract: UTC start-inclusive/end-exclusive dates; bounded to 1–90 days; reject invalid windows with 422.
- SQL aggregates only; **no subject, ticket body, customer IDs, external identities, email, or ticket IDs** in response.
- Output: `total_created`, grouped `status_counts`, `priority_counts` and `created_by_day`, `generated_at`, `timezone=UTC`, explicit `cohort_definition`.
- Important semantics: counts cover tickets **created in the interval**, and their status and priority reflect the state **at query time**; counts are NOT historical status snapshots or SLA compliance indicators.
- Separate `dashboard:read` authorization: SUPERVISOR/ADMIN only, OPA allow contract; deny SUPPORT_AGENT, CUSTOMER and SYSTEM_WORKER. Non-production local tests mirror this.
- Existing tenant-scoped PostgreSQL `FORCE ROW LEVEL SECURITY` stays active; explicit `tenant_id` filter adds defense in depth. New composite index `(tenant_id, created_at DESC)`.
- Critical prerequisite hardening: reject ticket creation referencing a customer outside the actor's tenant; FK references alone do not prove tenant ownership.
- Offline API/schema/security tests plus PostgreSQL-backed cross-tenant test and OPA policy tests; outcome is **not claimed** until CI executes on the exact PR HEAD.

## 2. Quantitative inventory (source-backed, not runtime certification)

| Capability | Observed before this branch | Change/proposed gate |
| --- | --- | --- |
| FastAPI ticket create/read | Code present | Retain API |
| PostgreSQL + Alembic | Initial schema exists | Add index migration 0002 |
| Tenant RLS | ENABLE+FORCE RLS in migration | Additional negative cross-tenant tests |
| Identity verification | OIDC verifier + user binding code | Real IdP/JWKS + rotation drill missing |
| Authorization | OPA deny-by-default policy code | Real policy service + outage drill missing |
| Event/outbox/audit | Created transactionally in ticket create | Publisher + retry/dead-letter/reconcile absent |
| Support dashboard backend | Synthetic Streamlit charts | Tenant-safe aggregate endpoint proposed |
| Support dashboard front-end | Demo Streamlit UI only | Authenticated client + filter, export and accessibility audit missing |
| Human handoff | Concept/schema exists | Real assignment/escalation/review workflow missing |
| SLA figures | Demo hard-coded values | First-response/resolution event pipeline + calculation missing |
| OpenTelemetry/SLOs | Not certified | Instrumentation, PII policy, alerts missing |
| Backup/restore/DR | Not certified | Encrypted backup and isolated restore drill missing |
| CI/security/supply chain | Existing CI with Postgres + OPA tests | New HEAD must pass; SBOM/transitive lock/provenance gates pending |
| Go-live / secrets | Production flag false | Human release authorization and canary + rollback pending |

**14 assessed capabilities.** This matrix tracks code evidence vs certification; **do not derive a production-readiness percentage** because criteria are not equally weighted and many cannot be verified without live infrastructure.

## 3. Proposed SLOs and acceptance criteria — TARGETS, NOT MEASUREMENTS

| Metric/criterion | Proposed gate | Measurement |
| --- | --- | --- |
| API availability | >=99.9% across 30 days | Good requests / eligible requests, synthetic+server SLIs |
| 30-day error budget at 99.9% | 43.2 minutes equivalent | 30×24×60×0.001 (example, not measured downtime) |
| Dashboard read latency | p95 <= 800 ms on reference load | Authorized GET server latency with real dataset |
| Ticket creation latency | p95 <= 1 s on reference load | POST duration including database commit |
| Cross-tenant leakage | 0 unauthorized accesses in negative suite | Two-tenants RLS and forged-customer tests |
| Incorrect policy allows | 0 across adversarial/OPA tests | Fault injection, unknown action/role |
| Repeated notification or external action | 0 duplicates | Outbox idempotency and reconciliation E2E (not implemented) |
| Initial load test | 25 req/s for 15 min | Staging only; adjust to measured capacity and tenant mix |
| Restore targets | RPO <= 15 min; RTO <= 60 min | Separate backup/restore exercise |
| Release gate | 100% required checks PASS | Exact SHA, independent review, signed artifact evidence |
| Dashboard audit | 100% aggregates reconcile to source | Controlled PostgreSQL fixture + independently reconciled sample |
| Front-end | WCAG 2.2 AA checks | Automated + manual keyboard/screen-reader audit |

These numbers are **candidate engineering acceptance thresholds** to be approved and capacity-tested. They are not claims about achieved performance, SLA offered to customers, or existing support coverage. SLO 99.9% derives from Google's error-budget methodology; 43.2 min assumes a 30-day month.

## 4. Quantitative evaluation template for a real pilot

Use only **synthetic test data** until privacy/legal basis and customer consent are certified.
A capacity scenario, not measured customer usage: 10 tenants × 5,000 tickets = 50,000 tickets. Staging must then separately benchmark queries over last 1, 7, 30 and 90 UTC days, record p50/p95/p99, row counts and PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`; test both high-volume and low-volume tenants. Protect performance telemetry from accidental PII exfiltration. Repeat with cold/warm cache and concurrent OIDC/OPA calls. Reject approval if p95 threshold fails, tenant access leaks, or index scans fail unexpectedly.

Data quality:
- `total_created == sum(status_counts.values()) == sum(priority_counts.values()) == sum(created_by_day.count)`.
- No negative counts; no source PII in aggregate response.
- Unknown, stale or incomplete event information must not become synthetic SLA metrics.
- Separate `status` at query-time from historically reconstructed state and report time windows in UTC.
- If small-group privacy thresholds are required by the tenant agreement, introduce explicit suppression rules before enabling analytics for that tenant (not included in current PR).

## 5. Client integration contract (future site/UI PR required)

```http
GET /v1/dashboards/tickets/summary?start=2026-10-01&end=2026-10-08
Authorization: Bearer <OIDC access token>
```

The response is a JSON summary, not a webpage or a public endpoint. The browser must **not** send `X-Tenant-ID`, `X-Actor-ID`, or `X-Role` in production; headers are non-prod testing only. Configure allowed CORS origins explicitly, session expiry, CSRF where relevant, no cross-tenant caching, `Cache-Control: no-store` at authenticated endpoints and strict security headers. The production edge must verify its actual backend origin and HTTPS trust, and prohibit direct public access to OPA/PostgreSQL. The web project remains commercial intake only until its own separately reviewed dashboard client and lawful data integration are implemented.

The **Streamlit UI remains non-authoritative**; never publish synthetic ticket totals or fixed first-response/resolution-time values as real customer KPIs.

## 6. Remaining gates in dependency order

1. **G2 tenant/customer integrity**: prove all parent/child FK tenant checks, request idempotency payload mismatch handling, status transition integrity, field-level authorization, pagination, rate limiting and duplicate racing requests.
2. **G3 real identity/policy:** provision approved IdP/JWKS, OPA runtime, least-privilege role, secure secrets and outage/fail-closed certification.
3. **G4 support workflow:** add update/assign/respond/escalate/resolve, durable approvals, scoped knowledge base and optional read-only agent drafts; do not let LLMs send messages autonomously.
4. **G5 delivery reliability:** outbox dispatcher, retry+dedup, poison queue, delivery acknowledgement and UNKNOWN reconciliation with human gates for outbound actions.
5. **G6 dashboard delivery:** real authenticated accessible UI, permitted data sources, signed/no-store exports, accurate SLA source-event computation; no synthetic reports.
6. **G7 operations:** tracing/metrics/logging, PII scrub, SLI sampling, alerts, runbooks, on-call ownership, backup/restore drill, load/recovery test and vulnerability/SBOM checks.
7. **G8 commerce:** ensure service quote, legal terms, production subscription provisioning and payment-ledger reconciliation; do not infer payment from quote or PayPal intent.
8. **G9 release:** independent human review of exact HEAD, branch rules and CI PASS, threat model + security/privacy approval, approved staging canary and explicit production authorization. Otherwise remain BLOCKED.

## 7. Locally reproducible commands (no deployments)

```sh
python3 -m pip install -r requirements-api.txt -r requirements-dev.txt
python3 -m compileall -q api application repositories security policy migrations tests
python3 -m ruff check --select E9,F63,F7,F82 api application repositories security policy tests
python3 -m pytest -q tests/test_dashboard.py tests/test_api.py tests/test_identity_policy.py
# PostgreSQL integration: provision isolated test database, then run existing CI.
# OPA: use the exact pinned binary in .github/workflows/runtime-container-ci.yml
# and test policy/support.rego + policy/support_test.rego.
```

## 8. External sources and rationale (verified 2026-10-13)

- OWASP API Security Top 10 — BOLA and broken authorization: https://api-security.owasp.org/editions/2023/en/0x11-t10/
- PostgreSQL RLS, table owner bypass and FK covert-channel risks: https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- NIST AI 600-1 GenAI Risk Management Profile: https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- OWASP LLM01 Prompt Injection (agent capability not yet implemented): https://genai.owasp.org/llm-top-10/
- W3C WCAG 2.2 Recommendation: https://www.w3.org/WAI/news/2023-10-05/wcag22rec/
- OpenTelemetry GenAI semantic conventions (some definitions marked Development; pin versions): https://github.com/open-telemetry/semantic-conventions-genai
- Google SRE error budget: https://sre.google/workbook/error-budget-policy/

All external references inform engineering priorities; they do not prove this repository meets the standards.
