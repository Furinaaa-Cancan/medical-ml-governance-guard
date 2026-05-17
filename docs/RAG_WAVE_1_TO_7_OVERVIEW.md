# RAG Layer: Wave 1-7 Overview (2026-05-16 to 2026-05-17)

**Status**: closeout narrative.
**Authority**: Wave 8 W9 retrospective.
**Scope**: the two-day RAG hardening effort that followed the 5-agent strict
eval (E1-E5), through Wave 7's measurement-system corrections.

## TL;DR

- 5-agent strict eval (E1-E5) found 30+ bugs across four dimensions
  (precision, decomposition, edge cases, gate coverage).
- 7 fix waves shipped ~78 commits, with sub-tracks labeled F*, H*, G*, A*,
  P*, W* (numbering reset per wave; orchestrator scope-tagged each agent).
- Net delta: free-text mean P@5 settled at ~0.61 while gate-anchored P@5
  reached ~0.79 (H14 vs E1 baseline of 0.717). BM25 is now load-bearing in
  gate-anchored mode (G8 fix), MMR diversifies on dense cosine instead of
  raw score, and roughly half a dozen LLM-side hedges shipped to keep the
  synthesis layer honest under weak retrieval.
- Three architectural findings remain in the backlog: `tag_overlap` is
  mostly dead (W7-P4), the KB tag space is severely fragmented (W7-P6),
  and the eval harness is gate-driven where production is partially
  query-driven (W7-P1 closed the harness side but the divergence story is
  not finished).

## Wave timeline

### Pre-wave: 5-agent strict eval (2026-05-16)

Five agents ran in parallel against the freshly merged Wave-2026-05-13 KB
(~335 entries / 817 reviewer concerns):

- **E1 — retrieval precision audit**: 12 hand-graded queries, mean P@5
  = 0.717 (summary header said 0.80; per-query table is the truth).
  Strongest dimensions all hit P@5 = 1.0 (leakage, calibration, class
  imbalance, external validation, reproducibility). Four weak dimensions
  surfaced: missing data (0.2), AUROC-CI (0.2), temporal validation
  (0.3), tuning-on-test (0.4). Four defect categories cataloged: topical
  drift, severity-driven displacement, lexical-anchor failure,
  near-duplicate clusters. Full report at `/tmp/E1_retrieval_precision.md`.
- **E2 — hybrid decomposition**: BM25 effectively dead in free-text mode
  because `hybrid_rank` guards on `if gate and failure_codes`. Dense
  carried 100% of free-text scoring.
- **E3 — edge cases + CLI parity**: empty-string queries crashed, the
  bridge had a circular import, and the gate-only contract was being
  violated.
- **E4 — cache + performance**: cold-start latency budget, cache signal
  staleness when the KB hash changed.
- **E5 — 33-gate coverage**: only 1 sparse gate (`prediction_replay_gate`,
  1 KB entry), 4 honest-empty gates (infra/audit). No KB tag hygiene
  drift. Method A (empty query + gate filter) crashed on every gate —
  the same bug E3 surfaced. Full report at `/tmp/E5_gate_coverage.md`.

### Wave 1 (F1-F5): code-bug fix wave

Triggered by E1+E2+E3. The four ship-stopper hybrid-ranker scoring bugs
landed in `830ce4a`, the bridge circular-import + gate-only contract
landed in `251003b`, and the package layout was rationalized into
`retrieval/`, `index/`, `evals/`, and `core/` subpackages (`ce16bbe` →
`921ac33`). F4 produced a re-tag proposal for two RAG-weak gates
(`86cd21f`). Wave 1 also planted the seed of the eval baseline by
broadening test assertions (`da5fb14`, `cf7fc4b`) and adding regression
tests that initially shipped under `xfail` markers (`4670991`) and were
unxfail'd once F1+F2 landed (`89d50be`).

### Wave 2 (H1-H19): broader fix wave + structural finds

