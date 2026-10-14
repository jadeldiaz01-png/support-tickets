"""Persist canonical request fingerprint for idempotent ticket creates.

Revision ID: 0003_ticket_request_fingerprint
Revises: 0002_dashboard_read_index
Create Date: 2026-10-13

Historical records remain NULL: do not retroactively attest unknown intent.
"""
from alembic import op

revision = "0003_ticket_request_fingerprint"
down_revision = "0002_dashboard_read_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tickets ADD COLUMN request_sha256 text "
        "CHECK (request_sha256 IS NULL OR "
        "request_sha256 ~ '^[0-9a-f]{64}$')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP COLUMN request_sha256")
