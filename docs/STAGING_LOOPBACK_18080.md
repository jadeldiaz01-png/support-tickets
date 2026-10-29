# Staging-only support API on 127.0.0.1:18080

Status: **proposed infrastructure; NOT deployed; PRODUCTION_AUTHORIZED=false**.

## Purpose and isolation

Run the existing `Dockerfile.api` as a separate Compose project named
`jadel-support-api-staging` on the VPS, publishing only host loopback port
`127.0.0.1:18080` to container port `8000`. The host's
`127.0.0.1:8000` is currently used by the **nexus-ai-automation-prod**
container and `127.0.0.1:8787` by the private gateway; do not change,
restart, reconfigure, or attach this stack to either service.

The API uses mandatory OIDC authentication and OPA policy mode, even in
staging. Without provisioned staging OIDC, policy service, a separately
authorized staging PostgreSQL role, migrated schema, and valid tenant data,
protected ticket operations will remain unavailable. This Compose file does
**not** create PostgreSQL, install OPA, configure OIDC, run migrations,
change DNS/firewall/proxy settings, or attach to the production database.

The backend still lacks certified production identity/policy runtime,
outbox delivery, observability, backup/restore and production approval.
Liveness is **not** a production-readiness certificate.

## Evidence-only preflight (safe, no state change)

From a checked-out approved commit:

```bash
sudo ss -ltnp | grep -E ':(8000|8787|18080)\b' || true
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
python -m pytest -q tests/test_staging_loopback_infrastructure.py
```

Confirm port 18080 is free before any manual startup, verify Docker Engine is current (at least v28.0.0; preferably a patched v28.3.3+ release), and record the
exact commit SHA. Confirm Docker Engine and Compose are available and the
VPS has enough capacity. Never share secret values or output of
`docker inspect`/`docker compose config` containing credentials.

## Configuration gate (operator-only, separate approval)

1. Provision a **new isolated staging database** and a non-owner runtime
   role. Do **not** reuse `nexus-ai-automation-prod-postgres-1`, its
   `DATABASE_URL`, or its credentials.
2. Apply `alembic upgrade head` with a separate staging migration owner
   identity *only* after schema/change review. Do not give DDL privileges
   to the API runtime role.
3. Provision and independently verify staging OIDC/JWKS and OPA decision
   service endpoints accessible from the **new container network**.
4. Create a root-owned staging env file outside the repository. For example,
   `sudo install -m 0600 -o root -g root ops/staging/staging.env.example /etc/support-tickets/staging.env`
   (the directory must first exist). Replace ALL placeholders using a
   root-only editor. This is an example, not a request to do so now.
5. Inspect grants, TLS and service dependencies. Keep all sensitive
   credentials in the protected file or an approved secrets manager.
   Never commit staging.env or put secrets into Actions variables.

The example file is unusable as-is by design.

## Candidate operator procedure (NOT executed by this PR)

Only after explicit VPS/container startup approval:

```bash
# Preview service names without revealing rendered secrets
sudo env SUPPORT_STAGING_ENV_FILE=/etc/support-tickets/staging.env \
  docker compose -f ops/staging/compose.yaml config --services

# Separately approved build/start (not part of this PR):
sudo env SUPPORT_STAGING_ENV_FILE=/etc/support-tickets/staging.env \
  docker compose -f ops/staging/compose.yaml build
sudo env SUPPORT_STAGING_ENV_FILE=/etc/support-tickets/staging.env \
  docker compose -f ops/staging/compose.yaml up -d

# Local-only observation. No authorization implied.
curl --fail-with-body --connect-timeout 2 --max-time 5 \
  http://127.0.0.1:18080/health/live
curl -i --connect-timeout 2 --max-time 5 \
  http://127.0.0.1:18080/health/ready
```

Expected liveness (only if running): HTTP 200 with `{"status":"live"}`.
Readiness should be HTTP 200 with `{"status":"database-ready",
"production_authorized":"false"}` only with a configured working
staging database. A 503 readiness is a **blocked gate**, not a reason
to bypass database or identity checks.

Rollback (operator-approved): stop only this Compose project, not any
`nexus-ai-automation-prod-*` service. Do not run `down -v` or delete
databases/volumes:

```bash
sudo env SUPPORT_STAGING_ENV_FILE=/etc/support-tickets/staging.env \
  docker compose -f ops/staging/compose.yaml stop support-api
```

## Connectivity semantics

- `SUPPORT_API_BASE_URL=http://127.0.0.1:18080` only works for a
  **consumer on the same host network namespace** (for instance a
  host-based process on the VPS).
- GitHub-hosted runners use their own `127.0.0.1` and cannot reach the
  VPS through this value.
- `jadel-chatbot-production` is in a container: its localhost refers
  to **that container**, not the VPS host. Do not modify its networking
  or share Docker networks without a reviewed integration and authorization.
- Keep the service private; a public HTTPS reverse proxy is a separate
  security and deployment decision.

## Release gates

Require PR/CI checks at exact SHA, review of API authorization and
network boundaries, staging identity/policy/database verification,
resource-capacity approval, and separate VPS startup authorization.
No GitHub secret, merger, production deploy, paid service, live financial
action, or public ingress is authorized by this proposal.
