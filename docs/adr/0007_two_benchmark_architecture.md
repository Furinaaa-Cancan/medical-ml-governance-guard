# ADR 0007 — Two-Benchmark Architecture (MLGG-Bench + NCPR-Bench)

**Status**: Accepted with Amendment 1 (2026-05-17 fire #5, see §"Amendment 1" below)

**Supersedes**: nothing
**Superseded-by**: nothing yet
**Related**: ADR 0005 (NCPR design), ADR 0006 (NCPR v2 NC-only), `docs/BENCHMARK_OVERVIEW.md`

## Context

By 2026-05-17 the repo has two benchmarks that were built independently
and could easily be conflated, collapsed into one, or treated as
duplicate work:

- **MLGG-Bench v1.0 / v1.0.1** (sibling-built, mature): 305 scenarios
  testing the RAG retrieval component. Lives at
  `references/retrieval_eval/MLGG-Bench-v1.0[.1]/`. Used by
  `scripts/rag/evals/run_eval.py`. Citable; has SPEC.md + citation
  block. Current numbers: `hit@5=0.858, cp_hit@5=0.821, tag_p@5=0.448`.

- **NCPR-Bench v1 / v2** (W22+W23, design complete, execution blocked):
  intended to measure end-to-end MLGG-as-AI-reviewer on held-out NC
  papers. Lives at `references/benchmark/ncpr_v*_*.md` +
  `scripts/rag/evals/run_ncpr_benchmark.py` (orchestrator) + 7 sibling
  modules. v2 blocked on holdout builder (only 7 CRITICAL NC papers
  survive eval-set exclusion vs target 8; leakage category 0/4 because
  all 9 leakage-tagged NC papers are already in
  `labeled_precision_at_5.json`).

The risk: a future contributor seeing two `benchmark*` directories
either (a) deletes one as duplicate, (b) tries to merge them into a
single unified metric, or (c) ships claims from one without disclosing
the other exists. All three are wrong.

## Decision

Maintain two benchmarks indefinitely. They are deliberately
non-overlapping:

| Dimension | MLGG-Bench | NCPR-Bench |
|---|---|---|
| Layer tested | RAG retrieval (component) | Full pipeline (system) |
| Input | Synthetic reviewer-style query | Real held-out paper |
| Ground truth | Hand-labelled CPs + tags | Real reviewer concerns |
| Headline metric | `cp_hit@k` | `severity_weighted_f1` |
| Cost per run | ~15s | ~6 min for 30 papers |
| Maturity | Citable | Blocked on D1 |
| Bias profile | Curator self-eval risk | Cross-paper drift risk |

Component test catches regressions in the ranker, embedder, BM25 tokenizer.
System test catches regressions in the pipeline as an
"AI reviewer". A green MLGG-Bench number does NOT imply a green
NCPR-Bench number; a red NCPR-Bench does NOT necessarily blame retrieval.

## Alternatives considered + rejected

- **Alt A: collapse into one mega-benchmark.** Rejected: different
  ground-truth source (CP labels vs reviewer concerns), different cost
  budget (per-commit vs nightly), different update cadence (CP relabel
  is automated; reviewer concerns require external sourcing).

- **Alt B: deprecate MLGG-Bench in favor of NCPR-Bench.** Rejected:
  MLGG-Bench is the only sub-second per-commit signal we have on RAG
  regression. NCPR's 6 min cost prohibits per-commit use; falling back
  to "no per-commit retrieval check" is worse than the cost of keeping
  both.

- **Alt C: deprecate NCPR-Bench in favor of MLGG-Bench.** Rejected:
  MLGG-Bench cannot answer the project's existential question — "is
  MLGG actually peer-review-grade on novel papers?" NCPR-Bench is the
  only honest measurement of system-level effectiveness.

- **Alt D: share scenarios, differ only in metric.** Rejected: NCPR's
  ground truth requires PDF + reviewer-concern triple per paper;
  MLGG-Bench's CP labels would not apply at all to a real reviewer's
  natural-language concern. The data shapes are incompatible.

## Consequences

**Positive**:
- Two independent signals catch different failure modes
- External claims can choose the appropriate scope ("RAG cp_hit" vs
  "system reviewer-match"), reducing scope drift
- Each benchmark can iterate independently (v3 of one doesn't bump v2
  of the other)

**Negative**:
- Two sets of CI scheduling decisions
- Two ADRs touched when changing eval scope
- New contributors need a routing rule ("when do I use which?")

**Mitigation**: `docs/BENCHMARK_OVERVIEW.md` is the single entry point;
both benchmarks link back to it. The routing table in §"When to run
which" is the contributor's first stop.

## Reversal criteria

This ADR should be revisited if either of:

1. NCPR-Bench's per-paper cost drops below 5s (e.g., by aggressive
   caching of embeddings + flag synthesis). Then it could replace
   MLGG-Bench as a single per-commit benchmark — but only if it also
   reaches multi-journal scope (currently NC-only blocks generalization
   claims).

