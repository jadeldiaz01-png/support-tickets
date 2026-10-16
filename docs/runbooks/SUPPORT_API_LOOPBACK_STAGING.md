# Support API: loopback-only staging on 127.0.0.1:18080

Status: **TEMPLATE ONLY / NOT DEPLOYED / PRODUCTION_AUTHORIZED=false**.
This change adds a proposed `systemd` unit and example environment file. It does
**not** alter the VPS, PostgreSQL, firewall, Docker, systemd state, routing,
GitHub secrets or customer-facing deployments.

## Scope and existing host constraints

Known host observations (user-provided; recheck on-site before any installation):
- Port `127.0.0.1:8000` is already bound by a Docker proxy for
  `nexus-ai-automation-prod-api-1`. Do not change or stop it.
- `127.0.0.1:8787` is the existing private gateway. Do not change or stop it.
- `jadel-chatbot-production` is published on host loopback port `18501`.
- The existing `nexus-ai-automation-prod-postgres-1` is a **production**
  PostgreSQL container, not an approved staging database.
- `uvicorn api.main:app --host 127.0.0.1 --port 18080` started successfully
  when tested interactively, but was stopped with Ctrl+C. A subsequent
  curl failure occurred because it had already exited.

## Trust and network boundary

`SUPPORT_API_BASE_URL=http://127.0.0.1:18080` is valid only for a client
in the *same host network namespace* as the server. `127.0.0.1` inside
another Docker container or a GitHub-hosted runner points to that
container/runner itself, **not** to the VPS.

Do not open port 18080 publicly, publish a Docker port, or create a reverse
proxy route until a separate reviewed authorization. For a future bot/container
integration choose an explicitly authorized Docker network, tightly scoped
reverse proxy or private tunnel and retest authentication and source
restrictions. No such network changes are included.

## Preconditions for a separately approved staging installation

1. Obtain explicit approval identifying VPS, source commit SHA, isolated
   staging database, account names, permissible network connections and
   installation action. No production deployment authority is implied.
2. Audit the host read-only:

   ```sh
   sudo ss -ltnp | grep -E ':(8000|8787|18080|18501)([^0-9]|$)' || true
   sudo docker ps --format '{{.Names}} {{.Ports}}'
   sudo systemctl list-unit-files '*support*' --no-pager
   df -h /opt /var
   free -h
   ```

   Do not proceed if port 18080 is occupied or any resource/identity clashes.
3. Provision an **isolated staging PostgreSQL** database with dedicated
   runtime and migration roles and tested RLS. Existing production database
   and its secrets must not be reused. Migrations must be applied separately
   by the privileged migration identity after review; the running API uses a
   least-privilege runtime DSN.
4. Provision a real staging OIDC issuer/JWKS and OPA policy service, exercise
   fail-closed decisions and negative cross-tenant tests. `SUPPORT_ENV=production`
   is intentional to block unsafe test-header auth even in staging. Real
   certificates/HTTPS are required by the OIDC code.
5. Store runtime secrets outside Git in a root-controlled file or approved
   secret manager; audit filesystem and process environment exposure.

## Proposed installation sequence (NOT executed)

For an approved change window only:

```sh
# Select one reviewed, immutable source revision before provisioning.
git -C ~/support-tickets rev-parse HEAD
# Prepare a dedicated, non-login account. Run only if not already present.
sudo useradd --system --no-create-home --shell /usr/sbin/nologin jadel-support
sudo install -d -o root -g jadel-support -m 0750 /opt/jadel-support-api
sudo install -d -o root -g jadel-support -m 0750 /opt/jadel-support-api/current
sudo install -d -o root -g jadel-support -m 0750 /etc/jadel-support-api
```

Deploy the exact reviewed source to `/opt/jadel-support-api/current` (never
use the live `~/support-tickets/.venv` or hot-edit a release). Build the
virtual environment at `/opt/jadel-support-api/current/.venv` with
`python3 -m venv` and install `requirements-api.txt` from that revision.
An administrator must ensure all paths in the installation are readable by
`jadel-support` but not writable by that user, and validate dependency
artifacts before any start.

Copy `ops/systemd/staging.env.example` to
`/etc/jadel-support-api/staging.env`; replace **all** placeholders with
approved, dedicated staging values. Restrict the file to root and the
`jadel-support` group with mode `0640`. It must **never** be committed.
Review the implications of putting credentials into systemd environment
variables; use credential files/injection if the target runtime is adapted
to support them.

Only after independent review and separate explicit approval:

```sh
sudo install -o root -g root -m 0644 \
  ops/systemd/jadel-support-api-staging.service \
  /etc/systemd/system/jadel-support-api-staging.service
sudo systemd-analyze verify /etc/systemd/system/jadel-support-api-staging.service
sudo systemctl daemon-reload
# HUMAN RELEASE GATE: no start/enable command is part of this template.
```

At the release gate, a human operator can separately authorize the actions
needed to start and enable the service. This document does not perform them.

## Read-only verification after an authorized start

```sh
sudo systemctl status jadel-support-api-staging --no-pager
sudo ss -ltnp | grep ':18080'
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:18080/health/live
curl --silent --show-error -i \
  http://127.0.0.1:18080/health/ready
sudo journalctl -u jadel-support-api-staging -n 50 --no-pager
```

Expected liveness response is `{"status":"live"}`. Readiness reports
`database-ready` only after a working database connection. **It does not
test OIDC, OPA, backups, tenant isolation, or external authorization.**
A 200 liveness response is **not** production certification.

Test an unauthenticated `POST /v1/tickets` with an isolated fixture and
confirm it is denied; execute tenant/OPA tests in a separate staging test
harness, without customer PII. Reproduce test, migrations, restoration, and
independent release review on the exact source SHA.

## Rollback and boundaries

Keep the previous reviewed release intact; revert only the dedicated
staging unit and source at an explicitly authorized rollback gate. Never
restart `nexus-ai-automation-prod-*`, `private-gateway` or
`jadel-chatbot-production` as part of this service. Do not share their
credentials, PostgreSQL instance, network bindings, or ports.

The systemd service starts Uvicorn with one worker and loopback binding.
The release remains `NOT_PRODUCTION_AUTHORIZED` until identity, policy,
DB, observability, backup/restore, CI and human approval gates are proven.
