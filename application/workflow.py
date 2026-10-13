"""Internal, tenant-scoped ticket workflow. No outward delivery or AI actions.

All writes are transactionally versioned and recorded in ticket_events/audit_events.
Assignment and internal-note events deliberately do NOT enqueue external outbox
messages; customer-visible sends require separate explicit approval and tooling.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from repositories.db import bind_tenant
from security.context import ActorContext


class InternalWorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _lock_ticket(self, actor: ActorContext, ticket_id: UUID, expected_version: int):
        ticket = self.session.execute(
            text("""
                SELECT id, status, version FROM tickets
                WHERE id = :ticket_id AND tenant_id = :tenant_id
                FOR UPDATE
            """),
            {"ticket_id": ticket_id, "tenant_id": actor.tenant_id},
        ).mappings().first()
        if ticket is None:
            raise HTTPException(status_code=404, detail="TICKET_NOT_FOUND")
        if ticket["version"] != expected_version:
            raise HTTPException(status_code=409, detail="TICKET_VERSION_CONFLICT")
        return ticket

    def _advance_ticket(self, actor: ActorContext, ticket_id: UUID, version: int) -> int:
        return self.session.execute(
            text("""
                UPDATE tickets SET version = version + 1, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :ticket_id AND version = :version
                RETURNING version
            """),
            {"tenant_id": actor.tenant_id, "ticket_id": ticket_id, "version": version},
        ).scalar_one()

    def _record(self, actor: ActorContext, ticket_id: UUID, event_type: str,
                action: str, data: dict) -> None:
        # Never store internal note text or PII in event/audit payloads.
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        self.session.execute(
            text("""
                INSERT INTO ticket_events (id, tenant_id, ticket_id, event_type, payload)
                VALUES (:id, :tenant_id, :ticket_id, :event_type, CAST(:payload AS jsonb))
            """),
            {"id": uuid4(), "tenant_id": actor.tenant_id,
             "ticket_id": ticket_id, "event_type": event_type, "payload": payload},
        )
        self.session.execute(
            text("""
                INSERT INTO audit_events
                (id, tenant_id, actor_id, action, resource_type, resource_id, data)
                VALUES (:id, :tenant_id, :actor_id, :action, 'ticket',
                        :ticket_id, CAST(:payload AS jsonb))
            """),
            {"id": uuid4(), "tenant_id": actor.tenant_id, "actor_id": actor.actor_id,
             "action": action, "ticket_id": ticket_id, "payload": payload},
        )

    def assign(self, *, actor: ActorContext, ticket_id: UUID,
               assignee_user_id: UUID | None, expected_version: int) -> dict:
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)
            ticket = self._lock_ticket(actor, ticket_id, expected_version)
            if ticket["status"] == "CLOSED":
                raise HTTPException(status_code=409, detail="TICKET_CLOSED")
            current = self.session.execute(
                text("""
                    SELECT id, user_id FROM ticket_assignments
                    WHERE tenant_id = :tenant_id AND ticket_id = :ticket_id
                      AND released_at IS NULL
                    FOR UPDATE
                """),
                {"tenant_id": actor.tenant_id, "ticket_id": ticket_id},
            ).mappings().first()
            previous_user_id = current["user_id"] if current else None
            if previous_user_id == assignee_user_id:
                raise HTTPException(status_code=409, detail="ASSIGNMENT_UNCHANGED")
            if assignee_user_id is not None:
                matched = self.session.execute(
                    text("""
                        SELECT id FROM users
                        WHERE id = :user_id AND tenant_id = :tenant_id
                          AND role IN ('SUPPORT_AGENT', 'SUPERVISOR', 'ADMIN')
                    """),
                    {"user_id": assignee_user_id, "tenant_id": actor.tenant_id},
                ).scalar_one_or_none()
                if matched is None:
                    raise HTTPException(status_code=404, detail="ASSIGNEE_NOT_FOUND")
            if current:
                self.session.execute(
                    text("""
                        UPDATE ticket_assignments SET released_at = now()
                        WHERE id = :id AND tenant_id = :tenant_id
                    """),
                    {"id": current["id"], "tenant_id": actor.tenant_id},
                )
            if assignee_user_id is not None:
                self.session.execute(
                    text("""
                        INSERT INTO ticket_assignments
                        (id, tenant_id, ticket_id, user_id)
                        VALUES (:id, :tenant_id, :ticket_id, :user_id)
                    """),
                    {"id": uuid4(), "tenant_id": actor.tenant_id,
                     "ticket_id": ticket_id, "user_id": assignee_user_id},
                )
            version = self._advance_ticket(actor, ticket_id, expected_version)
            self._record(
                actor, ticket_id, "TICKET_ASSIGNMENT_CHANGED", "ticket:assign",
                {"from_user_id": str(previous_user_id) if previous_user_id else None,
                 "to_user_id": str(assignee_user_id) if assignee_user_id else None,
                 "version": version},
            )
            return {"ticket_id": ticket_id, "assignee_user_id": assignee_user_id,
                    "version": version}

    def internal_note(self, *, actor: ActorContext, ticket_id: UUID,
                      body: str, expected_version: int) -> dict:
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)
            self._lock_ticket(actor, ticket_id, expected_version)
            note_id = uuid4()
            self.session.execute(
                text("""
                    INSERT INTO ticket_messages
                    (id, tenant_id, ticket_id, author_user_id, author_type, body)
                    VALUES (:id, :tenant_id, :ticket_id, :actor_id, 'HUMAN_AGENT', :body)
                """),
                {"id": note_id, "tenant_id": actor.tenant_id,
                 "ticket_id": ticket_id, "actor_id": actor.actor_id, "body": body},
            )
            version = self._advance_ticket(actor, ticket_id, expected_version)
            self._record(
                actor, ticket_id, "INTERNAL_NOTE_ADDED", "ticket:internal_note",
                {"message_id": str(note_id), "internal_only": True, "version": version},
            )
            return {"ticket_id": ticket_id, "message_id": note_id, "version": version}
