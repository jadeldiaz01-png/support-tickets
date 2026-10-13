#!/usr/bin/env bash
# G6 reviewer helper — run locally ONLY against a disposable isolated DB.
# Never downloads source or uses production credentials by itself.
set -euo pipefail
EXPECTED_SHA="REPLACE_WITH_G6_EXACT_HEAD"
if [[ "${G6_DISPOSABLE_TEST_ONLY:-}" != "YES" ]]; then
  echo 'G6_GATE=BLOCKED: explicit disposable test flag required' >&2; exit 2
fi
if [[ "${SUPPORT_ENV:-}" != "test" ]]; then
  echo 'G6_GATE=BLOCKED: SUPPORT_ENV must be test' >&2; exit 2
fi
actual="$(git rev-parse HEAD)"
if [[ "$actual" != "$EXPECTED_SHA" ]]; then
  echo "G6_GATE=BLOCKED: checked-out HEAD differs from reviewed SHA" >&2; exit 3
fi
python3 - <<'PY'
import os
from sqlalchemy.engine.url import make_url
for variable, user in [("DATABASE_URL_OWNER", "postgres"), ("DATABASE_URL", "support_runtime")]:
    value = os.environ.get(variable)
    if not value:
        raise SystemExit("G6_GATE=BLOCKED: missing isolated database credentials")
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1"} or url.username != user or url.database != "support":
        raise SystemExit("G6_GATE=BLOCKED: database endpoint/identity rejected")
print("G6_REVIEW_DB_SHAPE=DISPOSABLE_CANDIDATE (verify localhost is not a production tunnel)")
PY
echo "G6_REVIEW_HEAD=$actual"
python3 --version
python3 -m compileall -q api application repositories security migrations tests
python3 -m ruff check --select E9,F63,F7,F82 api application repositories security tests
python3 -m pytest -q tests/test_g6_tenant_fks.py tests/test_g5_permissions_and_catalog.py
echo 'G6_REVIEW_SUITE=PASS (reviewer must independently attest)'
