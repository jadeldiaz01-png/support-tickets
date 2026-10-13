"""G6: tenant-couple all remaining direct references in initial support schema.

Revision ID: 0006_tenant_fks
Revises: 0005_tenant_audit_guard

Does not touch a production DB unless independently approved/applied later.
All constraints are validated; preexisting mismatches abort the full transaction.
"""
from alembic import op

revision = "0006_tenant_fks"
down_revision = "0005_tenant_audit_guard"
branch_labels = None
depends_on = None

# (child, parent, nullable-or-required child ref, original FK, original delete action,
#  composite constraint already installed in 0005)
REFERENCES = (
    ("ticket_assignments","tickets","ticket_id","ticket_assignments_ticket_id_fkey","CASCADE",True),
    ("ticket_assignments","users","user_id","ticket_assignments_user_id_fkey","RESTRICT",True),
    ("approval_requests","users","decided_by","approval_requests_decided_by_fkey","SET NULL (decided_by)",False),
    ("approval_requests","users","requested_by","approval_requests_requested_by_fkey","SET NULL (requested_by)",False),
    ("approval_requests","tickets","ticket_id","approval_requests_ticket_id_fkey","CASCADE",False),
    ("reconciliation_records","tool_intents","intent_id","reconciliation_records_intent_id_fkey","CASCADE",False),
    ("ticket_events","tickets","ticket_id","ticket_events_ticket_id_fkey","CASCADE",False),
    ("ticket_messages","users","author_user_id","ticket_messages_author_user_id_fkey","SET NULL (author_user_id)",False),
    ("ticket_messages","tickets","ticket_id","ticket_messages_ticket_id_fkey","CASCADE",False),
    ("ticket_sla_state","tickets","ticket_id","ticket_sla_state_ticket_id_fkey","CASCADE",False),
    ("ticket_tags","tickets","ticket_id","ticket_tags_ticket_id_fkey","CASCADE",False),
    ("tickets","customers","customer_id","tickets_customer_id_fkey","SET NULL (customer_id)",False),
    ("tool_intents","tickets","ticket_id","tool_intents_ticket_id_fkey","CASCADE",False)
)

def _new_name(child: str, column: str) -> str:
    return f"g6_fk_{child}_{column}"


def upgrade() -> None:
    # Do not emit row identifiers/PII in exceptions or logs.
    # This preflight is for the 11 as-yet uncoupled relationships; the two
    # assignment relationships were validated in 0005.
    op.execute("""
    DO $g6$
    DECLARE
      item record;
      mismatch boolean;
    BEGIN
      FOR item IN
        SELECT * FROM (VALUES
        ('approval_requests','users','decided_by'),
        ('approval_requests','users','requested_by'),
        ('approval_requests','tickets','ticket_id'),
        ('reconciliation_records','tool_intents','intent_id'),
        ('ticket_events','tickets','ticket_id'),
        ('ticket_messages','users','author_user_id'),
        ('ticket_messages','tickets','ticket_id'),
        ('ticket_sla_state','tickets','ticket_id'),
        ('ticket_tags','tickets','ticket_id'),
        ('tickets','customers','customer_id'),
        ('tool_intents','tickets','ticket_id')
        ) AS refs(child_table, parent_table, child_column)
      LOOP
        EXECUTE format(
          'SELECT EXISTS (SELECT 1 FROM %I c '
          || 'LEFT JOIN %I p ON p.id=c.%I AND p.tenant_id=c.tenant_id '
          || 'WHERE c.%I IS NOT NULL AND p.id IS NULL)',
          item.child_table, item.parent_table,
          item.child_column, item.child_column
        ) INTO mismatch;
        IF mismatch THEN
          RAISE EXCEPTION 'G6_EXISTING_CROSS_TENANT_REFERENCE: %.%',
            item.child_table, item.child_column
            USING ERRCODE = '23514';
        END IF;
      END LOOP;
    END $g6$;
    """)
    op.execute("ALTER TABLE customers ADD CONSTRAINT g6_uq_customer_tenant_id UNIQUE (tenant_id,id)")
    op.execute("ALTER TABLE tool_intents ADD CONSTRAINT g6_uq_intent_tenant_id UNIQUE (tenant_id,id)")

    # Existing 0005 assignment composite FKs are retained untouched.
    # Add validated tenant-scoped replacements BEFORE dropping old plain FKs.
    for child, parent, col, old_name, action, present in REFERENCES:
        if not present:
            op.execute(
                f"ALTER TABLE {child} ADD CONSTRAINT {_new_name(child,col)} "
                f"FOREIGN KEY (tenant_id,{col}) REFERENCES {parent}(tenant_id,id) "
                f"ON DELETE {action}"
            )
    for child, parent, col, old_name, action, present in REFERENCES:
        op.execute(f"ALTER TABLE {child} DROP CONSTRAINT {old_name}")


def downgrade() -> None:
    # Restore old single-column behavior BEFORE dropping composite guards.
    # Downgrade weakens tenant isolation: only for disposable CI or separately
    # authorized recovery; never an automatic production rollback.
    for child, parent, col, old_name, action, present in REFERENCES:
        op.execute(
            f"ALTER TABLE {child} ADD CONSTRAINT {old_name} "
            f"FOREIGN KEY ({col}) REFERENCES {parent}(id) ON DELETE {action.split(' (')[0]}"
        )
    for child, parent, col, old_name, action, present in REFERENCES:
        if not present:
            op.execute(f"ALTER TABLE {child} DROP CONSTRAINT {_new_name(child,col)}")
    op.execute("ALTER TABLE tool_intents DROP CONSTRAINT g6_uq_intent_tenant_id")
    op.execute("ALTER TABLE customers DROP CONSTRAINT g6_uq_customer_tenant_id")
