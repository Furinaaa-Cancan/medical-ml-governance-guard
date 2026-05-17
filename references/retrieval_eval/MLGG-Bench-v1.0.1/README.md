# MLGG-Bench v1.0.1 — CP-Relabel PATCH

| Field | Value |
|---|---|
| Version | 1.0.1 |
| Release date | 2026-05-17 |
| Change type | PATCH (gold-label refinement; no scenarios added or removed) |
| Builds on | v1.0 (`../MLGG-Bench-v1.0/`) |
| Files changed | `all_scenarios.json` (`expected_canonical_pattern_ids` updated on 59/155 indist scenarios) |

## What changed

A full-pass CP relabel was run on all 155 `indist_155` scenarios, *without* anchoring on the source_concern's native CP — independently re-derived from `query_text` + KB. This corrects the conservative bias of the v1.0 CP-Relabel v2 pass (which had only touched 25 scenarios seeded by the bench_06 IRR audit).

**Delta distribution (155 indist scenarios):**

| Change | Count | %  |
|---|---|---|
| `unchanged` | 96 | 62% |
| `refined` (stricter subset) | 12 | 8% |
| `expanded` (added relevant CP) | 27 | 17% |
| `replaced` (swapped CP entirely) | 20 | 13% |
| **Total touched** | **59** | **38%** |

**Top REPLACED transitions** (where v2 used a catch-all CP that v3 replaced with a more specific one):

1. `CP-003 → CP-002` ×5 — catch-all "causality_and_framing" → concrete cohort/inclusion concern
2. `CP-002 → CP-036` ×2 — generic cohort → outcome/time-horizon conflation (definition-variable)
3. `CP-048 → CP-002` ×2 — ancestry-terminology → confounding-by-age/sex/BMI in unmatched controls
4. `CP-026 → CP-020` (varied) — AUC-vs-calibration → clinically-critical-metric-omitted
5. `CP-009/011 → CP-035` (varied) — generic code-availability → demo-artifact-mismatch-with-text

## Metric impact

Re-run on the full 305-scenario benchmark with v3 labels (vs. v1.0):

| Metric | v1.0 | **v1.0.1** | Δ |
|---|---|---|---|
| `mean_hit_at_k` | 0.858 | 0.858 | 0 (tag overlap unchanged) |
| **`mean_cp_hit_at_k`** | **0.794** | **0.821** | **+0.027** |
| `n_cp_evaluable` | 252 | 252 | 0 |
| `mean_tag_precision_at_k` | 0.448 | 0.448 | 0 |
| `coverage_rate` | 0.921 | 0.921 | 0 |

Interpretation: 38% of CP labels changed, but cp_hit moves only +0.027. This means the RAG was *already* retrieving both the v2 catch-all CPs and the more-specific v3 CPs in its top-5 — the metric improvement reflects v3's stricter scoring rule, not new retrievals. CP labels in v1.0.1 are a more honest measure of CP-level recall.

## Audit trail

- `cp_relabel_v3_changelog.json` — per-scenario `(v2_cps, v3_cps, change_type, reason)` for all 155 scenarios. Use this to spot-audit before treating v1.0.1 as authoritative.
- The CP-Relabel v3 agent (autonomous) recommended a hand spot-audit of ~10 REPLACED + 5 EXPANDED before global merge. **That audit has NOT been done.** v1.0.1 should be treated as "automated-best-effort" until a clinical methodology reviewer has signed off on the 59 changes.

## Files

```
MLGG-Bench-v1.0.1/
├── README.md                       ← this file
├── all_scenarios.json              ← 305 scenarios with v3 CP labels applied to indist_155
└── cp_relabel_v3_changelog.json    ← per-scenario change log
```

Everything else (SPEC.md, baselines, splits, runner) inherits from `../MLGG-Bench-v1.0/` — no copies. To run the v1.0.1 benchmark:

```bash
python3 scripts/rag/evals/run_eval.py \
  --scenarios references/retrieval_eval/MLGG-Bench-v1.0.1/all_scenarios.json \
  --top-k 5
```

## Relationship to v1.1_proposed

v1.0.1 is the verified PATCH. The parallel `../MLGG-Bench-v1.0/v1.1_proposed/` directory contains DRAFT artifacts for v1.1.0 (a MINOR release) — KB meta-entries, compound-query prototype, etc. — none of which are auto-promoted because they require either clinical review (KB additions) or a more substantive fix (compound prototype was a negative result).

## Pending for v1.0.2 or v1.1.0

- Hand spot-audit of v3 REPLACED/EXPANDED set — **partially done**: see `v3_spot_audit.md` (9/15 v3-better verified, 3/15 flagged for human review, 3/15 ties); full 59-change audit still pending
- Apply CP relabel methodology to the OOD slices (currently only indist_155 was re-audited; ood_01–04 still carry agent-original CPs)
- ~~Resolve the 4 unresolved scenarios where v3 still has empty `expected_canonical_pattern_ids`~~ — **resolved**: indist_155 now has 0 empty CP labels post-relabel. (53 scenarios across other slices have intentionally empty CPs: 30 in `baseline_30` (legacy schema), 10 in `bench_04_negatives` (out-of-scope, by design), 10 in `bench_05_distractors` (by design), 3 in `bench_01_fairness` (no clear CP fit per fairness agent's own audit) — those are correct, not bugs.)
