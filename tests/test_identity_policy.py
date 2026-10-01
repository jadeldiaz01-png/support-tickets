from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

import policy.authorizer as authorizer
import security.oidc as oidc
from security.context import ActorContext


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()


class StaticJWKClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        assert token
        return SimpleNamespace(key=PUBLIC_KEY)


class FakeOPAResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeOPAResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amount: int) -> bytes:
        assert amount == authorizer.MAX_OPA_RESPONSE_BYTES + 1
        return self.payload


def _oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "oidc")
    monkeypatch.setenv("SUPPORT_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("SUPPORT_OIDC_AUDIENCE", "support-api")
    monkeypatch.setenv("SUPPORT_OIDC_JWKS_URL", "https://issuer.example/jwks")
    monkeypatch.setenv("SUPPORT_OIDC_TENANT_CLAIM", "tenant_id")
    monkeypatch.setenv("SUPPORT_OIDC_ROLE_CLAIM", "support_role")
    monkeypatch.setattr(oidc, "_get_jwk_client", lambda _: StaticJWKClient())


def _token(*, audience: str = "support-api", role: str = "SUPPORT_AGENT") -> tuple[str, str]:
    tenant_id = str(uuid4())
    now = datetime.now(timezone.utc)
    encoded = jwt.encode(
        {
            "iss": "https://issuer.example",
            "aud": audience,
            "sub": "external-user-123",
            "iat": now - timedelta(seconds=5),
            "exp": now + timedelta(minutes=5),
            "tenant_id": tenant_id,
            "support_role": role,
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    return encoded, tenant_id


def test_oidc_verifies_signature_issuer_audience_and_claim_contract(monkeypatch) -> None:
    _oidc_env(monkeypatch)
    token, tenant_id = _token()

    identity = oidc.verify_bearer_token(token)

    assert str(identity.tenant_id) == tenant_id
    assert identity.external_subject == "external-user-123"
    assert identity.role == "SUPPORT_AGENT"


def test_oidc_rejects_wrong_audience(monkeypatch) -> None:
    _oidc_env(monkeypatch)
    token, _ = _token(audience="wrong-audience")

    with pytest.raises(HTTPException) as caught:
        oidc.verify_bearer_token(token)

    assert caught.value.status_code == 401
    assert caught.value.detail == "INVALID_ACCESS_TOKEN"


def test_oidc_rejects_unrecognized_role(monkeypatch) -> None:
    _oidc_env(monkeypatch)
    token, _ = _token(role="ROOT")

    with pytest.raises(HTTPException) as caught:
        oidc.verify_bearer_token(token)

    assert caught.value.status_code == 401
    assert caught.value.detail == "INVALID_IDENTITY_CLAIMS"


def test_production_oidc_requires_https_for_issuer_and_jwks(monkeypatch) -> None:
    _oidc_env(monkeypatch)
    monkeypatch.setenv("SUPPORT_OIDC_ISSUER", "http://issuer.example")
    token, _ = _token()

    with pytest.raises(HTTPException) as caught:
        oidc.verify_bearer_token(token)

    assert caught.value.status_code == 503
    assert caught.value.detail == "SUPPORT_OIDC_ISSUER_HTTPS_REQUIRED"


def test_opa_allow_contract(monkeypatch) -> None:
    actor = ActorContext(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        role="SUPPORT_AGENT",
        external_subject="user-a",
    )
    captured: dict[str, object] = {}

    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "opa")
    monkeypatch.setenv(
        "SUPPORT_OPA_DECISION_URL",
        "http://127.0.0.1:8181/v1/data/support/authz/allow",
    )

    def fake_urlopen(request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data)
        return FakeOPAResponse(b'{"result":true}')

    monkeypatch.setattr(authorizer, "urlopen", fake_urlopen)

    authorizer.authorize(
        actor,
        "ticket:read",
        resource={"type": "ticket", "ticket_id": str(uuid4())},
    )

    assert captured["url"] == (
        "http://127.0.0.1:8181/v1/data/support/authz/allow"
    )
    assert captured["timeout"] == 2.0
    assert captured["body"]["input"]["actor"]["tenant_id"] == str(actor.tenant_id)
    assert captured["body"]["input"]["action"] == "ticket:read"


def test_opa_explicit_deny_is_403(monkeypatch) -> None:
    actor = ActorContext(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        role="SUPPORT_AGENT",
        external_subject="user-a",
    )
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "opa")
    monkeypatch.setenv(
        "SUPPORT_OPA_DECISION_URL",
        "http://127.0.0.1:8181/v1/data/support/authz/allow",
    )
    monkeypatch.setattr(
        authorizer,
        "urlopen",
        lambda request, timeout: FakeOPAResponse(b'{"result":false}'),
    )

    with pytest.raises(HTTPException) as caught:
        authorizer.authorize(actor, "ticket:create", resource={"type": "ticket"})

    assert caught.value.status_code == 403
    assert caught.value.detail == "POLICY_DENY"


def test_opa_malformed_response_fails_closed(monkeypatch) -> None:
    actor = ActorContext(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        role="SUPPORT_AGENT",
        external_subject="user-a",
    )
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "opa")
    monkeypatch.setenv(
        "SUPPORT_OPA_DECISION_URL",
        "http://127.0.0.1:8181/v1/data/support/authz/allow",
    )
    monkeypatch.setattr(
        authorizer,
        "urlopen",
        lambda request, timeout: FakeOPAResponse(b'{"unexpected":true}'),
    )

    with pytest.raises(HTTPException) as caught:
        authorizer.authorize(actor, "ticket:create", resource={"type": "ticket"})

    assert caught.value.status_code == 503
    assert caught.value.detail == "POLICY_ENGINE_INVALID_RESPONSE"


def test_production_cannot_use_test_local_policy(monkeypatch) -> None:
    actor = ActorContext(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        role="SUPPORT_AGENT",
        external_subject="user-a",
    )
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")

    with pytest.raises(HTTPException) as caught:
        authorizer.authorize(actor, "ticket:create", resource={"type": "ticket"})

    assert caught.value.status_code == 503
    assert caught.value.detail == "POLICY_ENGINE_NOT_CONFIGURED"
