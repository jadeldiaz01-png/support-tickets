from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from repositories.db import bind_tenant, get_engine
from security.oidc import ALLOWED_ROLES, OIDCIdentity, verify_bearer_token


@dataclass(frozen=True)
class ActorContext:
    tenant_id: UUID
    actor_id: UUID
    role: str
    external_subject: str


def _resolve_oidc_actor(identity: OIDCIdentity) -> ActorContext:
    try:
        with Session(get_engine()) as session:
            with session.begin():
                bind_tenant(session, identity.tenant_id)
                row = session.execute(
                    text(
                        """
                        SELECT id, role
                        FROM users
                        WHERE tenant_id = :tenant_id
                          AND external_subject = :external_subject
                        """
                    ),
                    {
                        "tenant_id": identity.tenant_id,
                        "external_subject": identity.external_subject,
                    },
                ).mappings().first()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IDENTITY_DIRECTORY_UNAVAILABLE",
        ) from exc

    if row is None or row["role"] != identity.role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="IDENTITY_NOT_BOUND",
        )

    return ActorContext(
        tenant_id=identity.tenant_id,
        actor_id=row["id"],
        role=row["role"],
        external_subject=identity.external_subject,
    )


def _test_actor(
    *,
    x_tenant_id: str | None,
    x_actor_id: str | None,
    x_role: str | None,
) -> ActorContext:
    if not x_tenant_id or not x_actor_id or x_role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TEST_IDENTITY",
        )

    try:
        actor_id = UUID(x_actor_id)
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TEST_IDENTITY",
        ) from exc

    return ActorContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=x_role,
        external_subject=f"test:{actor_id}",
    )


def get_actor_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> ActorContext:
    environment = os.environ.get("SUPPORT_ENV", "dev")
    auth_mode = os.environ.get("SUPPORT_AUTH_MODE", "disabled")

    if auth_mode == "test-header" and environment != "production":
        return _test_actor(
            x_tenant_id=x_tenant_id,
            x_actor_id=x_actor_id,
            x_role=x_role,
        )

    if auth_mode != "oidc":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_NOT_CONFIGURED",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="BEARER_TOKEN_REQUIRED",
        )

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="BEARER_TOKEN_REQUIRED",
        )

    identity = verify_bearer_token(token.strip())
    return _resolve_oidc_actor(identity)
