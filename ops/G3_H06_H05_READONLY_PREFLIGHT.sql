-- G3 read-only SQL preflight for a separate, explicitly approved DB review.
-- NEVER run this automatically against production. Use audited read-only DB role.
-- H-06: duplicate active assignments would block migration 0004.
SELECT tenant_id, ticket_id, count(*) AS active_assignment_count
FROM ticket_assignments
WHERE released_at IS NULL
GROUP BY tenant_id, ticket_id
HAVING count(*) > 1
ORDER BY active_assignment_count DESC, tenant_id, ticket_id;

-- H-05: inspect grants, no mutation; role names depend on the actual environment.
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND table_name = 'audit_events'
ORDER BY grantee, privilege_type;
