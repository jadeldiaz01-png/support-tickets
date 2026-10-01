package support.authz

import rego.v1

default allow := false

internal_ticket_role(role) if {
    role in {"SUPPORT_AGENT", "SUPERVISOR", "ADMIN"}
}

valid_actor if {
    is_string(input.actor.tenant_id)
    input.actor.tenant_id != ""
    is_string(input.actor.actor_id)
    input.actor.actor_id != ""
    is_string(input.actor.external_subject)
    input.actor.external_subject != ""
    internal_ticket_role(input.actor.role)
}

allow if {
    valid_actor
    input.action == "ticket:create"
    input.resource.type == "ticket"
}

allow if {
    valid_actor
    input.action == "ticket:read"
    input.resource.type == "ticket"
    is_string(input.resource.ticket_id)
    input.resource.ticket_id != ""
}
