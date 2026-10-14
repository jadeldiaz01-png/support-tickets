"""G8 local verification of signed audit batch integrity, no external IO.

Unsigned hashes alone do not protect against a database owner rewriting history.
Signatures are verifiable only against *independently trusted* public keys and
previous-head/sequence anchors. This module does not manage keys, sign, publish,
store, export customer data, or provide immutable/WORM storage.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_BATCH = 500
ZERO_DIGEST = "0" * 64
SCHEMA = "support.audit.batch.v1"
EVENT_FIELDS = frozenset({
    "id", "tenant_id", "actor_id", "action", "resource_type",
    "resource_id", "data", "created_at",
})
UNSIGNED_FIELDS = frozenset({
    "schema", "tenant_id", "batch_sequence", "previous_digest",
    "event_count", "events_digest", "key_id", "batch_digest",
})
ENVELOPE_FIELDS = UNSIGNED_FIELDS | {"signature"}


class AuditProofError(ValueError):
    """Untrusted source data or a failed cryptographic integrity check."""


def _canonical(value: object) -> bytes:
    def check(value: object, depth: int = 0) -> None:
        if depth > 24:
            raise AuditProofError("AUDIT_NESTING_LIMIT")
        if value is None or isinstance(value, (bool, str)):
            if isinstance(value, str) and len(value) > 65536:
                raise AuditProofError("AUDIT_STRING_TOO_LARGE")
            return
        if type(value) is int:
            if abs(value) > (2**53 - 1):
                raise AuditProofError("AUDIT_INTEGER_UNSAFE")
            return
        if isinstance(value, list):
            if len(value) > 10000:
                raise AuditProofError("AUDIT_COLLECTION_TOO_LARGE")
            for child in value:
                check(child, depth + 1)
            return
        if isinstance(value, dict):
            if len(value) > 10000:
                raise AuditProofError("AUDIT_COLLECTION_TOO_LARGE")
            for key, child in value.items():
                if not isinstance(key, str):
                    raise AuditProofError("AUDIT_KEY_TYPE")
                check(child, depth + 1)
            return
        raise AuditProofError("AUDIT_NON_CANONICAL_VALUE")

    check(value)
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if len(raw) > MAX_BATCH * 65536:
        raise AuditProofError("AUDIT_PAYLOAD_TOO_LARGE")
    return raw


def _uuid(raw: object) -> str:
    if not isinstance(raw, str):
        raise AuditProofError("AUDIT_INVALID_UUID")
    try:
        value = UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise AuditProofError("AUDIT_INVALID_UUID") from exc
    if str(value) != raw:
        raise AuditProofError("AUDIT_UUID_NOT_CANONICAL")
    return raw


def _uuid_or_none(raw: object) -> str | None:
    return None if raw is None else _uuid(raw)


def _digest(raw: object) -> str:
    if (not isinstance(raw, str) or len(raw) != 64
            or any(c not in "0123456789abcdef" for c in raw)):
        raise AuditProofError("AUDIT_INVALID_DIGEST")
    return raw


def _event(event: Mapping[str, object], tenant: str) -> dict:
    if not isinstance(event, Mapping) or set(event) != EVENT_FIELDS:
        raise AuditProofError("AUDIT_EVENT_SCHEMA")
    if _uuid(event["tenant_id"]) != tenant:
        raise AuditProofError("AUDIT_CROSS_TENANT_EVENT")
    action = event["action"]
    resource_type = event["resource_type"]
    if not (isinstance(action, str) and 1 <= len(action) <= 120
            and isinstance(resource_type, str)
            and 1 <= len(resource_type) <= 120):
        raise AuditProofError("AUDIT_EVENT_KIND")
    raw_time = event["created_at"]
    if not isinstance(raw_time, str):
        raise AuditProofError("AUDIT_EVENT_TIME")
    try:
        dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditProofError("AUDIT_EVENT_TIME") from exc
    if dt.utcoffset() is None:
        raise AuditProofError("AUDIT_TIMEZONE_REQUIRED")
    normalized_time = dt.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    payload = event["data"]
    if not isinstance(payload, dict):
        raise AuditProofError("AUDIT_EVENT_DATA_TYPE")
    result = {
        "id": _uuid(event["id"]),
        "tenant_id": tenant,
        "actor_id": _uuid_or_none(event["actor_id"]),
        "action": action,
        "resource_type": resource_type,
        "resource_id": _uuid_or_none(event["resource_id"]),
        "data": payload,
        "created_at": normalized_time,
    }
    if len(_canonical(result)) > 65536:
        raise AuditProofError("AUDIT_EVENT_TOO_LARGE")
    return result


def _normalized_events(events: Sequence[Mapping[str, object]], tenant: str) -> list[dict]:
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= MAX_BATCH:
        raise AuditProofError("AUDIT_BATCH_SIZE")
    normalized = [_event(event, tenant) for event in events]
    ids = [event["id"] for event in normalized]
    if len(ids) != len(set(ids)):
        raise AuditProofError("AUDIT_DUPLICATE_EVENT")
    sort_keys = [(event["created_at"], event["id"]) for event in normalized]
    if sort_keys != sorted(sort_keys):
        raise AuditProofError("AUDIT_EVENTS_OUT_OF_ORDER")
    return normalized


def _hash(namespace: bytes, raw: bytes) -> str:
    return hashlib.sha256(namespace + b"\x00" + raw).hexdigest()


def make_unsigned_batch(
    events: Sequence[Mapping[str, object]], *,
    tenant_id: str, batch_sequence: int, previous_digest: str, key_id: str,
) -> dict:
    """Produce a deterministic, unsigned manifest for externally managed signing.

    This is never a sufficient independent proof without a trusted signature,
    verified event input, and independent previous-head/sequence anchor.
    """
    tenant_id = _uuid(tenant_id)
    previous_digest = _digest(previous_digest)
    if type(batch_sequence) is not int or not 0 <= batch_sequence <= 2**53 - 1:
        raise AuditProofError("AUDIT_INVALID_SEQUENCE")
    if not isinstance(key_id, str) or not 1 <= len(key_id) <= 128:
        raise AuditProofError("AUDIT_INVALID_KEY_ID")
    normalized = _normalized_events(events, tenant_id)
    event_hash = _hash(b"SUPPORT_AUDIT_EVENTS_V1", _canonical(normalized))
    payload = {
        "schema": SCHEMA,
        "tenant_id": tenant_id,
        "batch_sequence": batch_sequence,
        "previous_digest": previous_digest,
        "event_count": len(normalized),
        "events_digest": event_hash,
        "key_id": key_id,
    }
    payload["batch_digest"] = _hash(
        b"SUPPORT_AUDIT_BATCH_V1", _canonical(payload),
    )
    return payload


def signing_bytes(unsigned: Mapping[str, object]) -> bytes:
    """Domain-separated bytes suitable for an external Ed25519 signer.

    Accept *only* the full expected unsigned structure to avoid ambiguity.
    """
    if not isinstance(unsigned, Mapping) or set(unsigned) != UNSIGNED_FIELDS:
        raise AuditProofError("AUDIT_UNSIGNED_SCHEMA")
    _digest(unsigned["batch_digest"])
    return b"SUPPORT_AUDIT_SIGNATURE_V1\x00" + _canonical(dict(unsigned))


def verify_signed_batch(
    events: Sequence[Mapping[str, object]],
    envelope: Mapping[str, object],
    *,
    trusted_public_keys: Mapping[str, bytes],
    expected_tenant_id: str,
    expected_previous_digest: str,
    expected_batch_sequence: int,
) -> str:
    """Verify a signed audit batch against independently held chain anchors.

    Returns verified batch digest. Never retrieves or writes to external systems.
    """
    if not isinstance(envelope, Mapping) or set(envelope) != ENVELOPE_FIELDS:
        raise AuditProofError("AUDIT_ENVELOPE_SCHEMA")
    if not isinstance(trusted_public_keys, Mapping):
        raise AuditProofError("AUDIT_MISSING_TRUST_ROOT")
    key_id = envelope["key_id"]
    if not isinstance(key_id, str) or key_id not in trusted_public_keys:
        raise AuditProofError("AUDIT_UNKNOWN_SIGNER")
    unsigned = {key: value for key, value in envelope.items()
                if key != "signature"}
    expected = make_unsigned_batch(
        events, tenant_id=expected_tenant_id,
        batch_sequence=expected_batch_sequence,
        previous_digest=expected_previous_digest,
        key_id=key_id,
    )
    if not hmac.compare_digest(_canonical(unsigned), _canonical(expected)):
        raise AuditProofError("AUDIT_MANIFEST_MISMATCH")
    signature = envelope["signature"]
    if not isinstance(signature, str):
        raise AuditProofError("AUDIT_SIGNATURE_SCHEMA")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        if len(signature_bytes) != 64:
            raise AuditProofError("AUDIT_SIGNATURE_LENGTH")
        key = Ed25519PublicKey.from_public_bytes(trusted_public_keys[key_id])
        key.verify(signature_bytes, signing_bytes(unsigned))
    except (InvalidSignature, ValueError, TypeError, binascii.Error) as exc:
        raise AuditProofError("AUDIT_SIGNATURE_INVALID") from exc
    return str(expected["batch_digest"])
