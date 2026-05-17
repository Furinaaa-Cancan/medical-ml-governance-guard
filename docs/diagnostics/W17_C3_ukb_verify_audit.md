# W17-C3 — UKB Codebook 8-Layer Verify Audit

**Wave:** 17 (strict-review) · **Cell:** C3 · **Date:** 2026-05-17
**Script:** `scripts/codebooks/verify_ukb_codebook.py` (1455 LOC)
**Fixture:** real DB `references/codebooks/ukb/ukb_codebook.sqlite` (64 MB) +
12 raw `.txt` source files. Default + `--full-faithfulness` invocations.
**Reports:** `/tmp/W17_C3_run.json` (full), `/tmp/W17_C3_default.json` (default).

---

## TL;DR — Verdict: **YELLOW**

The script runs; every check that runs passes. But the README headline
**"8-layer verify"** does not match the implementation: there is no
"layer 8" registry. The script docstring claims **3 layers**; the code
exposes **6 named sub-layers** in the JSON report (5 in default mode);
the 1.87M-cell claim is real but only inside one opt-in sub-layer
(`--full-faithfulness`) that is **off by default and not invoked by CI
or any wrapper grepped in this audit**.

---

## Claim vs reality

| Source | Claim |
|---|---|
| `README.md:61` | "codebooks/ukb (8 层验证，1.87M cells)" |
| `README.md:76` | "verify_ukb_codebook.py 8 层验证 … 1.87M cell 全量对账" |
| `docs/reference/LINT_RULES.md:386` | "8-layer pipeline" |
| Script docstring L4 | **"Runs 3 layers of checks"** (L1 / L2 / L3) |
| Code (named layers) | L1, L2, L2c, L3, L3b, content_hashes = **6** |
| Default run report | 5 layers (L2c gated off) |
| `--full-faithfulness` run | 6 layers |

**The "8" in the README is not anchored in code.** Most plausible
reading: someone counted L2 sub-checks (counts, hard_invariants,
source_vs_db, source_encoding, ceilings) + L1 + L3 + L3b = 8. But
that interpretation is not surfaced anywhere in the script's own
output, and L2c + content_hashes are then left uncounted.

## Per-layer execution table (real DB, full-faithfulness run)

| # | Layer key in report | Function | Ran | Result | Time |
|---|---|---|---|---|---|
| 1 | `l1_source_fidelity` | `check_source_manifest` | ✓ | 0 issues | 0.026 s |
| 2 | `l2_structural` (counts) | `check_counts` | ✓ | 0 issues | 0.008 s |
| 3 | `l2_structural` (hard_inv) | `check_hard_invariants` | ✓ | 0 issues | 1.231 s |
| 4 | `l2_structural` (src↔db rows) | `check_source_vs_db_row_counts` | ✓ | 0 issues | 0.034 s |
| 5 | `l2_structural` (src encoding) | `check_source_encoding` | ✓ | 0 issues | 0.005 s |
| 6 | `l2_structural` (ceilings) | `check_ceilings` | ✓ | 0 warns | <0.001 s |
| 7 | `l2c_full_faithfulness` | `check_full_faithfulness` | ✓ (flag) | 0 issues | 1.001 s |
| 8 | `l3_golden` | `check_golden_fields` | ✓ | 0 issues | 0.090 s |
| 9 | `l3b_disease_kb` | `check_disease_kb_consistency` | ✓ | 0 errs, 1 warn | 0.001 s |
| 10 | `content_hashes` | `compute_content_hashes` + drift | ✓ | 0 drift | 0.403 s |

End-to-end default run: **1.84 s, exit 0.** Full faithfulness adds
~1.0 s for cell-by-cell scan.

Single warning surfaced (not gating): L3b flags
`atrial_fibrillation` field 24613 (AFib-Burden) marked
`identifier_direct`, outside the allowed set for disease-definition
fields. Real signal, downstream of the disease-KB provenance gap
already tracked in MEMORY.

## Silent-skip / fail-closed audit

- **Skip flags exist for L1, L3, L3b** (`--skip-l1`, `--skip-l3`,
  `--skip-disease-kb`). When invoked, the layer is omitted from
  `summary.layers` entirely — there is **no `status=skipped` record**,
  no warning, no trace. A CI job that flips a skip flag will exit 0
  with no audit trail. **Fail-closed weakness.**
- `--full-faithfulness` is the inverse: opt-in. The default run
  silently skips L2c (the only layer that touches the 1.87M cells the
  README advertises). No banner, no warning that the strongest check
  was not run.
- **Exception handlers** (lines 685, 714, 802, 904, 947, 1060, 1238,
  1250) all either append to `issues` or are safe `try/except` over
  parsing (no broad `except Exception: pass` over a check body). The
  fail-closed contract holds for layers that *are* invoked.
- Final exit: `return 2 if all_issues else 0` (line 1451). Warnings —
  including the L3b warning above and any content-hash drift in
  non-strict mode — do **not** fail. This matches MLGG's gate
  convention but means content-hash drift is informational unless
  `--strict-content-hashes` is set.

## Cell-count claim (1.87M)

Confirmed **inside L2c only.** Per the `check_full_faithfulness`
docstring (lines 921-926):

```
11,821 fields × 23 cols  = 271,883
   410 categories × 1     =     410
   858 encodings  × 2     =   1,716
    12 instances  × 1     =      12
533,286 enc_values × 3    = 1,599,858
                          ─────────
                          1,873,879  ≈ 1.87M  ✓
```

Math checks out. **But:** default run touches 0 of these cells (L2c
is flag-gated). The README's "1.87M cell 全量对账" therefore
describes a code path that the default operator does not exercise.

## Wave-N+ fix candidates

1. **R1 — reconcile "8 layers" wording (RED-light cosmetic).** Either
   make the script's `summary.layers` actually enumerate 8 named
   layers, or correct README + LINT_RULES to say "6 layers (5 default,
   +1 opt-in faithfulness, +1 content-hash drift)". Pick one and pin it.
2. **R2 — make L2c default-on (or default-on in CI).** The README
   sells the 1.87M cell guarantee as a headline. Either flip
   `--full-faithfulness` to default + add a `--skip-faithfulness`
   escape (1.0 s extra is cheap), or document in README that you must
   pass the flag.
3. **R3 — record skipped layers in the report.** When `--skip-l1` /
   `--skip-l3` / `--skip-disease-kb` are used, emit
   `summary.layers.lN = {"status": "skipped", "reason": "--skip-lN"}`
   so audit logs can detect a CI that quietly disabled a gate.
4. **R4 — disease-KB AFib warning.** Single live warning from this
   run. Hand off to disease-KB provenance review (already a tracked
   project task).
5. **R5 — `--strict-content-hashes` default-on in CI.** Currently
   informational; making it gating closes the last "warn-but-pass"
   path for the content layer.

## Files

- Script: `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/codebooks/verify_ukb_codebook.py`
- DB: `/Volumes/Seagate/Skill/ml-leakage-guard/references/codebooks/ukb/ukb_codebook.sqlite`
- Reports: `/tmp/W17_C3_run.json`, `/tmp/W17_C3_default.json`
- README claims: `README.md` lines 61, 76; `docs/reference/LINT_RULES.md:386`
