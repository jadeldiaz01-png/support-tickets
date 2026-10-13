#!/usr/bin/env bash
# G6.1: exact immutable reviewer checkout; NO credentials or production DB.
# Reviewer must personally verify that the localhost DB is disposable.
set -euo pipefail
EXPECTED="${G61_EXPECTED_SHA:-}"
if [[ ! "$EXPECTED" =~ ^[a-f0-9]{40}$ ]]; then
  echo "G61_BLOCKED=invalid expected SHA" >&2; exit 2
fi
command -v git >/dev/null || { echo "G61_BLOCKED=git unavailable" >&2; exit 3; }
if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]]; then
  echo "G61_BLOCKED=not git checkout" >&2; exit 3
fi
actual="$(git rev-parse HEAD)"
if [[ "$actual" != "$EXPECTED" ]]; then
  echo "G61_BLOCKED=wrong HEAD: $actual" >&2; exit 3
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "G61_BLOCKED=tracked source files modified" >&2; exit 3
fi
git cat-file -e "$actual^{commit}"
git fsck --no-reflogs --connectivity-only >/dev/null
echo "G61_VERIFIED_COMMIT=$actual"
echo "G61_SOURCE_TREE=$(git rev-parse HEAD^{tree})"
echo "G61_REVIEW_REQUIRED=personally inspect SQL role and DB isolation"
exec env G6_EXPECTED_SHA="$EXPECTED" \
  G6_DISPOSABLE_TEST_ONLY="${G6_DISPOSABLE_TEST_ONLY:-}" \
  SUPPORT_ENV="${SUPPORT_ENV:-}" \
  bash ops/g6_reviewer_reproduce.sh
