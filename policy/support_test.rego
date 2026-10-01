package support.authz_test

import rego.v1
import data.support.authz

actor := {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "actor_id": "22222222-2222-2222-2222-222222222222",
    "external_subject": "user-a",
    "role": "SUPPORT_AGENT",
}

test_support_agent_can_create_ticket if {
    authz.allow with input as {
        "actor": actor,
        "action": "ticket:create",
        "resource": {"type": "ticket"},
    }
}

test_support_agent_can_read_ticket if {
    authz.allow with input as {
        "actor": actor,
        "action": "ticket:read",
        "resource": {
            "type": "ticket",
            "ticket_id": "33333333-3333-3333-3333-333333333333",
        },
    }
}

test_customer_denied_until_customer_ownership_binding_exists if {
    not authz.allow with input as {
        "actor": object.union(actor, {"role": "CUSTOMER"}),
        "action": "ticket:read",
        "resource": {
            "type": "ticket",
            "ticket_id": "33333333-3333-3333-3333-333333333333",
        },
    }
}

test_system_worker_denied_ticket_read if {
    not authz.allow with input as {
        "actor": object.union(actor, {"role": "SYSTEM_WORKER"}),
        "action": "ticket:read",
        "resource": {
            "type": "ticket",
            "ticket_id": "33333333-3333-3333-3333-333333333333",
        },
    }
}

test_missing_tenant_denied if {
    not authz.allow with input as {
        "actor": object.remove(actor, {"tenant_id"}),
        "action": "ticket:create",
        "resource": {"type": "ticket"},
    }
}

test_unknown_action_denied if {
    not authz.allow with input as {
        "actor": actor,
        "action": "ticket:delete",
        "resource": {"type": "ticket"},
    }
}
