from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"


class TicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    subject: str
    status: str
    priority: str
    version: int
    created_at: datetime


class TicketDashboardDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    count: int = Field(ge=0)


class TicketDashboardSummary(BaseModel):
    """No ticket subjects, bodies, customer IDs or other PII."""

    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    timezone: Literal["UTC"]
    cohort_definition: Literal["TICKETS_CREATED_IN_WINDOW_CURRENT_STATE"]
    total_created: int = Field(ge=0)
    status_counts: dict[str, int]
    priority_counts: dict[str, int]
    created_by_day: list[TicketDashboardDay]
    generated_at: datetime
