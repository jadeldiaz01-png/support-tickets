# G8 — Offline signed audit proof verification (TEST / DESIGN ONLY)

Date: 2026-10-13. Based on G7 PR #13 HEAD
\`64a5e1fe88555f635f8f6797d9b4ad9a5cebb6cf\`.

## Objective

Provide a deterministic, fail-closed, **offline** verifier for the integrity
of **synthetic** PostgreSQL audit event batches, with no production connection,
no signing secret, no exporter, no network call and no storage vendor.

The module \`security/audit_manifest.py\` uses canonical JSON, SHA-256
domain separation, event UUID validation, UTC microsecond timestamps,
unique event IDs, ordered batches and strict schemas.
\`cryptography==50.0.2\` (already pinned) verifies Ed25519 signatures
using an **independently trusted** caller-supplied public key and
**independently recorded** previous digest/sequence.
\`make_unsigned_batch\` returns a local candidate manifest; an external
signing identity is **not provided or provisioned**.
Synthetic tests generate temporary Ed25519 keys inside pytest only and
never persist, export, or log private key material.

## Threat model and explicit non-goals

- An actor changing, removing, adding or reordering events relative to a
  *trusted signed and externally anchored* manifest is detected by the verifier.
- An actor substituting a signer, signature, expected previous digest or
  batch sequence is rejected.
- An attacker controlling the database, unsigned manifests **and** their
  trusted key/previous-head store can forge history; this module offers
  no defense in that scenario.
- Completely missing tail batches are **not detected** unless an independent
  observer knows the expected latest signed head/sequence and that all
  batches were delivered. Verification of a chain is not proof that the
  actual database contains every committed event.
- Hashing/signing existing supplied events does NOT prove those events
  were authentic, timely, privacy-lawful, free of PII or complete.
- No external WORM/immutability, retention enforcement, signer provenance,
  key rotation, replay protection across tenants, exporter, database trigger,
  append-only outbox worker, payment, external notification or production use.
- The actual PostgreSQL owner can still TRUNCATE audit tables or DDL,
  and unrelated polymorphic ID relationships remain unverified.
- The sequence and digest anchor must be tracked outside the DB owner/admin
  scope. **Do not deploy** any key/storage integration without specific
  authorized provider, retention, privacy, cost and recovery gates.

## API (local / no IO)

\`\`\`python
from security.audit_manifest import (
    ZERO_DIGEST, make_unsigned_batch, signing_bytes, verify_signed_batch,
)
unsigned = make_unsigned_batch(
    synthetic_events, tenant_id=tenant, batch_sequence=0,
    previous_digest=ZERO_DIGEST, key_id="offline-test-key",
)
# A separate, independently authorized signer would sign signing_bytes(unsigned)
# using an externally managed private key. No such signer exists here.
# A separate verifier may verify a signed envelope using approved public
# keys and independently retained previous-head/sequence:
verify_signed_batch(
    synthetic_events, signed_envelope,
    trusted_public_keys={"offline-test-key": trusted_ed25519_public_key},
    expected_tenant_id=tenant, expected_previous_digest=ZERO_DIGEST,
    expected_batch_sequence=0,
)
\`\`\`

The current integration is only exercised by pytest using synthetic data.
External keys, customer data, production tokens and retained evidence must
never be pasted into GitHub issues, Actions logs or documents.

## Separate human/administrative gates

1. Privacy/retention assessment for any export of audit evidence or digest.
2. External independent trust anchor, signing key ownership, key rotation,
   storage cost, immutability guarantees, gap monitoring and restoration.
3. Representative licensed/authorized data restore and migration rehearsal.
4. Actual production database permissions and owner/superuser isolation.
5. GitHub \`main\` ruleset approval/CODEOWNERS, new explicit merge
   authorization and deployment authorization.

The owner withdrew optional reviewer requests on G6/G6.1, **not**
mandatory GitHub main protections. All code remains \`RESEARCH_ONLY\` /
\`HOLD / NO_MERGE / PRODUCTION_AUTHORIZED=false\`.
