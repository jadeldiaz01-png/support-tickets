# Automated risk validation (no compulsory independent reviewer)

This repository proposes an automated gate for every pull request:
- LOW (documentation and ordinary text): automated gate + existing CI.
- MEDIUM (ordinary program code): automated gate + existing CI.
- HIGH (workflows, permissions, security, production, deployment, payments,
  trading execution, licensing, migrations, dependency locks): automated gate
  and **explicit owner authorization tied to the exact PR HEAD commit SHA**.

High-risk authorization is provided by the repository administrator through
**Settings > Secrets and variables > Actions > Variables**. Set
`RISK_APPROVED_SHA` to the full 40-character SHA of the inspected PR HEAD,
then rerun the failed `automated-risk` check. Clear or replace the variable
after the decision. A new commit revokes approval automatically.

A PASS **does not grant** deployment, payment activation, data-licensing,
trading authorization, API write permissions, or financial execution.
Existing human authorization for critical effects remains separate.
In particular, production deployments and LIVE financial operations
are not permitted by this check.

This check runs with `contents: read`, no deployment credentials,
no external dependencies, no self-hosted runner, and no unpinned GitHub
Actions. It writes an audit summary and has reproducible regression tests.

## Enforcement prerequisites

A workflow file alone **does not make a required branch-protection check**.
After a controlled pilot and green CI, an administrator should add the
`automated-risk` status context to the default-branch ruleset, alongside
existing required build, test and security checks. Do not remove existing
required checks. If the repository requires human PR approvals generally,
lower required approving reviews to 0 and turn off mandatory CODEOWNER
review **only after** the automated checks are verified and configured
as required. Preserve PR-only changes, deletion protection, non-fast-forward
protection, and resolved-conversation requirements.

For repositories where GitHub Free does not expose ruleset settings,
retain current protections; do not simulate enforcement. This file
documents proposed governance until the corresponding ruleset is updated.