The largest wave. MMR diversity reranking shipped (`3ab0584`,
upgraded to dense-cosine in G-followup `1642f3a`), `prewarm()` arrived
for service-init latency budget (`3f93960`), and the `mlgg rag`
orchestration subcommand wrapped `scripts/rag/query.py` (`875a88c`).
H10 codified E1's 12 queries as `scenarios.json` (`e096b7c`), H2
converted `TAG_OVERLAYS` from substring to whole-token matching
(`b3a8c47`), and H19 ran a self-audit of the RAG → synthesis-LLM loop
with RICH / WEAK / ZERO scenarios (full report at
`/tmp/H19_rag_llm_loop_eval.md`). H19's findings shipped as the
weak-match hedge (`be9e2d0`) and same-paper marker (`7788b7f`). H14
re-ran E1 and found gate-anchored mode now hit P@5 = 0.792, +0.075
over the E1 free-text baseline (full report at `/tmp/H14_eval_delta.md`).

### Wave 3 (G1-G10): post-Wave-2 followup wave

G2 split the `reproducibility` keyword in the backfill map
(`342e70b`), G3 hardened cache signals (`2339e64`), G8 found the BM25
class-of-failures bug — a 2-character token filter was eating canonical
codes like `MLGG-E01` (`c542240`, full diag at `/tmp/G8_bm25_diagnostic.md`),
and G10 routed subprocess echo to stderr (`ee292c3`). Pre-push hook
caught README drift locally (`2128a6a`).

### Wave 4 (H1-H18): hedges + measurement-path repair

Off-MLGG-scope low-confidence hedge landed (`39f5a81`), the eval
harness was switched to default `--mode hybrid` to match production
(`caaa7a0`, the W3 measurement-path fix), and a reproducible eval
script (`run_eval.py`) was committed as single source of truth
(`bbab235`). MMR floor was raised to 0.88 so MMR only penalizes
near-duplicates rather than topical neighbors (`a5ada09`, W2 q9
regression diag at `/tmp/W2_q9_regression_diagnosis.md`). The W3 BM25
IDF-overanchoring investigation (`/tmp/W3_bm25_idf_diagnosis.md`)
concluded H14's alleged regressions were a measurement-system artifact,
not a real regression — see "ghost regression" anti-pattern below.

### Wave 5 (W1-W5): metric primary + baseline freeze

Switched primary metric from `tag_precision@K` to `hit@K` with a
coverage_rate companion (`1dacc98`, A2+A4 findings). Re-baselined
`TestLiveRetrievalQuality` (`424d37a`), committed the authoritative
post-Wave-5 hybrid baseline snapshot (`8be5253`), and shipped the
A4 ghost-improvement coverage regression CI gate (`aaba296`).

### Wave 6 (W1-W3): off-modality denylist hedge

Shipped the off-MLGG-modality denylist hedge (`bb5cbaa`, W7P2
ships-W1) which short-circuits queries that BGE happily embeds but
that have nothing to do with ML governance ("music", "sailing",
"woodworking" probes).

### Wave 7 (W1-W10 + P-track): audits + remaining cleanup

W7-P1 found 19 of 30 scenarios returning zero hits — 15 were silently
dropped by `run_eval.py` because they lacked a `query_text` field and
the harness short-circuited empty queries before hitting retrieval
(`976218a`, diag `/tmp/W7P1_zero_hit_diagnosis.md`). Fix: synthesize
query from gate + failure codes when missing, matching the
`gate_rag_bridge._synthesize_query` production path. W7-P4 audited
tag overlap across all 49 canonical patterns and found 45 of 49 DEAD
(<5% of within-CP pairs share even one tag), full results at
`/tmp/W7P4_all_cp_fragmentation.md`. W7-P0 lowered the `tag_overlap`
threshold to >=1 shared as a partial mitigation (`9e6391c`). W7-P8
covered defensive branches in `gate_rag_bridge` (`7e9596d`), W7-P9
routed `validate` status messages to stderr (`9127345`), and W7-P5
re-generated the post-Wave-5 baseline after the W7-P1
query-synthesis fix (`889b0ec`).

### Wave 8 (W1-W9): closeout + provenance

