# Identity and authorization contract

Status: IMPLEMENTED IN CODE / NOT DEPLOYED / NOT PRODUCTION AUTHORIZED.

This contract defines the production authentication and authorization boundary for
`PRJ-SUPPORT-001`. It does not provision an identity provider, OPA service, network
route, secret, or production deployment.

## Production authentication

Production requires:

- `SUPPORT_AUTH_MODE=oidc`
- `SUPPORT_OIDC_ISSUER`
- `SUPPORT_OIDC_AUDIENCE`
- `SUPPORT_OIDC_JWKS_URL`
- optional `SUPPORT_OIDC_TENANT_CLAIM` (default: `tenant_id`)
- optional `SUPPORT_OIDC_ROLE_CLAIM` (default: `support_role`)
- optional `SUPPORT_OIDC_LEEWAY_SECONDS` (default: 30, maximum: 300)

The issuer and JWKS URL must use HTTPS in production. Accepted signing algorithms are
`RS256` and `ES256`. Tokens must contain `exp`, `iat`, `iss`, `aud`, and
`sub`. Missing, expired, incorrectly signed, wrong-issuer, wrong-audience, malformed,
or unsupported-role tokens fail closed.

OIDC does not directly grant the internal user id. The verified token's `sub`,
tenant claim and role claim must match a durable row in `users` under the same
PostgreSQL tenant RLS context. A missing binding, cross-tenant subject, or role mismatch
is denied.

`test-header` authentication is permitted only when `SUPPORT_ENV != production`.

## Production authorization

Production requires:

- `SUPPORT_POLICY_MODE=opa`
- `SUPPORT_OPA_DECISION_URL`
- optional `SUPPORT_OPA_TIMEOUT_SECONDS` (default: 2, range: 0.1-10)

The API sends OPA a structured input containing the verified actor, action and typed
resource. Only an explicit JSON boolean `{"result": true}` grants authorization.
Explicit false returns deny. Network failures, timeouts, malformed responses, missing
configuration and unknown decisions fail closed.

The canonical decision path for the included policy is:

`/v1/data/support/authz/allow`

The included Rego policy is deny-by-default. In this increment only
`SUPPORT_AGENT`, `SUPERVISOR`, and `ADMIN` may perform `ticket:create` or
`ticket:read`. `CUSTOMER` remains denied until a durable customer-to-identity
ownership binding exists. `SYSTEM_WORKER` is also denied these interactive actions.

`test-local` policy is permitted only when `SUPPORT_ENV != production`.

## Non-authorities

None of the following grants access:

- model or agent output;
- request headers outside the explicit non-production test mode;
- browser state;
- health checks;
- possession of a tenant UUID;
- a role claim without a durable tenant user binding;
- an OPA response that is absent, malformed or non-boolean.

## Deployment gate

No IdP issuer, audience, JWKS endpoint, OPA endpoint, credential, secret or production
network route is configured by this change. Those are separate human gates.

`PRODUCTION_AUTHORIZED=false` remains unchanged.
