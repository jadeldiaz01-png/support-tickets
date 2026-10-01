from __future__ import annotations

from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.schemas import TicketCreate, TicketResponse
from application.tickets import TicketService
from policy.authorizer import authorize
from repositories.db import get_engine
from security.context import ActorContext, get_actor_context

app = FastAPI(
    title="Support & Tickets API",
    version="0.1.0-foundation",
    docs_url=None,
    redoc_url=None,
)


def get_db() -> Session:
    with Session(get_engine()) as session:
        yield session


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_NOT_READY",
        ) from exc
    return {"status": "database-ready", "production_authorized": "false"}


@app.post("/v1/tickets", response_model=TicketResponse, status_code=201)
def create_ticket(
    payload: TicketCreate,
    idempotency_key: str = Header(
        min_length=8,
        max_length=200,
        alias="Idempotency-Key",
    ),
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketResponse:
    authorize(actor, "ticket:create")
    result = TicketService(session).create_ticket(
        actor=actor,
        customer_id=payload.customer_id,
        subject=payload.subject,
        body=payload.body,
        priority=payload.priority,
        idempotency_key=idempotency_key,
    )
    return TicketResponse.model_validate(result)


@app.get("/v1/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: UUID,
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketResponse:
    authorize(actor, "ticket:read")
    result = TicketService(session).get_ticket(actor=actor, ticket_id=ticket_id)
    if result is None:
        raise HTTPException(status_code=404, detail="TICKET_NOT_FOUND")
    return TicketResponse.model_validate(result)