W8-W5 normalized MMR top-1 score to `lam * relevance` so the
provenance JSON matches the displayed ranking (`81115c5`). W8-W9
(this document) is the retrospective.

## Architecture before vs after

### Hybrid ranker — 4 signals

```
final_score = w_dense * dense_cosine          (BGE-large, query-prefixed)
            + w_bm25  * bm25_minmax           (gate-anchored only, 2+ char tokens)
            + w_tag   * tag_overlap_jaccard   (mostly dead — see Open #1)
            + w_sev   * severity_prior        (critical/high/medium/low boost)
```

Paths:
- `scripts/rag/retrieval/dense.py` — BGE-large-en-v1.5 with
  query/passage prefix asymmetry
- `scripts/rag/retrieval/bm25.py` — manifest-driven `TAG_SYNONYMS`,
  whole-token matching, 2+ char filter that no longer eats canonical
  codes (G8 fix `c542240`)
- `scripts/rag/retrieval/hybrid.py` — score fusion, severity boost,
  MMR v2 dense-cosine diversification with floor 0.88

### Cache layer

- `references/retrieval_eval/concerns_embeddings.npz` — KB embeddings
- `kb_hash.txt` — invalidation signal
- Atomic write semantics via `index/cache.py` (extracted in
  `407a8a8`); `prewarm()` helper (`3f93960`, hardened in `2339e64`)
  keeps cold-start within the latency budget covered by
  `tests/test_rag_latency.py`.

### Eval infrastructure

- `scripts/rag/evals/harness.py` — supports `--mode bm25_only|hybrid`,
  defaults to `hybrid` (W3 fix `caaa7a0`).
- `scripts/rag/evals/run_eval.py` — committed reproducible eval entry
  point (W3+W1 `bbab235`). Synthesizes query from gate when
  `query_text` is absent (W7-P1 fix `976218a`).
- `references/retrieval_eval/scenarios.json` — 30 scenarios incl. 3
  off-domain WEAK + 1 empty-query ZERO + 26 gate-anchored.
- `references/retrieval_eval/post_wave7_baseline_hybrid.{md,json}` —
  the committed reference (`8be5253`, regenerated `889b0ec`; renamed
  from `post_wave5_baseline_hybrid` in W8-W1 deep-int to reflect that
  the snapshot now captures post-W7 reality after the query-synthesis
  fix `976218a`).
- Primary metrics: `hit@K` (A2) + `coverage_rate` (A4).

### Hedge layers (governance honesty)

The LLM-side honesty layer in `scripts/core/gate_rag_bridge.py`:

- `_is_weak_match` — fallback-only path + final score < 0.05
  (`be9e2d0`)
- `_is_low_confidence` — dense < 0.72 → hedge (`39f5a81`)
- `_is_off_modality_query` — denylist for off-MLGG-modality queries
  (`bb5cbaa`)
- same-paper marker — annotates concerns from the same paper to
  prevent over-counting (`7788b7f`)

## Open architectural questions

### 1. tag_overlap signal mostly dead

W7-P4 audit: 45 of 49 canonical patterns DEAD (<5% of within-CP pairs
share even one tag), 4 DEGRADED, 0 HEALTHY. W7-P0 lowered the
threshold to >=1 shared as a workaround but the gain was modest. Root
cause from W7-P6: 89.5% of tags are singletons (each appears on
exactly one concern), so within-CP pairs almost never overlap.

**Backlog options**: (a) replace `tag_overlap` with within-CP dense
cosine, (b) canonicalize tags via a curated vocabulary, (c) drop the
signal entirely and reweight.

### 2. Query-driven vs gate-driven eval

`harness.py` + `run_eval.py` default to hybrid (production path), but
`scenarios.json` is 26 gate-driven + 4 free-text. The `query_text`
field added by H10 (`e096b7c`) is underutilized for the gate-driven
26. W7-P1 closed the harness short-circuit, but the deeper divergence
— production has both gate-anchored and free-text users, eval is
biased toward gate-anchored — remains.

