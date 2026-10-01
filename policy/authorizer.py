from __future__ import annotations

import os

from fastapi import HTTPException, status

from security.context import ActorContext

CREATE_ROLES = {"CUSTOMER", "SUPPORT_AGENT", "SUPERVISOR", "ADMIN"}
READ_ROLES = {"CUSTOMER", "SUPPORT_AGENT", "SUPERVISOR", "ADMIN"}


def authorize(actor: ActorContext, action: str) -> None:
    environment = os.environ.get("SUPPORT_ENV", "dev")
    mode = os.environ.get("SUPPORT_POLICY_MODE", "deny")

    if mode != "test-local" or environment == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="POLICY_ENGINE_NOT_CONFIGURED",
        )

    allowed = (
        action == "ticket:create" and actor.role in CREATE_ROLES
    ) or (
        action == "ticket:read" and actor.role in READ_ROLES
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="POLICY_DENY",
        )
