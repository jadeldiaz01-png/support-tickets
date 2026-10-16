"""Static fail-closed contract tests for the proposed localhost-only Compose stack."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "ops" / "staging" / "compose.yaml"
EXAMPLE = ROOT / "ops" / "staging" / "staging.env.example"


def test_compose_binds_only_host_loopback() -> None:
    content = COMPOSE.read_text(encoding="utf-8")
    assert re.search(r'^\s+- "127\.0\.0\.1:18080:8000"$', content, re.MULTILINE)
    assert "network_mode: host" not in content
    assert "privileged: true" not in content
    assert "0.0.0.0:18080" not in content
    assert "127.0.0.1:8000:8000" not in content


def test_staging_security_modes_fail_closed() -> None:
    content = COMPOSE.read_text(encoding="utf-8")
    assert "dockerfile: Dockerfile.api" in content
    assert "context: ../.." in content
    assert "SUPPORT_ENV: staging" in content
    assert "SUPPORT_AUTH_MODE: oidc" in content
    assert "SUPPORT_POLICY_MODE: opa" in content
    assert "no-new-privileges:true" in content
    assert "read_only: true" in content
    assert "cap_drop:" in content
    assert "restart: unless-stopped" in content
    assert "required: true" in content
    assert "SUPPORT_STAGING_ENV_FILE:?" in content
    assert "nexus-ai-automation" not in content


def test_template_contains_no_real_credentials() -> None:
    content = EXAMPLE.read_text(encoding="utf-8")
    required = (
        "DATABASE_URL=", "SUPPORT_OIDC_ISSUER=", "SUPPORT_OIDC_AUDIENCE=",
        "SUPPORT_OIDC_JWKS_URL=", "SUPPORT_OPA_DECISION_URL=",
    )
    assert all(token in content for token in required)
    assert "REPLACE_WITH_STAGING_PASSWORD" in content
    assert "example.invalid" in content
    assert "nexus-ai-automation" not in content