**Backlog**: build a query-driven harness that runs the free-text use
case as a first-class citizen, with its own labeled precision target.

### 3. Eval metrics

W7-P7 found `tag_precision@K` actively rewards "stay in cluster",
which fights MMR diversification. W5/A2 made `hit@K` primary; W5/A4
added `coverage_rate` as a guard against ghost improvement. 19 of 30
zero-hit scenarios fixed by W7-P1.

**Backlog**: 20-query labeled precision (W8-W2 ships as the
authoritative external benchmark; this doc captures the gap, the
implementation lives in W8).

## Process learnings (5 anti-patterns + mitigations)

1. **Ghost regression** — H14's narrative claimed Q2 / Q12 P@5
   regressed; W3's repro found the deltas not reproducible against
   harness HEAD. Likely cause: H14 measured a different metric or
   mutated state mid-run. **Mitigation**: reproducible eval scripts
   committed (`bbab235`), authoritative baseline JSON committed
   (`8be5253`), CI gate on coverage regression (`aaba296`).
2. **Ghost improvement** — A4 found a coverage-rate drop that looked
   like an improvement on the primary metric. **Mitigation**:
   `coverage_rate` companion metric + CI guard so improvements that
   are silent failures fail loudly.
3. **Measurement-system mismatch** — A2 surfaced that
   `tag_precision@K` penalizes the MMR behavior we explicitly want.
   **Mitigation**: `hit@K` is now primary; `tag_precision@K` is
   diagnostic only.
4. **Premise verification** — H4 and H12 are cases where the agent
   halted because my plan's premise was wrong (e.g. "this regression
   exists" — it didn't). **Mitigation**: trust agent halts; require
   a repro before fix work proceeds.
5. **git commit -o is not race-safe** — F1 and F2 collided on the
   same file; P3 absorbed without surfacing the conflict.
   **Mitigation**: hunk-level isolation for parallel agents, or
   explicit file ownership in the orchestrator dispatch.

## Commit timeline (~78 entries, chronological, grouped by wave)

