# Attestation Signing Onboarding

This guide walks a project maintainer from "no signing key" to
"execution_attestation_gate passes on my signed bundle" end-to-end. If
you skip any of these steps, the attestation gate reduces to an
internal-consistency check — see `README.md` in this folder for what
that means for security claims.

## 0. Prerequisites

You need `openssl` on PATH. Verify:

```sh
openssl version
# OpenSSL 3.x.x or LibreSSL 3.x.x or similar
```

Both BoringSSL-style and LibreSSL builds work. The attestation gate
calls `openssl dgst -sha256 -verify` and `openssl pkey -pubin`, which
are in every modern distribution.

## 1. Generate a signing keypair

Ed25519 is recommended — short keys, fast verify, no parameter knobs
to misconfigure. RSA also works if you have existing RSA infrastructure.

```sh
# Ed25519 (recommended)
openssl genpkey -algorithm ed25519 -out ~/mlgg_signing_key.pem
openssl pkey -in ~/mlgg_signing_key.pem -pubout -out ~/mlgg_signing_pub.pem
```

Or RSA:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
    -out ~/mlgg_signing_key.pem
openssl pkey -in ~/mlgg_signing_key.pem -pubout -out ~/mlgg_signing_pub.pem
```

**Protect the private key.** It never leaves the signing machine.

```sh
chmod 0600 ~/mlgg_signing_key.pem
```

For production: use a hardware token (YubiKey / TPM / Nitro HSM)
instead of a file. This guide covers file-based keys only.

## 2. Compute the public key fingerprint

The fingerprint is the SHA-256 of the DER-encoded public key. The
attestation gate computes the same fingerprint at verify-time and
looks it up in `trusted_signers.json`.

```sh
openssl pkey -pubin -in ~/mlgg_signing_pub.pem -outform DER | \
    openssl dgst -sha256 -binary | xxd -p -c 256
# → 64 hex chars, e.g. 8d7c2a1b...
```

Record this 64-character string. Case-insensitive; the gate normalizes
to lowercase.

## 3. Register the fingerprint in `trusted_signers.json`

If this is the first key for your project, copy the example:

```sh
cp references/attestation/trusted_signers.example.json \
   references/attestation/trusted_signers.json
```

Edit `trusted_signers.json`:

```json
{
  "version": "1.0",
  "schema": "mlgg-trusted-signers",
  "signers": [
    {
      "fingerprint_sha256": "8d7c2a1b...",
      "signer_name": "Alice Smith, MLGG Release Signer 2026",
      "active_from": "2026-04-23T00:00:00Z",
      "active_until": "2027-04-23T00:00:00Z",
      "revoked": false,
      "notes": "Initial release-signing key; rotate annually."
    }
  ]
}
```

Commit `trusted_signers.json`. This file IS the external trust anchor
— it lives in the repo, not in the attestation bundle, so an attacker
who forges a bundle has no way to get their key accepted.

## 4. Sign an attestation bundle

The attestation gate expects three files produced by this signing step:

- `signed_payload.json` — the canonical serialization of the
  attestation payload (study_id, run_id, command, timestamps,
  artifact hashes, etc.).
- `signed_payload.json.sig` — detached signature over the raw bytes
  of `signed_payload.json`.
- `signing_pub.pem` — the public key a verifier uses. Its fingerprint
  must match an active entry in `trusted_signers.json`.

```sh
# Build signed_payload.json with whatever MLGG producer step wrote it
# (e.g. scripts/orchestration/mlgg.py attest), then:

openssl dgst -sha256 \
    -sign ~/mlgg_signing_key.pem \
    -out signed_payload.json.sig \
    signed_payload.json

# Publish the public key alongside the bundle:
cp ~/mlgg_signing_pub.pem signing_pub.pem
```

The payload file and its signature MUST be byte-identical between sign
time and verify time. Any reformatting (pretty-printing JSON, stripping
trailing newlines, line-ending conversion) breaks the signature.

## 5. Reference the bundle in the attestation spec

Your `attestation_spec.json`:

```json
{
  "study_id": "my_study",
  "run_id": "2026-04-23-run-001",
  "issued_at_utc": "2026-04-23T12:00:00Z",
  "signing": {
    "method": "openssl-dgst-sha256",
    "signed_payload_file": "signed_payload.json",
    "signature_file": "signed_payload.json.sig",
    "public_key_file": "signing_pub.pem"
  },
  ...
}
```

All three referenced paths must resolve under the spec's parent
directory. Symlink escape is blocked by the gate's path sandbox —
keep the keys alongside the bundle, not symlinked from your
`~/.ssh/` or similar.

## 6. Verify

From the project root:

```sh
python3 scripts/gates/execution_attestation_gate.py \
    --attestation-spec path/to/attestation_spec.json \
    --evaluation-report path/to/evaluation_report.json \
    --report /tmp/attestation_report.json \
    --strict
# Expected: exit 0, status PASS
```

If the gate fails with `signer_not_trusted`, the fingerprint in
`trusted_signers.json` does not match what was computed from
`signing_pub.pem`. Recompute from step 2 and compare byte-by-byte.

If it fails with `attestation_stale`, regenerate the bundle — the
default freshness window is 168 hours. Bump `--max-age-hours` if your
workflow legitimately validates older bundles, but be aware that
raising this weakens replay resistance.

## 7. Rotate annually

When the `active_until` of a key approaches, generate a new keypair
(steps 1–2), add a new entry to `signers` (step 3), and mark the old
entry `revoked: true` AFTER the changeover is verified in production.

Do NOT edit or delete the old entry — audit history must stay
reconstructable. A future forensic review should be able to answer
"which key signed this attestation?" by looking only at the
`trusted_signers.json` at that point in git history.

## Dev / CI escape hatch

`--allow-unsigned` on the gate CLI skips both trust-anchor and
freshness enforcement. Every run using it emits a
`trust_anchor_bypassed` warning in the report envelope.

Do NOT enable `--allow-unsigned` on:
- CI pipelines that produce publication-grade claims
- Any run whose report might be shown to reviewers or auditors

It exists only for unit tests and exploratory development, where
generating a real signed bundle is noise.

## What if I lose the private key?

Mark the corresponding `trusted_signers.json` entry `revoked: true`
immediately. All attestations signed by that key will now fail
`signer_revoked`. Generate a new keypair (step 1) and register it
(step 3).

Old attestations cannot be re-signed. They remain cryptographically
valid but will be rejected by the hygiene gate — the expected
outcome, because a lost key cannot be distinguished from a compromised
one by the gate.
