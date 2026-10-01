from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

ALLOWED_ROLES = {
    "CUSTOMER",
    "SUPPORT_AGENT",
    "SUPERVISOR",
    "ADMIN",
    "SYSTEM_WORKER",
}

OIDC_ALGORITHMS = ["RS256", "ES256"]


@dataclass(frozen=True)
class OIDCIdentity:
    tenant_id: UUID
    external_subject: str
    role: str


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name}_REQUIRED",
        )
    return value


def _validate_oidc_url(name: str, value: str, environment: str) -> None:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name}_INVALID",
        )
    if environment == "production" and parsed.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name}_HTTPS_REQUIRED",
        )


def _leeway_seconds() -> int:
    raw = os.environ.get("SUPPORT_OIDC_LEEWAY_SECONDS", "30")
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPPORT_OIDC_LEEWAY_SECONDS_INVALID",
        ) from exc
    if not 0 <= value <= 300:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPPORT_OIDC_LEEWAY_SECONDS_INVALID",
        )
    return value


@lru_cache(maxsize=16)
def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def verify_bearer_token(token: str) -> OIDCIdentity:
    environment = os.environ.get("SUPPORT_ENV", "dev")
    issuer = _required_env("SUPPORT_OIDC_ISSUER")
    audience = _required_env("SUPPORT_OIDC_AUDIENCE")
    jwks_url = _required_env("SUPPORT_OIDC_JWKS_URL")
    _validate_oidc_url("SUPPORT_OIDC_ISSUER", issuer, environment)
    _validate_oidc_url("SUPPORT_OIDC_JWKS_URL", jwks_url, environment)

    try:
        signing_key = _get_jwk_client(jwks_url).get_signing_key_from_jwt(token)
    except PyJWKClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC_JWKS_UNAVAILABLE",
        ) from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=OIDC_ALGORITHMS,
            audience=audience,
            issuer=issuer,
            leeway=_leeway_seconds(),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_ACCESS_TOKEN",
        ) from exc

    tenant_claim = os.environ.get("SUPPORT_OIDC_TENANT_CLAIM", "tenant_id")
    role_claim = os.environ.get("SUPPORT_OIDC_ROLE_CLAIM", "support_role")

    subject = claims.get("sub")
    tenant_value = claims.get(tenant_claim)
    role = claims.get(role_claim)

    if not isinstance(subject, str) or not subject or len(subject) > 512:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_IDENTITY_CLAIMS",
        )
    if not isinstance(tenant_value, str) or not isinstance(role, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_IDENTITY_CLAIMS",
        )
    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_IDENTITY_CLAIMS",
        )

    try:
        tenant_id = UUID(tenant_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_IDENTITY_CLAIMS",
        ) from exc

    return OIDCIdentity(
        tenant_id=tenant_id,
        external_subject=subject,
        role=role,
    )