2. MLGG-Bench's CP taxonomy expands to include reviewer-concern-text
   matching as a CP, AND a labeled subset is added for severity. Then
   it would functionally subsume NCPR — but the curation cost (one
   reviewer per paper per scenario) is high, so this is unlikely
   pre-v3.

## Self-challenge (1 paragraph)

The strongest argument against two-benchmark coexistence is that
contributors will eventually only run one. In practice the cheaper
benchmark (MLGG-Bench, ~15s) will dominate per-commit usage and
NCPR-Bench will atrophy — exactly the failure mode that converted
W17-C5's "honour-system maintenance contract" into 56% stale labels.
The mitigation is a CI gate that runs NCPR-Bench on a fixed cadence
(weekly? per-release?) regardless of any commit's content. That CI gate
does not yet exist; until it does, this ADR is a recommendation, not a
guarantee. Track it as W24+ work.

## Amendment 1 (autoloop fire #5, 2026-05-17)

User pushback on the original "two co-equal benchmarks" framing led to
honest re-evaluation:

- NCPR-Bench has **never produced a real 30-paper number**. Only the
  W23-D2 5-paper smoke at `weighted_f1 = 0.318` exists, and even that
  smoke was contaminated by the W23 finding-#1 lexical-path-dead
  matcher bug (all signal semantic-only).
- MLGG-Bench v1.0.1 is **already in CI**, sibling-audited (`252a243`),
  and producing reproducible headline numbers.
- The original ADR's "non-overlapping signals catch different failure
  modes" argument is correct in principle but currently asymmetric:
  one signal is live, the other is aspirational.

**Amended decision**: keep both benchmarks (do not collapse, do not
delete NCPR files), but **explicitly demote NCPR to "research preview"
status**. NCPR docs + harness remain as a roadmap for system-level
testing. MLGG-Bench is the sole production benchmark for external
claims, CI, and tuning until NCPR clears its 4 W23 blockers AND
someone owns running the 30-paper cadence.

This is option **Y** from the orchestrator's 2026-05-17 16:?? message
("我们 benchmark 是否要合并呢" decision tree). Y was chosen over X
(merge as slice) and Z (invest to make NCPR co-equal) because:
- Y is reversible (just change the framing back) if NCPR ever gets fixed
- X requires touching sibling-owned MLGG-Bench v1.0.1 production paths
  (cost + race + breakage risk on a working system)
- Z requires 10+ agent waves of fix work for a benchmark we can't run
  even once today — not justified pre-evidence

**Rejection criteria for Y → X / Y → Z promotion**:
- Y → X: NCPR's 4 W23 findings get fixed AND someone proposes the
  scenario-schema unification work to embed NCPR as a slice
- Y → Z: NCPR's 4 findings get fixed AND an owner commits to weekly
  run cadence

Until either triggers, MLGG-Bench is "the" benchmark; NCPR-Bench is
"a research roadmap".

## Provenance

- W21 autoloop fire #3 (orchestrator) — wrote `BENCHMARK_OVERVIEW.md`
- W22-T1..T5 — NCPR v1 design
- W22-X1..X8 — NCPR v1 harness modules
- W23-A..D — NCPR v2 (NC-only) + 4 fundamental findings
- Sibling sessions (b2c6b62, 373b185, c6e755a) — MLGG-Bench v1.0.1 +
  v1.1 proposed artifacts + lit-KB shap closure
- METRIC_CONTRACT.md (sibling 49e1222) — retrieval-side metric contract
  (primary `mean_tag_precision`, secondary `mean_labeled_P@5` with
  circularity warning)
