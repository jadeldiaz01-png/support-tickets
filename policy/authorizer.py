from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from security.context import ActorContext

INTERNAL_TICKET_ROLES = {"SUPPORT_AGENT", "SUPERVISOR", "ADMIN"}
MAX_OPA_RESPONSE_BYTES = 1024 * 1024


def _local_allowed(actor: ActorContext, action: str) -> bool:
    return (
        action in {"ticket:create", "ticket:read"}
        and actor.role in INTERNAL_TICKET_ROLES
    )


def _opa_timeout() -> float:
    raw = os.environ.get("SUPPORT_OPA_TIMEOUT_SECONDS", "2")
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPPORT_OPA_TIMEOUT_SECONDS_INVALID",
        ) from exc
    if not 0.1 <= timeout <= 10:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPPORT_OPA_TIMEOUT_SECONDS_INVALID",
        )
    return timeout


def _opa_url() -> str:
    value = os.environ.get("SUPPORT_OPA_DECISION_URL", "").strip()
    parsed = urlparse(value)
    if not value or not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPPORT_OPA_DECISION_URL_INVALID",
        )
    return value


def _authorize_with_opa(
    actor: ActorContext,
    action: str,
    resource: dict[str, str],
) -> None:
    payload = json.dumps(
        {
            "input": {
                "actor": {
                    "tenant_id": str(actor.tenant_id),
                    "actor_id": str(actor.actor_id),
                    "external_subject": actor.external_subject,
                    "role": actor.role,
                },
                "action": action,
                "resource": resource,
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")

    request = Request(
        _opa_url(),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=_opa_timeout()) as response:
            raw = response.read(MAX_OPA_RESPONSE_BYTES + 1)
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="POLICY_ENGINE_UNAVAILABLE",
        ) from exc

    if len(raw) > MAX_OPA_RESPONSE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="POLICY_ENGINE_INVALID_RESPONSE",
        )

    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="POLICY_ENGINE_INVALID_RESPONSE",
        ) from exc

    decision = body.get("result") if isinstance(body, dict) else None
    if decision is True:
        return
    if decision is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="POLICY_DENY",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="POLICY_ENGINE_INVALID_RESPONSE",
    )


def authorize(
    actor: ActorContext,
    action: str,
    *,
    resource: dict[str, str] | None = None,
) -> None:
    environment = os.environ.get("SUPPORT_ENV", "dev")
    mode = os.environ.get("SUPPORT_POLICY_MODE", "deny")
    resource = resource or {}

    if mode == "test-local" and environment != "production":
        if _local_allowed(actor, action):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="POLICY_DENY",
        )

    if mode == "opa":
        _authorize_with_opa(actor, action, resource)
        return

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="POLICY_ENGINE_NOT_CONFIGURED",
    )
