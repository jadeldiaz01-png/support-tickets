from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from repositories.db import bind_tenant
from security.context import ActorContext


def _fingerprint(*, actor: ActorContext, customer_id: UUID | None, subject: str,
                 body: str, priority: str) -> str:
    """Bind a tenant-scoped idempotency key to the initiating user and full intent."""
    data = json.dumps(
        {"actor_id": str(actor.actor_id), "customer_id": str(customer_id) if customer_id else None,
         "subject": subject, "body": body, "priority": priority},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _verified_replay(existing: dict, fingerprint: str) -> dict:
    if existing["request_sha256"] is None:
        # Old records pre-date intent fingerprinting: cannot prove equality.
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_LEGACY_KEY")
    if existing["request_sha256"] != fingerprint:
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_REUSED")
    return {key: value for key, value in existing.items() if key != "request_sha256"}


ALLOWED_TRANSITIONS = {
    "OPEN": frozenset({"IN_PROGRESS"}),
    "IN_PROGRESS": frozenset({"WAITING_CUSTOMER", "RESOLVED"}),
    "WAITING_CUSTOMER": frozenset({"IN_PROGRESS"}),
    "RESOLVED": frozenset({"IN_PROGRESS", "CLOSED"}),
    "CLOSED": frozenset(),
}


class TicketService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_ticket(
        self,
        *,
        actor: ActorContext,
        customer_id: UUID | None,
        subject: str,
        body: str,
        priority: str,
        idempotency_key: str,
    ) -> dict:
        fingerprint = _fingerprint(
            actor=actor, customer_id=customer_id, subject=subject,
            body=body, priority=priority,
        )
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)

            existing = self.session.execute(
                text(
                    """
                    SELECT id, subject, status, priority, version, created_at, request_sha256
                    FROM tickets
                    WHERE tenant_id = :tenant_id
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "tenant_id": actor.tenant_id,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().first()
            if existing:
                return _verified_replay(dict(existing), fingerprint)

            # PostgreSQL FK checks are not a tenant-ownership guarantee.
            # Verify the referenced customer under the current RLS context.
            if customer_id is not None:
                customer = self.session.execute(
                    text(
                        """
                        SELECT id FROM customers
                        WHERE id = :customer_id AND tenant_id = :tenant_id
                        """
                    ),
                    {"customer_id": customer_id, "tenant_id": actor.tenant_id},
                ).scalar_one_or_none()
                if customer is None:
                    raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")

            ticket_id = uuid4()
            inserted = self.session.execute(
                text(
                    """
                    INSERT INTO tickets (
                        id, tenant_id, customer_id, idempotency_key,
                        subject, status, priority, request_sha256
                    )
                    VALUES (
                        :id, :tenant_id, :customer_id, :idempotency_key,
                        :subject, 'OPEN', :priority, :request_sha256
                    )
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": ticket_id,
                    "tenant_id": actor.tenant_id,
                    "customer_id": customer_id,
                    "idempotency_key": idempotency_key,
                    "subject": subject,
                    "priority": priority,
                    "request_sha256": fingerprint,
                },
            ).scalar_one_or_none()
            if inserted is None:
                # Handles concurrent first-writers without IntegrityError/duplicate events.
                existing = self.session.execute(
                    text(
                        """
                        SELECT id, subject, status, priority, version,
                               created_at, request_sha256
                        FROM tickets
                        WHERE tenant_id = :tenant_id
                          AND idempotency_key = :idempotency_key
                        """
                    ),
                    {"tenant_id": actor.tenant_id, "idempotency_key": idempotency_key},
                ).mappings().one()
                return _verified_replay(dict(existing), fingerprint)

            self.session.execute(
                text(
                    """
                    INSERT INTO ticket_messages (
                        id, tenant_id, ticket_id, author_user_id,
                        author_type, body
                    )
                    VALUES (
                        :id, :tenant_id, :ticket_id, :actor_id,
                        :author_type, :body
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "tenant_id": actor.tenant_id,
                    "ticket_id": ticket_id,
                    "actor_id": actor.actor_id,
                    "author_type": (
                        "CUSTOMER" if actor.role == "CUSTOMER" else "HUMAN_AGENT"
                    ),
                    "body": body,
                },
            )

            self.session.execute(
                text(
                    """
                    INSERT INTO ticket_events (
                        id, tenant_id, ticket_id, event_type, payload
                    )
                    VALUES (
                        :id, :tenant_id, :ticket_id,
                        'TICKET_CREATED', CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "tenant_id": actor.tenant_id,
                    "ticket_id": ticket_id,
                    "payload": json.dumps({"priority": priority}),
                },
            )

            self.session.execute(
                text(
                    """
                    INSERT INTO outbox_events (
                        id, tenant_id, aggregate_type, aggregate_id,
                        event_type, payload
                    )
                    VALUES (
                        :id, :tenant_id, 'ticket', :ticket_id,
                        'ticket.created', CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "tenant_id": actor.tenant_id,
                    "ticket_id": ticket_id,
                    "payload": json.dumps(
                        {
                            "ticket_id": str(ticket_id),
                            "tenant_id": str(actor.tenant_id),
                        }
                    ),
                },
            )

            self.session.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        id, tenant_id, actor_id, action,
                        resource_type, resource_id, data
                    )
                    VALUES (
                        :id, :tenant_id, :actor_id, 'ticket:create',
                        'ticket', :ticket_id, CAST(:data AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "tenant_id": actor.tenant_id,
                    "actor_id": actor.actor_id,
                    "ticket_id": ticket_id,
                    "data": json.dumps({"idempotency_key": idempotency_key}),
                },
            )

            created = self.session.execute(
                text(
                    """
                    SELECT id, subject, status, priority, version, created_at
                    FROM tickets
                    WHERE id = :ticket_id
                    """
                ),
                {"ticket_id": ticket_id},
            ).mappings().one()
            return dict(created)

    def transition_status(
        self, *, actor: ActorContext, ticket_id: UUID,
        expected_version: int, new_status: str,
    ) -> dict:
        """Atomic internal state transition; no external send or agent action."""
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)
            current = self.session.execute(
                text(
                    """
                    SELECT id, status, version
                    FROM tickets
                    WHERE id = :ticket_id AND tenant_id = :tenant_id
                    FOR UPDATE
                    """
                ),
                {"ticket_id": ticket_id, "tenant_id": actor.tenant_id},
            ).mappings().first()
            if current is None:
                raise HTTPException(status_code=404, detail="TICKET_NOT_FOUND")
            if current["version"] != expected_version:
                raise HTTPException(status_code=409, detail="TICKET_VERSION_CONFLICT")
            old_status = current["status"]
            if new_status not in ALLOWED_TRANSITIONS[old_status]:
                raise HTTPException(status_code=409, detail="TICKET_INVALID_TRANSITION")

            updated = self.session.execute(
                text(
                    """
                    UPDATE tickets
                    SET status = :new_status, version = version + 1, updated_at = now()
                    WHERE id = :ticket_id AND tenant_id = :tenant_id
                      AND version = :expected_version
                    RETURNING id, subject, status, priority, version, created_at
                    """
                ),
                {"new_status": new_status, "ticket_id": ticket_id,
                 "tenant_id": actor.tenant_id, "expected_version": expected_version},
            ).mappings().one()
            event = {"from": old_status, "to": new_status, "version": updated["version"]}
            self.session.execute(
                text(
                    """
                    INSERT INTO ticket_events (id, tenant_id, ticket_id, event_type, payload)
                    VALUES (:id, :tenant_id, :ticket_id, 'TICKET_STATUS_CHANGED',
                            CAST(:payload AS jsonb))
                    """
                ),
                {"id": uuid4(), "tenant_id": actor.tenant_id, "ticket_id": ticket_id,
                 "payload": json.dumps(event)},
            )
            self.session.execute(
                text(
                    """
                    INSERT INTO outbox_events
                    (id, tenant_id, aggregate_type, aggregate_id, event_type, payload)
                    VALUES (:id, :tenant_id, 'ticket', :ticket_id,
                            'ticket.status_changed', CAST(:payload AS jsonb))
                    """
                ),
                {"id": uuid4(), "tenant_id": actor.tenant_id, "ticket_id": ticket_id,
                 "payload": json.dumps({"ticket_id": str(ticket_id), **event})},
            )
            self.session.execute(
                text(
                    """
                    INSERT INTO audit_events
                    (id, tenant_id, actor_id, action, resource_type, resource_id, data)
                    VALUES (:id, :tenant_id, :actor_id, 'ticket:transition',
                            'ticket', :ticket_id, CAST(:data AS jsonb))
                    """
                ),
                {"id": uuid4(), "tenant_id": actor.tenant_id, "ticket_id": ticket_id,
                 "actor_id": actor.actor_id, "data": json.dumps(event)},
            )
            return dict(updated)

    def get_ticket(self, *, actor: ActorContext, ticket_id: UUID) -> dict | None:
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)
            row = self.session.execute(
                text(
                    """
                    SELECT id, subject, status, priority, version, created_at
                    FROM tickets
                    WHERE id = :ticket_id
                    """
                ),
                {"ticket_id": ticket_id},
            ).mappings().first()
            return dict(row) if row else None
