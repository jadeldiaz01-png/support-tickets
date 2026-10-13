-- G7: human/read-only inventory, not a production safety attestation.
-- Requires an authorized read-only SQL role. Returns aggregate counts only;
-- never exports tenant IDs, actor IDs, ticket IDs or customer payloads.
-- A missing referenced row may reflect lawful historic deletion, not attack.
SELECT 'outbox.ticket aggregate' AS relationship,
       COUNT(*) AS matched_type_count,
       COUNT(*) FILTER (WHERE t.id IS NULL) AS unresolved_or_wrong_tenant_count
FROM outbox_events o
LEFT JOIN tickets t
  ON t.id=o.aggregate_id AND t.tenant_id=o.tenant_id
WHERE o.aggregate_type='ticket';

SELECT 'audit.ticket resource' AS relationship,
       COUNT(*) AS matched_type_count,
       COUNT(*) FILTER (WHERE t.id IS NULL) AS unresolved_or_wrong_tenant_count
FROM audit_events a
LEFT JOIN tickets t
  ON t.id=a.resource_id AND t.tenant_id=a.tenant_id
WHERE a.resource_type='ticket' AND a.resource_id IS NOT NULL;

SELECT 'audit.actor' AS relationship,
       COUNT(*) AS recorded_actor_count,
       COUNT(*) FILTER (WHERE u.id IS NULL) AS unresolved_or_wrong_tenant_count
FROM audit_events a
LEFT JOIN users u ON u.id=a.actor_id AND u.tenant_id=a.tenant_id
WHERE a.actor_id IS NOT NULL;

-- Review row-level policies including the FORCE flag.
SELECT c.relname AS table_name, c.relrowsecurity AS enabled,
       c.relforcerowsecurity AS forced,
       p.polname AS policy_name, p.polpermissive AS permissive,
       pg_get_expr(p.polqual, p.polrelid) AS using_expression,
       pg_get_expr(p.polwithcheck, p.polrelid) AS check_expression
FROM pg_class c
LEFT JOIN pg_policy p ON p.polrelid=c.oid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
ORDER BY c.relname, p.polname;
