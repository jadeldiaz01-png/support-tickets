"""Support foundation schema with tenant isolation.

Revision ID: 0001_support_foundation
Revises:
Create Date: 2026-09-30
"""

from alembic import op

revision = "0001_support_foundation"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "users",
    "customers",
    "tickets",
    "ticket_messages",
    "ticket_events",
    "ticket_assignments",
    "ticket_tags",
    "ticket_sla_state",
    "approval_requests",
    "tool_intents",
    "outbox_events",
    "reconciliation_records",
    "audit_events",
    "knowledge_sources",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenants (
            id uuid PRIMARY KEY,
            slug text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE users (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            external_subject text NOT NULL,
            role text NOT NULL CHECK (role IN ('CUSTOMER','SUPPORT_AGENT','SUPERVISOR','ADMIN','SYSTEM_WORKER')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, external_subject)
        );

        CREATE TABLE customers (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            external_ref text,
            display_name text,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, external_ref)
        );

        CREATE TABLE tickets (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
            idempotency_key text NOT NULL,
            subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 300),
            status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','IN_PROGRESS','WAITING_CUSTOMER','RESOLVED','CLOSED')),
            priority text NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key)
        );

        CREATE TABLE ticket_messages (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            author_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            author_type text NOT NULL CHECK (author_type IN ('CUSTOMER','HUMAN_AGENT','SYSTEM','AI_DRAFT')),
            body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 20000),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE ticket_events (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            event_type text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE ticket_assignments (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            assigned_at timestamptz NOT NULL DEFAULT now(),
            released_at timestamptz
        );

        CREATE TABLE ticket_tags (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            tag text NOT NULL CHECK (char_length(tag) BETWEEN 1 AND 80),
            UNIQUE (tenant_id, ticket_id, tag)
        );

        CREATE TABLE ticket_sla_state (
            ticket_id uuid PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            first_response_due_at timestamptz,
            resolution_due_at timestamptz,
            first_responded_at timestamptz,
            resolved_at timestamptz,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0)
        );

        CREATE TABLE approval_requests (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid REFERENCES tickets(id) ON DELETE CASCADE,
            action text NOT NULL,
            status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','DENIED','EXPIRED','CANCELLED')),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            requested_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            decided_at timestamptz
        );

        CREATE TABLE tool_intents (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            ticket_id uuid REFERENCES tickets(id) ON DELETE CASCADE,
            tool_name text NOT NULL,
            side_effect boolean NOT NULL DEFAULT false,
            status text NOT NULL DEFAULT 'PREPARED' CHECK (status IN ('PREPARED','AUTHORIZED','EXECUTED','UNKNOWN','RECONCILED','DENIED','FAILED')),
            idempotency_key text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            result jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key)
        );

        CREATE TABLE outbox_events (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            aggregate_type text NOT NULL,
            aggregate_id uuid NOT NULL,
            event_type text NOT NULL,
            payload jsonb NOT NULL,
            status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','PUBLISHED','FAILED','UNKNOWN')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            next_attempt_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz
        );

        CREATE TABLE reconciliation_records (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            intent_id uuid REFERENCES tool_intents(id) ON DELETE CASCADE,
            external_ref text,
            state text NOT NULL CHECK (state IN ('UNKNOWN','CONFIRMED','ABSENT','CONFLICT','FAILED')),
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_checked_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE audit_events (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id uuid,
            action text NOT NULL,
            resource_type text NOT NULL,
            resource_id uuid,
            data jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE knowledge_sources (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_ref text NOT NULL,
            revision text NOT NULL,
            acl jsonb NOT NULL DEFAULT '{}'::jsonb,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_ref, revision)
        );

        CREATE INDEX idx_tickets_tenant_status ON tickets (tenant_id, status);
        CREATE INDEX idx_outbox_pending ON outbox_events (tenant_id, status, created_at);
        CREATE INDEX idx_audit_tenant_created ON audit_events (tenant_id, created_at);
        """
    )

    op.execute(
        """
        ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenants
            USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    for table in TENANT_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
