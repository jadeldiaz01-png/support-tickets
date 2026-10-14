"""G8 offline adversarial checks; ephemeral private keys used ONLY in tests."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from security.audit_manifest import (
    ZERO_DIGEST, AuditProofError, make_unsigned_batch, signing_bytes,
    verify_signed_batch,
)


def fixture():
    tenant = str(uuid4())
    user = str(uuid4())
    events = [
        {
            "id": str(uuid4()), "tenant_id": tenant, "actor_id": user,
            "action": "ticket:create", "resource_type": "ticket",
            "resource_id": str(uuid4()),
            "data": {"status": "OPEN", "version": 1},
            "created_at": (datetime(2026, 10, 13, tzinfo=timezone.utc)
                           + timedelta(minutes=i)).isoformat(),
        }
        for i in range(2)
    ]
    events.sort(key=lambda event: (event["created_at"], event["id"]))
    private = Ed25519PrivateKey.generate()  # ephemeral synthetic test only
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    unsigned = make_unsigned_batch(
        events, tenant_id=tenant, batch_sequence=0,
        previous_digest=ZERO_DIGEST, key_id="test-key-1",
    )
    signed = {**unsigned, "signature": base64.b64encode(
        private.sign(signing_bytes(unsigned))
    ).decode("ascii")}
    return events, tenant, private, public, signed


def verify(events, tenant, public, signed, *, prev=ZERO_DIGEST, seq=0):
    return verify_signed_batch(
        events, signed, trusted_public_keys={"test-key-1": public},
        expected_tenant_id=tenant, expected_previous_digest=prev,
        expected_batch_sequence=seq,
    )


def test_g8_signed_batch_pass_and_no_raw_events_in_manifest():
    events, tenant, _private, public, signed = fixture()
    assert verify(events, tenant, public, signed) == signed["batch_digest"]
    encoded = str(signed)
    assert events[0]["resource_id"] not in encoded
    assert events[0]["actor_id"] not in encoded


@pytest.mark.parametrize("field,mutated", [
    ("action", "ticket:deleted"),
    ("resource_type", "other"),
    ("data", {"status": "CHANGED"}),
    ("resource_id", "00000000-0000-0000-0000-000000000001"),
    ("created_at", "2026-10-13T00:05:00Z"),
])
def test_g8_detects_source_record_tampering(field, mutated):
    events, tenant, _private, public, signed = fixture()
    changed = deepcopy(events)
    changed[0][field] = mutated
    with pytest.raises(AuditProofError):
        verify(changed, tenant, public, signed)


def test_g8_detects_removed_added_or_reordered_records():
    events, tenant, _private, public, signed = fixture()
    for changed in ([events[0]], list(reversed(events)), events + [events[0]]):
        with pytest.raises(AuditProofError):
            verify(changed, tenant, public, signed)


def test_g8_detects_audit_tenant_substitution():
    events, tenant, _private, public, signed = fixture()
    altered = deepcopy(events)
    altered[1]["tenant_id"] = str(uuid4())
    with pytest.raises(AuditProofError, match="CROSS_TENANT"):
        verify(altered, tenant, public, signed)


def test_g8_rejects_unsigned_or_wrong_signature():
    events, tenant, _private, public, signed = fixture()
    for altered in ({k: v for k, v in signed.items() if k != "signature"},
                    {**signed, "signature": base64.b64encode(b"x"*64).decode()}):
        with pytest.raises(AuditProofError):
            verify(events, tenant, public, altered)


def test_g8_rejects_untrusted_key_even_when_other_signature_valid():
    events, tenant, _private, public, signed = fixture()
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    with pytest.raises(AuditProofError, match="SIGNATURE_INVALID"):
        verify(events, tenant, other, signed)
    with pytest.raises(AuditProofError, match="UNKNOWN_SIGNER"):
        verify_signed_batch(
            events, signed, trusted_public_keys={"other-key": public},
            expected_tenant_id=tenant,
            expected_previous_digest=ZERO_DIGEST, expected_batch_sequence=0,
        )


def test_g8_rejects_wrong_expected_head_or_batch_sequence():
    events, tenant, _private, public, signed = fixture()
    with pytest.raises(AuditProofError, match="MANIFEST_MISMATCH"):
        verify(events, tenant, public, signed, prev="a"*64)
    with pytest.raises(AuditProofError, match="MANIFEST_MISMATCH"):
        verify(events, tenant, public, signed, seq=1)


def test_g8_rejects_signed_but_rehashed_manifest_without_new_signature():
    events, tenant, _private, public, signed = fixture()
    altered = {**signed, "batch_digest": "f"*64}
    with pytest.raises(AuditProofError):
        verify(events, tenant, public, altered)


@pytest.mark.parametrize("mutate", [
    lambda event: event.update({"created_at": "2026-10-13T00:00:00"}),
    lambda event: event.update({"data": {"bad": float("nan")}}),
    lambda event: event.update({"data": {"bad": 1.5}}),
    lambda event: event.update({"data": {"bad": b"binary"}}),
    lambda event: event.update({"tenant_id": "nonsense"}),
    lambda event: event.update({"extra": "unrecognized"}),
])
def test_g8_rejects_noncanonical_or_unknown_event_data(mutate):
    events, tenant, _private, _public, _signed = fixture()
    alter = deepcopy(events)
    mutate(alter[0])
    with pytest.raises(AuditProofError):
        make_unsigned_batch(
            alter, tenant_id=tenant, batch_sequence=0,
            previous_digest=ZERO_DIGEST, key_id="test-key-1",
        )


def test_g8_normalizes_timestamp_to_utc_without_signature_changes():
    events, tenant, _private, public, signed = fixture()
    other = deepcopy(events)
    other[0]["created_at"] = "2026-10-12T20:00:00-04:00"
    other[1]["created_at"] = "2026-10-12T20:01:00-04:00"
    assert verify(other, tenant, public, signed) == signed["batch_digest"]


def test_g8_prevents_duplicate_and_cross_tenant_batches():
    events, tenant, _private, _public, _signed = fixture()
    with pytest.raises(AuditProofError):
        make_unsigned_batch(
            events + events, tenant_id=tenant,
            batch_sequence=0, previous_digest=ZERO_DIGEST, key_id="test-key-1",
        )
    with pytest.raises(AuditProofError):
        make_unsigned_batch(
            events, tenant_id=str(uuid4()),
            batch_sequence=0, previous_digest=ZERO_DIGEST, key_id="test-key-1",
        )


def test_g8_chain_requires_previous_independent_batch_head():
    events, tenant, _private, public, signed = fixture()
    next_unsigned = make_unsigned_batch(
        [events[0]], tenant_id=tenant,
        batch_sequence=1,
        previous_digest=signed["batch_digest"], key_id="test-key-1",
    )
    assert next_unsigned["previous_digest"] == verify(events, tenant, public, signed)
    # An independently retained previous digest must be supplied to the
    # verifier; the code cannot discover records deleted entirely at the end.
    with pytest.raises(AuditProofError):
        verify_signed_batch(
            events, signed, trusted_public_keys={"test-key-1": public},
            expected_tenant_id=tenant, expected_previous_digest=signed["batch_digest"],
            expected_batch_sequence=0,
        )
