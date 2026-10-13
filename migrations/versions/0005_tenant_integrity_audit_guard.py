"""Bind ticket assignment FKs to tenant and block audit row mutation.

Revision ID: 0005_tenant_audit_guard
Revises: 0004_active_assignment_index
Create Date: 2026-10-13

Existing mismatched assignments cause atomic migration failure, never rewriting
or deleting customer data. Must be evaluated on an isolated restore before any
production rollout; production permission is NOT conferred by this migration.
"""
from alembic import op

revision = "0005_tenant_audit_guard"
down_revision = "0004_active_assignment_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Actionable preflight without dumping personal/user/ticket identifiers.
    # Constraints below independently validate all rows as well.
    op.execute("""
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ticket_assignments a
                LEFT JOIN users u
                    ON u.id = a.user_id AND u.tenant_id = a.tenant_id
                WHERE u.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'H01_H02_EXISTING_FOREIGN_TENANT_ASSIGNMENT_USER'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM ticket_assignments a
                LEFT JOIN tickets t
                    ON t.id = a.ticket_id AND t.tenant_id = a.tenant_id
                WHERE t.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'H01_H02_EXISTING_FOREIGN_TENANT_ASSIGNMENT_TICKET'
                    USING ERRCODE = '23514';
            END IF;
        END $block$;
    """)
    op.execute("""
        ALTER TABLE users
        ADD CONSTRAINT uq_users_tenant_id UNIQUE (tenant_id, id)
    """)
    op.execute("""
        ALTER TABLE tickets
        ADD CONSTRAINT uq_tickets_tenant_id UNIQUE (tenant_id, id)
    """)
    op.execute("""
        ALTER TABLE ticket_assignments
        ADD CONSTRAINT fk_assignments_tenant_user
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES users (tenant_id, id)
        ON DELETE RESTRICT
    """)
    op.execute("""
        ALTER TABLE ticket_assignments
        ADD CONSTRAINT fk_assignments_tenant_ticket
        FOREIGN KEY (tenant_id, ticket_id)
        REFERENCES tickets (tenant_id, id)
        ON DELETE CASCADE
    """)
    # Prevent accidental modification by owner-level DML too. This does not
    # defeat owner DDL, TRUNCATE or superuser powers: external durable evidence
    # and careful DB role assignment remain necessary.
    op.execute("""
        CREATE FUNCTION support_reject_audit_row_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $func$
        BEGIN
            RAISE EXCEPTION 'AUDIT_EVENTS_APPEND_ONLY'
                USING ERRCODE = '42501';
        END
        $func$
    """)
    op.execute("""
        CREATE TRIGGER audit_events_append_only_rows
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW
        EXECUTE FUNCTION support_reject_audit_row_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only_rows ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS support_reject_audit_row_mutation()")
    op.execute("ALTER TABLE ticket_assignments DROP CONSTRAINT fk_assignments_tenant_ticket")
    op.execute("ALTER TABLE ticket_assignments DROP CONSTRAINT fk_assignments_tenant_user")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT uq_tickets_tenant_id")
    op.execute("ALTER TABLE users DROP CONSTRAINT uq_users_tenant_id")
