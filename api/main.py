from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.schemas import (
    TicketCreate, TicketDashboardSummary, TicketResponse, TicketStatusTransition,
    TicketAssignRequest, TicketAssignResult, TicketInternalNoteCreate,
    TicketInternalNoteResult,
)
from application.tickets import TicketService
from application.workflow import InternalWorkflowService
from application.dashboard import TicketDashboardService
from policy.authorizer import authorize
from repositories.db import get_engine
from security.context import ActorContext, get_actor_context

app = FastAPI(
    title="Support & Tickets API",
    version="0.2.0-identity-policy",
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
    authorize(actor, "ticket:create", resource={"type": "ticket"})
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
    authorize(
        actor,
        "ticket:read",
        resource={"type": "ticket", "ticket_id": str(ticket_id)},
    )
    result = TicketService(session).get_ticket(actor=actor, ticket_id=ticket_id)
    if result is None:
        raise HTTPException(status_code=404, detail="TICKET_NOT_FOUND")
    return TicketResponse.model_validate(result)



@app.patch("/v1/tickets/{ticket_id}/status", response_model=TicketResponse)
def transition_ticket_status(
    ticket_id: UUID,
    payload: TicketStatusTransition,
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketResponse:
    authorize(
        actor, "ticket:transition",
        resource={"type": "ticket", "ticket_id": str(ticket_id)},
    )
    result = TicketService(session).transition_status(
        actor=actor, ticket_id=ticket_id,
        expected_version=payload.expected_version, new_status=payload.status,
    )
    return TicketResponse.model_validate(result)


@app.get("/v1/dashboards/tickets/summary", response_model=TicketDashboardSummary)
def ticket_dashboard_summary(
    response: Response,
    start: date = Query(..., description="Inclusive UTC date, YYYY-MM-DD"),
    end: date = Query(..., description="Exclusive UTC date, YYYY-MM-DD"),
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketDashboardSummary:
    window_days = (end - start).days
    if window_days < 1 or window_days > 90:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="DASHBOARD_WINDOW_MUST_BE_1_TO_90_DAYS",
        )
    authorize(actor, "dashboard:read", resource={"type": "ticket_dashboard"})
    result = TicketDashboardService(session).get_summary(
        actor=actor, start=start, end=end
    )
    response.headers["Cache-Control"] = "private, no-store"
    return TicketDashboardSummary.model_validate(result)


@app.patch("/v1/tickets/{ticket_id}/assignment", response_model=TicketAssignResult)
def assign_internal_ticket(
    ticket_id: UUID,
    payload: TicketAssignRequest,
    response: Response,
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketAssignResult:
    authorize(
        actor, "ticket:assign",
        resource={"type": "ticket", "ticket_id": str(ticket_id)},
    )
    result = InternalWorkflowService(session).assign(
        actor=actor, ticket_id=ticket_id,
        assignee_user_id=payload.assignee_user_id,
        expected_version=payload.expected_version,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return TicketAssignResult.model_validate(result)


@app.post(
    "/v1/tickets/{ticket_id}/internal-notes",
    response_model=TicketInternalNoteResult, status_code=201,
)
def add_internal_ticket_note(
    ticket_id: UUID,
    payload: TicketInternalNoteCreate,
    response: Response,
    actor: ActorContext = Depends(get_actor_context),
    session: Session = Depends(get_db),
) -> TicketInternalNoteResult:
    authorize(
        actor, "ticket:internal_note",
        resource={"type": "ticket", "ticket_id": str(ticket_id)},
    )
    result = InternalWorkflowService(session).internal_note(
        actor=actor, ticket_id=ticket_id, body=payload.body,
        expected_version=payload.expected_version,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return TicketInternalNoteResult.model_validate(result)
