-- G5 read-only audit, for reviewer-run on an approved isolated DB only.
-- Run via a read-only database role, do not paste personal identifiers.
-- This file does not prove anything about a production environment until
-- executed there under a separately approved, scoped read-only procedure.

-- Effective audit privileges for the currently connected actor, reflecting
-- inherited memberships and PUBLIC (unlike a grant listing alone).
SELECT current_user AS actor,
       has_table_privilege(current_user,'public.audit_events','SELECT') AS can_read,
       has_table_privilege(current_user,'public.audit_events','INSERT') AS can_append,
       has_table_privilege(current_user,'public.audit_events','UPDATE') AS can_update,
       has_table_privilege(current_user,'public.audit_events','DELETE') AS can_delete,
       has_table_privilege(current_user,'public.audit_events','TRUNCATE') AS can_truncate,
       has_table_privilege(current_user,'public.audit_events','TRIGGER') AS can_create_trigger,
       has_schema_privilege(current_user,'public','CREATE') AS can_create_in_schema;

-- Attribute read only; role names do not contain customer data.
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit
FROM pg_roles
WHERE rolname = current_user;

-- Actual role membership grants, with INHERIT/SET options.
SELECT g.rolname AS grant_role, m.inherit_option, m.set_option
FROM pg_auth_members m
JOIN pg_roles member ON member.oid=m.member
JOIN pg_roles g ON g.oid=m.roleid
WHERE member.rolname = current_user
ORDER BY g.rolname;

-- Schema-wide foreign key inventory. Non-coupled FK != confirmed exploit:
-- check companion constraints, RLS and application access on each relationship.
SELECT c.conrelid::regclass AS child_table,
       c.confrelid::regclass AS parent_table,
       c.conname, c.convalidated,
       (SELECT bool_or(att.attname='tenant_id')
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute att
          ON att.attrelid=c.conrelid AND att.attnum=k.attnum) AS child_fk_has_tenant
FROM pg_constraint c
WHERE c.contype='f' AND c.connamespace='public'::regnamespace
ORDER BY child_table, parent_table, c.conname;

-- Sanitized preflight count: invalid assignments before 0005 would stop it.
SELECT count(*) AS invalid_assignment_user_links
FROM ticket_assignments a
LEFT JOIN users u ON u.id=a.user_id AND u.tenant_id=a.tenant_id
WHERE u.id IS NULL;

SELECT count(*) AS invalid_assignment_ticket_links
FROM ticket_assignments a
LEFT JOIN tickets t ON t.id=a.ticket_id AND t.tenant_id=a.tenant_id
WHERE t.id IS NULL;

-- Audit trigger state, not an immutable log store attestation.
SELECT tgname, tgenabled
FROM pg_trigger WHERE tgrelid='public.audit_events'::regclass
AND NOT tgisinternal ORDER BY tgname;
