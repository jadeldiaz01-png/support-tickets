"""Prevent more than one active assignment per ticket.

Revision ID: 0004_active_assignment_index
Revises: 0003_ticket_request_fingerprint
Create Date: 2026-10-13
"""
from alembic import op

revision = "0004_active_assignment_index"
down_revision = "0003_ticket_request_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX uq_ticket_active_assignment_per_tenant
        ON ticket_assignments (tenant_id, ticket_id)
        WHERE released_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX uq_ticket_active_assignment_per_tenant")
