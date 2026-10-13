"""Index for bounded UTC ticket dashboard cohort scans.

Revision ID: 0002_dashboard_read_index
Revises: 0001_support_foundation
Create Date: 2026-10-13
"""
from alembic import op

revision = "0002_dashboard_read_index"
down_revision = "0001_support_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_tickets_tenant_created "
        "ON tickets (tenant_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_tickets_tenant_created")
