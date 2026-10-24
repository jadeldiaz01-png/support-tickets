# Risk-tiered validation for Codex PRs

Automated risk classification supplements existing review and CI; it does not
replace the required human/CODEOWNER review during bootstrap or by itself
authorize removal of that review.

## Classification and effects
- **LOW:** documentation and ordinary prose; automated validation plus existing CI.
- **MEDIUM:** ordinary code; automated validation plus existing CI.
- **HIGH:** workflows, security/policy changes, dependencies, licensing,
  financial execution, production deployments, credentials, migrations, etc.
  Requires explicit authorization matching the exact PR HEAD SHA.
- No classification grants trading LIVE, PayPal LIVE, production deployment,
  real-money execution, spending, external side effects, or permission to use data.
  Those operations require separate manual authorization.

## Trusted enforcement, not self-approval
`.github/workflows/automated-risk.yml` tests the PR version and provides
advisory feedback. PR code can edit that version, so **do not** use its
`automated-risk` status as the sole required branch-protection check.

`.github/workflows/automated-risk-trusted.yml` is designed to run on
`pull_request_target`, check out only the protected default branch, and inspect
untrusted PR file metadata through GitHub's read-only API. It must never check
out or execute PR code. It should fail closed on API errors, HEAD races,
excessive change sets, and missing exact-SHA approval for HIGH risk.

The required ruleset status context should be `automated-risk-trusted`, but
this check cannot be relied upon until the workflow is present on the protected
default branch, has run successfully, and is confirmed as a required status
check in the repository's effective ruleset.

## High-risk authorization
The repository owner must inspect the actual changes, tests, and full 40-character
PR HEAD SHA. The repository variable `RISK_APPROVED_SHA` must match that exact
SHA for HIGH-risk changes. Any subsequent commit invalidates the authorization.
Clear or replace the variable after the decision. This variable is not permission
to deploy, trade, spend, or cause external effects.

## Two-stage safe rollout — mandatory protections stay enabled
1. Bootstrap this workflow under the repository's **current** protections.
   Keep the required approval and CODEOWNER review; retain all existing build,
   security, and regression checks.
2. Before treating the trusted check as enforcement, verify that it runs from
   the protected default branch, does not execute PR code, and blocks a
   deliberately missing or stale HIGH-risk authorization.
3. A repository administrator must inspect and record the effective branch
   protection/ruleset configuration and confirm `automated-risk-trusted` is
   actually required alongside existing checks.
4. **Do not remove mandatory approvals or CODEOWNER reviews as part of this PR
   or as an automatic follow-up.** Any later proposal to reduce human reviews
   requires a separate, explicitly approved governance change and evidence that
   the trusted control is enforced and that residual risks are accepted.

## Limits
This workflow uses read-only permissions and a GitHub-hosted runner. Available
Actions minutes and private-repository ruleset features depend on the plan.
Path-based classification has blind spots and is not a substitute for code
security scans, licensing review, independent governance decisions, or
operational approvals. CI success alone is not proof that branch protections
are configured correctly.
