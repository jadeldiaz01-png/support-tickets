"""Guardrails for internal ticket workflow: authorization, scope, and PII-safe metadata."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from security.context import ActorContext
from policy.authorizer import authorize
from fastapi import HTTPException


def _actor(role):
    return ActorContext(
        tenant_id=uuid4(), actor_id=uuid4(),
        role=role, external_subject="test-user",
    )


def test_local_assign_requires_supervisor_or_admin(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    for role in ("SUPPORT_AGENT", "CUSTOMER", "SYSTEM_WORKER"):
        with pytest.raises(HTTPException) as err:
            authorize(_actor(role), "ticket:assign",
                      resource={"type": "ticket", "ticket_id": str(uuid4())})
        assert err.value.status_code == 403
    for role in ("SUPERVISOR", "ADMIN"):
        authorize(_actor(role), "ticket:assign",
                  resource={"type": "ticket", "ticket_id": str(uuid4())})


def test_local_internal_note_does_not_grant_customer_role(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    with pytest.raises(HTTPException) as err:
        authorize(_actor("CUSTOMER"), "ticket:internal_note",
                  resource={"type": "ticket", "ticket_id": str(uuid4())})
    assert err.value.status_code == 403
    authorize(_actor("SUPPORT_AGENT"), "ticket:internal_note",
              resource={"type": "ticket", "ticket_id": str(uuid4())})


def test_invalid_expected_version_rejected_without_writing(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    headers = {
        "X-Tenant-ID": str(uuid4()), "X-Actor-ID": str(uuid4()),
        "X-Role": "SUPERVISOR",
    }
    ticket_id = str(uuid4())
    client = TestClient(app)
    bad_assign = client.patch(
        f"/v1/tickets/{ticket_id}/assignment",
        headers=headers, json={"assignee_user_id": None, "expected_version": 0},
    )
    bad_note = client.post(
        f"/v1/tickets/{ticket_id}/internal-notes",
        headers=headers, json={"body": "Private", "expected_version": -1},
    )
    assert bad_assign.status_code == 422
    assert bad_note.status_code == 422
