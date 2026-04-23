# MLGG Attestation Trust Model

## What the attestation gate does

`scripts/gates/execution_attestation_gate.py` verifies that an execution
attestation bundle is:

1. **Structurally consistent** — manifest references, artifact hashes,
   and internal timestamps line up.
2. **Signed by a trusted key** — the signing public key's SHA-256
   fingerprint appears in `trusted_signers.json` and is active.
3. **Fresh** — `issued_at_utc` is within the last `--max-age-hours`
   (default 168 h / 7 days) of wall-clock now.
4. **Sandboxed** — every file the bundle references resolves to a
   path under the attestation-spec directory. Symlink escapes are
   blocked because `Path.resolve()` yields the symlink target's
   canonical path, which is then rejected by the sandbox check.

Without (2), signature verification is self-authenticating — a
filesystem-write attacker can generate their own keypair, sign a
forged bundle with it, and the gate passes. Without (3), an old
legitimate bundle can be replayed indefinitely. Without (4), the
bundle can reference `/etc/passwd` or symlink-escape to sibling
directories.

## What the attestation gate does NOT do

- **TOCTOU hardening**: the gate checks path existence and then opens
  the file in separate syscalls. An attacker with concurrent write
  access could swap the file between check and open. Fixing this
  requires fd-based I/O throughout; not done today. Treat this gate
  as a *post-run auditor*, not a *live defense*.
- **Revocation via OCSP / CRL / Sigstore Rekor**: revocation is
  implemented as a `revoked: true` flag on entries in this file.
  External revocation sources are out of scope.
- **Signer identity beyond fingerprint**: there is no certificate
  chain validation. You are trusting the operator who curates
  `trusted_signers.json`.

## Setting up

1. Generate a signing keypair (one-time, on an air-gapped or
   hardware-backed machine):

   ```sh
   openssl genpkey -algorithm ed25519 -out mlgg_signing_key.pem
   openssl pkey -in mlgg_signing_key.pem -pubout -out mlgg_signing_pub.pem
   ```

2. Compute its SHA-256 fingerprint:

   ```sh
   openssl pkey -pubin -in mlgg_signing_pub.pem -outform DER | \
     openssl dgst -sha256 -binary | xxd -p -c 256
   ```

3. Copy `trusted_signers.example.json` to `trusted_signers.json` and
   paste the fingerprint. Set `active_from` / `active_until` to your
   rotation window. Commit `trusted_signers.json`.

4. Rotate annually by **adding** a new entry (not editing the old
   one) so audit history stays reconstructable. Mark old entries
   `revoked: true` when retired.

## Dev / CI override

`--allow-unsigned` on the gate CLI disables the trust anchor and
freshness enforcement. This is a dev escape hatch. Every run that
uses it emits a `trust_anchor_bypassed` warning. Do NOT enable it on
a pipeline that produces publication-grade claims — with the flag on,
the gate is effectively only an internal-consistency check and
cannot stop forged attestations.

## Hardening path (not yet wired)

- fd-based I/O to close the TOCTOU race.
- Sigstore / Rekor transparency-log cross-check as a stronger
  alternative to a local allowlist.
- Hardware-backed keys (YubiKey / TPM / Nitro HSM) for signing.
