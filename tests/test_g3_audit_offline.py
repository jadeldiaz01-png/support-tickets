"""G3 H-01..H-09 independent-readiness negative checks (offline).

These tests do not impersonate the human reviewer and never contact customers.
All results refer only to the checked-out revision, not real IdP/OPA availability.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from policy.authorizer import authorize
from security.context import ActorContext


def actor(role="SUPERVISOR"):
    return ActorContext(
        tenant_id=uuid4(), actor_id=uuid4(),
        role=role, external_subject="offline-test-subject",
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/v1/tickets/11111111-1111-1111-1111-111111111111/assignment",
         {"assignee_user_id": None, "expected_version": 1}),
        ("POST", "/v1/tickets/11111111-1111-1111-1111-111111111111/internal-notes",
         {"body": "CONFIDENTIAL_TEST_MARKER", "expected_version": 1}),
    ],
)
def test_h07_production_header_spoof_and_disabled_auth_fail_closed(
    monkeypatch, method, path, body,
):
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_AUTH_MODE", "test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    response = TestClient(app).request(
        method, path, json=body,
        headers={
            "X-Role": "ADMIN",
            "X-Tenant-ID": str(uuid4()),
            "X-Actor-ID": str(uuid4()),
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_NOT_CONFIGURED"
    assert "CONFIDENTIAL_TEST_MARKER" not in response.text


@pytest.mark.parametrize("action", ["ticket:assign", "ticket:internal_note"])
def test_h07_missing_policy_configuration_fails_closed(monkeypatch, action):
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "deny")
    with pytest.raises(HTTPException) as exc:
        authorize(actor(), action,
                  resource={"type": "ticket", "ticket_id": str(uuid4())})
    assert exc.value.status_code == 503


@pytest.mark.parametrize("action", ["ticket:assign", "ticket:internal_note"])
def test_h07_malformed_policy_endpoint_fails_closed(monkeypatch, action):
    monkeypatch.setenv("SUPPORT_ENV", "production")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "opa")
    monkeypatch.setenv("SUPPORT_OPA_DECISION_URL", "")
    with pytest.raises(HTTPException) as exc:
        authorize(actor(), action,
                  resource={"type": "ticket", "ticket_id": str(uuid4())})
    assert exc.value.status_code == 503
    assert exc.value.detail == "SUPPORT_OPA_DECISION_URL_INVALID"


@pytest.mark.parametrize(
    "role,action",
    [
        ("SUPPORT_AGENT", "ticket:assign"),
        ("CUSTOMER", "ticket:assign"),
        ("SYSTEM_WORKER", "ticket:assign"),
        ("CUSTOMER", "ticket:internal_note"),
        ("SYSTEM_WORKER", "ticket:internal_note"),
    ],
)
def test_h02_h07_prohibited_roles_denied(monkeypatch, role, action):
    monkeypatch.setenv("SUPPORT_ENV", "test")
    monkeypatch.setenv("SUPPORT_POLICY_MODE", "test-local")
    with pytest.raises(HTTPException) as exc:
        authorize(actor(role), action,
                  resource={"type": "ticket", "ticket_id": str(uuid4())})
    assert exc.value.status_code == 403


def test_h03_internal_note_schema_excludes_untrusted_fields():
    from pydantic import ValidationError
    from api.schemas import TicketInternalNoteCreate, TicketInternalNoteResult

    with pytest.raises(ValidationError):
        TicketInternalNoteCreate.model_validate({
            "body": "PRIVATE_SENTINEL", "expected_version": 1,
            "broadcast_to_customers": True,
        })
    with pytest.raises(ValidationError):
        TicketInternalNoteResult.model_validate({
            "ticket_id": str(uuid4()), "message_id": str(uuid4()),
            "version": 2, "body": "PRIVATE_SENTINEL",
        })


def test_h08_no_external_delivery_api_defined_for_g3():
    paths = {item.path for item in app.routes}
    assert "/v1/tickets/{ticket_id}/reply" not in paths
    assert "/v1/tickets/{ticket_id}/send" not in paths
