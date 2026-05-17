# MLGG Benchmark Overview

**TL;DR**: **MLGG-Bench is the production benchmark.** NCPR-Bench is a
**research preview** — design + harness complete, but not running on a real
held-out set (blocked on data / matcher fixes). Cite MLGG-Bench numbers;
treat NCPR docs as a system-level testing roadmap, not a measurement.

This file used to frame the two as co-equal. That overstated NCPR's
maturity. Revised 2026-05-17 (autoloop fire #5) after sibling
audit-verified MLGG-Bench rigor (`252a243`) and we accepted that NCPR
isn't actually producing publishable numbers.

The two benchmarks still answer different questions and should not be
collapsed at the implementation layer — but only one is currently
load-bearing.

## At a glance

| | **MLGG-Bench** | **NCPR-Bench** |
|---|---|---|
| Layer tested | Component: RAG retrieval | System: end-to-end (RAG + 33 gates + LLM synthesis) [^a2] |

[^a2]: Per `references/benchmark/hybrid_v1_spec.md` Amendment 2 (2026-05-17,
    W25 evidence L2 = 0/264 gate-paper pairs), the 33-gate layer is a
    pipeline contract for internal instrumented runs, not an external-audit
    layer. External hybrid is L1 lint + L3 RAG only.
| Input | Synthetic reviewer-style query | Real held-out paper (methods text / peer-review bundle) |
| Ground truth | Hand-labelled CP + tag + concern_id | Real reviewer concerns from held-out Nature Communications papers |
| Headline metrics | `hit@k`, `cp_hit@k`, `tag_precision@k`, `coverage_rate` | `severity_weighted_f1`, `category_coverage`, `tail_severity_recall` |
| Current status | ✅ v1.0.1 PRODUCTION — 305 scenarios live + sibling-audited (`252a243`) | 🟡 RESEARCH PREVIEW — spec + harness done, no real 30-paper run, blocked on 4 W23 findings |
| Best use | External citation, retrieval tuning, regression detection | System-level validity check; "does MLGG match a real NC reviewer?" |
| Reference run cost | ~15s on the full 305 | ~6 min for 30 papers (W22-V2 profile) |
| Owner files | `references/retrieval_eval/MLGG-Bench-v1.0/` + `v1.0.1/` | `references/benchmark/ncpr_v*_*.md` + `scripts/rag/evals/run_ncpr_benchmark.py` |

## Why we have both

```
[NC paper input]
       │
       ▼
[methods text] ─────► [MLGG-Bench probes RAG component]
       │                       (synthetic query → expected CPs/tags)
       ▼
[33 gates + RAG + LLM synthesis]
       │
       ▼
[MLGG flag list] ───► [NCPR-Bench probes SYSTEM]
                              (flag list → match against real reviewer concerns)
```

MLGG-Bench is component testing. NCPR-Bench is system testing. A green
MLGG-Bench number does not imply a green NCPR-Bench number, and a red
NCPR-Bench does not necessarily blame retrieval.

## MLGG-Bench (sibling, mature, citable)

- 305 scenarios across slices: `indist_155` + negative + distractor + OOD-40
- 49 canonical patterns (CP-001..CP-049)
- KB contract: `peer_review_kb.v1.4` (335 papers / 817 concerns)
- v1.0.1 (current): `mean_hit@5 = 0.858`, `cp_hit@5 = 0.821`, `tag_p@5 = 0.448`, `coverage = 0.921`
- Spec + SPEC.md + citation block under `MLGG-Bench-v1.0/`
- Run: `python3 scripts/rag/evals/run_eval.py --scenarios references/retrieval_eval/MLGG-Bench-v1.0.1/all_scenarios.json --top-k 5`

**Known pending work** (per the v1.0.1 README):
- 4 unresolved scenarios with empty `expected_canonical_pattern_ids`
- v3 CP-relabel only applied to `indist_155`; OOD slices still on v2 labels
- 59 v3 label changes carry an "automated-best-effort" tag — clinical
  methodology reviewer sign-off pending before treating v1.0.1 as authoritative

## NCPR-Bench (newer, system-level, blocked on data)

- Goal: "given a held-out NC paper, does MLGG (end-to-end) flag what a
  real Nature Communications reviewer would flag?"
- v1: 6-journal stratify (BLOCKED — KB only has NC + minimal CM)
- v2: NC-only, severity + category stratify (per ADR 0006)
- Harness: `scripts/rag/evals/run_ncpr_benchmark.py` + 7 sibling modules
  (matcher, severity scorer, category coverage, paper runner, aggregator,
  holdout builder, ground truth extractor)
- 60+ unit tests passing across W22+W23 commits
- 5-paper smoke baseline (W23-D2): macro `weighted_f1 = 0.318` ± 0.099,
  recall 0.769, precision 0.201 — **smoke set, NOT publishable**;
  matcher had the lexical-path-dead bug (W23 finding #1) so all signal
  was semantic-only. Number is informational only.

**Blockers (W23 fundamental findings)**:
1. `synthesize_flags_from_rag` emits `concern_id` as `flag.code` — the
   matcher's `exact_code` + `code_prefix` layers cannot fire, all signal
   is semantic-only (W23-D2 finding)
2. Pipeline mode (with lint) is `-2.3%` vs RAG-only on the 5-paper smoke;
   lint rules (R009/R016/...) don't show up in any reviewer's
   `mlgg_gates` list so they land as pure FP (W23-D4 finding)
3. Holdout builder cannot satisfy the v2 stratification floors —
   CRITICAL papers count to 7 (target 8); `leakage` category count to 0
   (target 4) because all 9 leakage-tagged NC papers are already in
   `labeled_precision_at_5.json`. The eval-set exclusion strips the
   category to zero (W23-D1 finding)
4. The `references/case-studies/<journal>/*/<paper>/*.pdf` files are
   peer-review bundles (reviewer comments), not the published papers'
   methods sections; the v2 PDF methods extractor's "Methods" regex
   misses on 4/5 of the smoke-set papers (W23-A2 + W23-V2 finding)

These are real findings the benchmark is meant to surface — the
benchmark works; the underlying system has gaps to close.

## When to run which

| Trigger | Use |
|---|---|
| Per-commit CI sanity | MLGG-Bench (~15s) |
| Tuning ranker weights | MLGG-Bench ablation |
| Manuscript figure | MLGG-Bench citable numbers only |
| External benchmark claim | MLGG-Bench v1.0.1 (cp_hit@5 = 0.821) |
| Adding new gates | MLGG-Bench scenarios + tag/CP labels (NCPR's "does flag map to reviewer concern" is the right question but harness is research-preview) |
| Pre-release / quarterly | MLGG-Bench full 305. NCPR full N=30 deferred until: (a) lexical-path bug fixed, (b) holdout floors relaxed, (c) someone owns running it |
| System-level effectiveness research | NCPR-Bench design docs + harness (research-only use) |

## Cross-links

- METRIC_CONTRACT.md (`references/retrieval_eval/METRIC_CONTRACT.md`) —
  the retrieval-side metric contract (primary `mean_tag_precision`,
  secondary `mean_labeled_P@5` with circularity warning)
- ADR 0001 (`docs/adr/0001_mmr_breakdown_consumer.md`) — `--explain`
  flag exposing per-rank MMR breakdown for retrieval debugging
- ADR 0005 (`docs/adr/0005_ncpr_benchmark_design.md`) — NCPR design
  decision
- ADR 0006 (`docs/adr/0006_ncpr_v2_nc_only.md`) — v2 NC-only relaxation
- `docs/RAG_WAVE_1_TO_8_RETRO.md` + `docs/RAG_WAVE_9_TO_12_RETRO.md` —
  RAG-side wave-by-wave history
- `docs/PROCESS_DEBT.md` — process-level anti-patterns (stash debt,
  unbreaker churn, virtual waves, ghost re-finds)

## Open questions for v2 of this overview

- Does it ever make sense to run NCPR-Bench on a paper NOT in the KB
  reviewer corpus? (Currently impossible — no ground truth.)
- Should NCPR-Bench's `category_coverage` metric track the gates'
  category taxonomy rather than reviewer concerns' category labels?
- Once MLGG-Bench v1.0.1 clinical sign-off lands, does the cp_hit@5 gold
  become the de-facto retrieval target, demoting `tag_precision@5` to
  diagnostic?
