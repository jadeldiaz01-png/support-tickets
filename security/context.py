from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, HTTPException, status

ALLOWED_ROLES = {
    "CUSTOMER",
    "SUPPORT_AGENT",
    "SUPERVISOR",
    "ADMIN",
    "SYSTEM_WORKER",
}


@dataclass(frozen=True)
class ActorContext:
    tenant_id: UUID
    actor_id: UUID
    role: str


def get_actor_context(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> ActorContext:
    environment = os.environ.get("SUPPORT_ENV", "dev")
    auth_mode = os.environ.get("SUPPORT_AUTH_MODE", "disabled")

    if auth_mode != "test-header" or environment == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_NOT_CONFIGURED",
        )

    if not x_tenant_id or not x_actor_id or x_role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TEST_IDENTITY",
        )

    try:
        return ActorContext(
            tenant_id=UUID(x_tenant_id),
            actor_id=UUID(x_actor_id),
            role=x_role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TEST_IDENTITY",
        ) from exc
