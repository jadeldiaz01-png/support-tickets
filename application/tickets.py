from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from repositories.db import bind_tenant
from security.context import ActorContext


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
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)

            existing = self.session.execute(
                text(
                    """
                    SELECT id, subject, status, priority, version, created_at
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
                return dict(existing)

            ticket_id = uuid4()
            self.session.execute(
                text(
                    """
                    INSERT INTO tickets (
                        id, tenant_id, customer_id, idempotency_key,
                        subject, status, priority
                    )
                    VALUES (
                        :id, :tenant_id, :customer_id, :idempotency_key,
                        :subject, 'OPEN', :priority
                    )
                    """
                ),
                {
                    "id": ticket_id,
                    "tenant_id": actor.tenant_id,
                    "customer_id": customer_id,
                    "idempotency_key": idempotency_key,
                    "subject": subject,
                    "priority": priority,
                },
            )

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