```
Pre-wave / KB ingestion (Wave 2026-05-13 carryover)
  62a89ad  test(stress_gate_cli): tighten TestAllScriptsHelp
  d8e836b  data(wave-2026-05-13): discovery + extraction + audit
  c617ce3  data(kb): merge extraction-wave-2026-05-13 — 49 NC papers
  c96d795  fix(kb): remap 100 invalid gate refs + re-baseline
  c3c5ba7  data(qa-wave-2026-05-13): 25-agent KB QA outputs
  a5342c2  fix(kb): apply qa-wave-2026-05-13

Initial RAG layer (10-agent build wave)
  da5fb14  fix(tests): broaden baseline-concern retrieval
  cf7fc4b  fix(tests): pre-emptively broaden ppv/sensitivity
  664ee69  feat(rag): dense vector RAG layer over peer-review-kb
  769034c  fix(rag): ruff F401 unused imports
  53de788  fix(drift): enforce scripts/rag/ count parity
  1fadaf9  perf(rag): add BGE query-prefix
  9dd6fab  fix(rag): label author_response as "(as reported)"
  0c6f5f5  feat(rag): wire real BM25 _score into hybrid ranker
  25b222c  fix(rag): declare sentence-transformers optional dep

Wave 1 — F1-F5
  ce16bbe  refactor(rag): scaffold retrieval/ index/ eval/
  727e0d6  refactor(rag): rename eval/ -> evals/
  73c76ba .. 921ac33  refactor: 10 layout commits
  251003b  fix(rag): break circular import
  830ce4a  fix(rag): 4 hybrid-ranker scoring bugs
  4b25540  docs(rag): Known Limitations subsection
  4670991  test(rag): regression tests (xfail)
  89d50be  test(rag): remove xfail markers
  6bc86eb  fix(drift): bump tests 133→134
  bc9c8c3  docs(rag): clean up subpackage docstrings
  86cd21f  feat(kb): F4 re-tag proposal

Wave 2 — H1-H19
  3f93960  feat(rag): prewarm()
  3ab0584  feat(rag): MMR diversity reranking
  5fd7844  test(rag): 33-gate coverage regression
  42d5cff  test(rag): latency budget regression
  2128a6a / 10b8d12  infra: pre-push hook
  875a88c  feat(orchestration): mlgg rag subcommand
  e096b7c  feat(evals): codify E1's 12 queries
  e1cfb7d  refactor(evals): scenarios.json schema drift
  8a00ea1  docs(readme): link Known Limitations
  a0aa014  docs(rag): symbolic anchors in TROUBLESHOOTING
  69f06ca  test(bm25): manifest-driven TAG_SYNONYMS
  b3a8c47  refactor(review): TAG_OVERLAYS whole-token
  6e180d0  fix(drift): bump tests 138→144
  be9e2d0  feat(bridge): hedge weak-match concerns
  7788b7f  feat(bridge): mark same-paper concerns
  da0d0d9  feat(evals): WEAK/ZERO scenarios

Wave 3 — G1-G10
  c03c69e  fix(drift): bump tests 134→138
  4ad3fb2  infra: widen readme-stats-drift hook
  c542240  fix(rag): BM25 class-of-failures (G8)
  342e70b  fix(review): split 'reproducibility' keyword (G2)
  1642f3a  feat(rag): MMR v2 dense embedding cosine
  2339e64  fix(rag): prewarm probe + cache hardening (G3)
  fa56622  test(kb): schema validation
  ee292c3  fix(orchestration): subprocess echo to stderr
  7d8c585  docs(rag): RAG_TROUBLESHOOTING.md

Wave 4 — H1-H18 (hedges + measurement)
  a5ada09  fix(rag): MMR_COSINE_FLOOR=0.88
  bbab235  feat(evals): reproducible eval script
  39f5a81  feat(bridge): low-confidence hedge
  caaa7a0  fix(evals): harness defaults to hybrid
  79363a5  fix(ci): repair 4 reds from Wave 4

Wave 5 — W1-W5 (metric primary)
  1dacc98  feat(evals): hit@K primary + coverage_rate
  424d37a  test(evals): re-baseline after A2
  8be5253  evals: authoritative post-Wave-5 baseline
  bef754a  fix(drift): bump tests 146→147

Wave 6 — W1-W3 (off-modality)
  bb5cbaa  feat(bridge): off-MLGG-modality denylist

Wave 7 — W1-W10 + P-track
  aaba296  test(evals): A4 ghost-improvement CI gate
  9127345  fix(mlgg): validate status to stderr (W7-P9)
  976218a  fix(evals): synthesize query from gate (W7-P1)
  7e9596d  test(bridge): defensive branches (W7-P8)
  9e6391c  fix(rag): tag_overlap threshold >=1 (W7-P0)
  15841a0  fix(drift): bump tests 147→150
  889b0ec  evals: regenerate post-Wave-5 baseline

Wave 8 — W1-W9 (closeout)
  81115c5  fix(rag): normalize MMR top-1 score (W8-W5)
  (this doc)  docs(rag): 7-wave overview narrative (W8-W9)
```

## Maintainer notes

- Re-run `python3 scripts/rag/evals/run_eval.py --mode hybrid` to
  produce a baseline diff against `post_wave7_baseline_hybrid.json`.
  CI guards on coverage regression (A4 gate).
- See `docs/RAG_TROUBLESHOOTING.md` for symptom → fix mapping
  (symbolic anchors added by H8 deep-int).
- See `docs/KB_TAG_STYLE_GUIDE.md` for tag conventions; the
  fragmentation problem in Open #1 needs this guide's authority
  before any large-scale recanonicalization.
- Diagnosis docs in `/tmp/` (E1, E5, G8, H14, H19, W2, W3, W7P1,
  W7P4, W7P8) are the load-bearing forensic record. Persist them
  into `docs/diagnostics/` before the next wave or risk losing the
  rationale.
- When orchestrating parallel agents on this layer, dispatch with
  explicit file ownership — `git commit -o` did not save us from
  F1/F2 colliding on the same file.
