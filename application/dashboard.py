"""Read-only, tenant-scoped, PII-free support dashboard aggregates.

Dates are UTC, start inclusive and end exclusive; status/priority reflect the
current state of tickets created inside the requested cohort, not historic states.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from repositories.db import bind_tenant
from security.context import ActorContext

STATUSES = ("OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class TicketDashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_summary(self, *, actor: ActorContext, start: date, end: date) -> dict:
        start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(end, time.min, tzinfo=timezone.utc)
        with self.session.begin():
            bind_tenant(self.session, actor.tenant_id)
            rows = self.session.execute(
                text(
                    """
                    SELECT (created_at AT TIME ZONE 'UTC')::date AS day_utc,
                           status, priority, COUNT(*) AS ticket_count
                    FROM tickets
                    WHERE tenant_id = :tenant_id
                      AND created_at >= :start_at
                      AND created_at < :end_at
                    GROUP BY day_utc, status, priority
                    ORDER BY day_utc, status, priority
                    """
                ),
                {
                    "tenant_id": actor.tenant_id,
                    "start_at": start_at,
                    "end_at": end_at,
                },
            ).mappings().all()

        status_counts = {key: 0 for key in STATUSES}
        priority_counts = {key: 0 for key in PRIORITIES}
        days: dict[date, int] = {}
        for row in rows:
            count = int(row["ticket_count"])
            status_counts[row["status"]] += count
            priority_counts[row["priority"]] += count
            day = row["day_utc"]
            days[day] = days.get(day, 0) + count

        total = sum(status_counts.values())
        return {
            "start": start,
            "end": end,
            "timezone": "UTC",
            "cohort_definition": "TICKETS_CREATED_IN_WINDOW_CURRENT_STATE",
            "total_created": total,
            "status_counts": status_counts,
            "priority_counts": priority_counts,
            "created_by_day": [
                {"day": day, "count": count}
                for day, count in sorted(days.items())
            ],
            "generated_at": datetime.now(timezone.utc),
        }
