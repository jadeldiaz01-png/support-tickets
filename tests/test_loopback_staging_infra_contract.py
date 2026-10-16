"""Static fail-closed checks for the unapplied loopback staging template."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "ops/systemd/jadel-support-api-staging.service"
EXAMPLE = ROOT / "ops/systemd/staging.env.example"


def test_systemd_template_is_loopback_only_and_unprivileged() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 18080" in unit
    assert "api.main:app" in unit
    assert "User=jadel-support" in unit
    assert "Group=jadel-support" in unit
    assert "EnvironmentFile=/etc/jadel-support-api/staging.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
    assert "Restart=on-failure" in unit
    assert "ExecStart=/opt/jadel-support-api/current/.venv/bin/python" in unit
    assert "--host 0.0.0.0" not in unit
    assert "--proxy-headers" not in unit
    assert "DATABASE_URL=" not in unit
    assert "ExecStartPre=/bin/bash" not in unit


def test_staging_example_uses_strict_identity_and_is_not_a_secret() -> None:
    env = EXAMPLE.read_text(encoding="utf-8")
    assert "SUPPORT_ENV=production" in env
    assert "SUPPORT_AUTH_MODE=oidc" in env
    assert "SUPPORT_POLICY_MODE=opa" in env
    assert "SUPPORT_OIDC_ISSUER=https://" in env
    assert "SUPPORT_OIDC_JWKS_URL=https://" in env
    assert "REPLACE_STAGING_ROLE" in env
    assert "REPLACE_PASSWORD" in env
    assert "nexus-ai-automation-prod-postgres-1" not in [
        line.split("=", 1)[-1] for line in env.splitlines()
        if line.startswith("DATABASE_URL=")
    ]


def test_runbook_requires_human_gate_and_avoids_live_fleet() -> None:
    runbook = (ROOT / "docs/runbooks/SUPPORT_API_LOOPBACK_STAGING.md").read_text(
        encoding="utf-8"
    )
    assert "PRODUCTION_AUTHORIZED=false" in runbook
    assert "HUMAN RELEASE GATE" in runbook
    assert "does **not** test OIDC, OPA" in runbook
    assert "Do not open port 18080 publicly" in runbook
