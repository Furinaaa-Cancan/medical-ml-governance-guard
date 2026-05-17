# RAG Layer Architecture

**Status**: durable maintainer reference. Updated as the system evolves.
**Companion docs**:
- `docs/RAG_TROUBLESHOOTING.md` — symptom → fix mapping
- `docs/RAG_WAVE_1_TO_8_RETRO.md` — frozen wave-by-wave retrospective
- `docs/KB_TAG_STYLE_GUIDE.md` — tag conventions
- `docs/diagnostics/` — load-bearing forensic diagnoses cited by retro

## Component map

```
scripts/rag/
  retrieval/
    dense.py        # BGE-large-en-v1.5 with query/passage prefix asymmetry
    bm25.py         # manifest-driven TAG_SYNONYMS, whole-token, 2+ char filter
    hybrid.py       # score fusion, severity boost, MMR v2 diversification
  index/
    cache.py        # atomic write semantics for embeddings + kb_hash
  evals/
    harness.py      # supports --mode bm25_only|hybrid, defaults to hybrid
    run_eval.py     # reproducible eval entry point, query synthesis fallback
  core/
    gate_rag_bridge.py  # gate → query synthesis + LLM-side hedge layer
  query.py          # CLI wrapped by `mlgg rag` subcommand

references/retrieval_eval/
  concerns_embeddings.npz                # KB embeddings cache
  kb_hash.txt                            # cache invalidation signal
  scenarios.json                         # 30 eval scenarios
  post_wave7_baseline_hybrid.{md,json}   # authoritative baseline (renamed W8-W1)
```

## Hybrid ranker — 4 signals

```
final_score = w_dense * dense_cosine          (BGE-large, query-prefixed)
            + w_bm25  * bm25_minmax           (gate-anchored only, 2+ char tokens)
            + w_tag   * tag_overlap_jaccard   (mostly dead — see Open #1)
            + w_sev   * severity_prior        (critical/high/medium/low boost)
```

### Flow

1. **Query intake**: either free-text or `(gate_id, failure_codes)` tuple.
   `gate_rag_bridge._synthesize_query` builds a query from gate metadata
   when free-text is absent (same path used by `run_eval.py` when a
   scenario lacks `query_text`).
2. **Dense retrieval**: BGE-large encodes the query with the query
   prefix; KB concerns are pre-encoded with the passage prefix and
   cached in `concerns_embeddings.npz`.
3. **BM25 retrieval** (gate-anchored mode only): manifest-driven
   `TAG_SYNONYMS` expansion, whole-token matching, 2+ char filter that
   no longer eats canonical codes like `MLGG-E01`.
4. **Fusion**: min-max normalized BM25 + raw dense cosine + tag overlap
   Jaccard + severity prior, weighted sum.
5. **Diversification**: MMR v2 reranks on dense cosine (not raw score)
   with `MMR_COSINE_FLOOR=0.88`, so MMR penalizes near-duplicates only,
   not topical neighbors. Top-1 score normalized to `lam * relevance`
   so provenance JSON matches displayed ranking.
6. **Hedge gate**: `gate_rag_bridge` inspects the top-K before passing
   to the synthesis LLM; weak/low-confidence/off-modality results
   trigger explicit hedges in the LLM prompt.

## Cache layer

- `references/retrieval_eval/concerns_embeddings.npz` — KB embeddings,
  written by `index/cache.py` with atomic semantics (temp file + rename).
- `kb_hash.txt` — content hash of the KB JSON. Mismatch with the
  embedded hash invalidates the cache and forces re-encode.
- `prewarm()` — loads dense model + cache eagerly at service init so
  first-query latency stays within the budget enforced by
  `tests/test_rag_latency.py`.

## Eval infrastructure

| Component | Path | Role |
|-----------|------|------|
| Harness | `scripts/rag/evals/harness.py` | `--mode bm25_only\|hybrid`, defaults to `hybrid` (matches production) |
| Reproducible runner | `scripts/rag/evals/run_eval.py` | Single source of truth for baseline diffs; synthesizes query from gate when `query_text` absent |
| Scenarios | `references/retrieval_eval/scenarios.json` | 30 scenarios: 26 gate-anchored + 3 off-domain WEAK + 1 empty-query ZERO |
| Baseline | `references/retrieval_eval/post_wave7_baseline_hybrid.{md,json}` | Authoritative reference for regression diffs |
| Labeled set | `references/retrieval_eval/labeled_*` | 20-query labeled precision target (W8-W2 external benchmark) |

> **W10-T1 note** — local nondeterminism measured at std=0 across N=10
> reruns of `run_eval.py` on macOS-CPU, so single-machine reruns are
> safe for diffing. Cross-machine variance (different OS, BLAS, or
> torch builds) is untested; if a baseline diff comes from a different
> machine, treat small deltas with suspicion.

**Primary metrics**: `hit@K` (W5/A2) + `coverage_rate` companion (W5/A4).
`tag_precision@K` is retained as a diagnostic-only metric — it actively
rewards "stay in cluster" behavior that fights MMR diversification, so
it must not be used as a primary signal.

### CI gates on eval

- Coverage regression gate (W5/A4, commit `aaba296`) — fails CI if
  `coverage_rate` drops vs the committed baseline. Catches the
  "ghost improvement" anti-pattern where the primary metric goes up
  because more queries silently return zero hits.
- README stats drift hook (pre-push) — keeps documented eval counts
  in sync with `scripts/diagnostics/check_readme_stats.py`.

## Hedge layers (governance honesty)

The LLM-side honesty layer in `scripts/core/gate_rag_bridge.py`
inspects retrieval output before prompt construction:

| Hedge | Trigger | Effect |
|-------|---------|--------|
| `_is_weak_match` | fallback-only path AND final score < 0.05 | LLM prompt warns "weak retrieval; do not over-cite" |
| `_is_low_confidence` | dense cosine < 0.72 | LLM prompt marks retrievals as low-confidence |
| `_is_off_modality_query` | query matches off-MLGG denylist (music, sailing, woodworking, ...) | short-circuit; explicit "out of scope" response |
| same-paper marker | multiple top-K concerns share `paper_id` | annotates so LLM does not double-count one paper as multiple sources |

These exist because BGE embeddings are happy to return *something* for
any query, including off-domain probes. Without these hedges the
synthesis LLM would confidently cite irrelevant KB entries.

## Open architectural questions

### 1. `tag_overlap` signal mostly dead

`docs/diagnostics/W7P4_all_cp_fragmentation.md` audit: 45 of 49
canonical patterns DEAD (<5% of within-CP pairs share even one tag),
4 DEGRADED, 0 HEALTHY. W7-P0 lowered the threshold to >=1 shared as
a workaround but the gain was modest.

Root cause (`docs/diagnostics/W7P6_singleton_tags_audit.md`): 89.5% of
tags are singletons (each appears on exactly one concern), so within-CP
pairs almost never overlap.

**Backlog options**:
(a) replace `tag_overlap` with within-CP dense cosine,
(b) canonicalize tags via a curated vocabulary (requires
    `docs/KB_TAG_STYLE_GUIDE.md` authority),
(c) drop the signal entirely and reweight `w_dense` / `w_bm25` / `w_sev`.

### 2. Query-driven vs gate-driven eval divergence

`harness.py` + `run_eval.py` default to hybrid (production path),
but `scenarios.json` is 26 gate-driven + 4 free-text. The `query_text`
field added in Wave 2 is underutilized for the 26 gate-driven scenarios.
W7-P1 closed the harness short-circuit (empty `query_text` no longer
silently skips), but the deeper divergence — production has both
gate-anchored and free-text users, eval is biased toward gate-anchored —
remains.

**Backlog**: build a query-driven harness that runs the free-text use
case as a first-class citizen, with its own labeled precision target.
See `docs/diagnostics/W7P1_zero_hit_diagnosis.md`.

### 3. Eval-metric selection

`tag_precision@K` actively rewards "stay in cluster" behavior that
fights MMR diversification (`docs/diagnostics/W7P7_e2_redo.md`).
`hit@K` is now primary; `coverage_rate` companion guards against
ghost improvement. 19 of 30 zero-hit scenarios were fixed by W7-P1's
query-synthesis fallback.

**Backlog**: the 20-query labeled precision benchmark (W8-W2) is the
authoritative external check; keep it pinned against the
post-Wave-5 baseline as the system evolves.

### 4. KB provenance (LLM-generated content)

The disease KB and parts of the concern KB are LLM-synthesized
(`docs/diagnostics/W8W10_disease_kb_provenance_audit.md`). Before
publication-grade claims rely on KB content, every entry needs:
(a) clinical review by a domain expert, (b) a guideline citation
chain that traces back to TRIPOD+AI 2024 / PROBAST+AI 2025 / a
named clinical guideline.

**Backlog**: provenance schema in `references/peer-review-kb/` that
distinguishes `source: llm_generated` from `source: guideline_cited`,
plus a CI gate that prevents `llm_generated` entries from being
cited in published gate reports without an explicit override.

### 5. Does the 4-signal hybrid ranker actually beat bm25_only?

W10-T2 ran `run_eval.py --mode hybrid` vs `--mode bm25_only` on
`scenarios.json` and found hybrid *worse* than bm25_only on the
primary tag-quality metric: mean_tag_precision@5 = 0.353 (hybrid) vs
0.436 (bm25_only), a delta of −0.083. The per-wave improvements
recorded in `RAG_WAVE_1_TO_8_RETRO.md` were measured against earlier
hybrid baselines, not against a bm25_only floor, so we never noticed
that the floor was higher.

W11-I1 ran the per-signal ablation
(`scripts/rag/evals/ablation_signal_drop.py`, n=30 scenarios). Initial
result is surprising: **dense is the dilutor**, not `tag_overlap` or
severity. Removing dense (`hybrid_no_dense`) lifts mean_tag_p@5 to
0.447 — above both hybrid_all (0.353) and bm25_only (0.436). Dropping
`tag_overlap`, severity, or MMR each moves the metric by <0.01. The
earlier suspicion that singleton tags (Open #1) were the problem here
turns out to be wrong on *this* metric — they hurt within-CP signal
but they are not why hybrid loses to BM25.

Interpretation worth verifying before re-weighting: BGE dense matches
on topical neighbors that share the query's domain but not its tag
cluster, so on `tag_precision@K` they look like misses. This means
Open #3's caveat about `tag_precision` rewarding stay-in-cluster is
load-bearing here — `hit@K` may tell a different story and should be
re-checked before any production weight change.

**Backlog options** in priority order:
(a) re-run the ablation against `hit@K` / `coverage_rate` to confirm
    the dense-dilutor finding is not an artifact of `tag_precision`;
(b) if confirmed, re-weight to lower `w_dense` (or split: dense for
    recall, BM25 for precision) and re-baseline;
(c) gate hybrid behind a per-query confidence check and fall back to
    bm25_only when hybrid disagrees materially with BM25's top-K.

Operational fallback: `--mode bm25_only` remains a legitimate choice
today for tag-quality-sensitive workloads.

## Maintainer playbook

- **Baseline regen**: `python3 scripts/rag/evals/run_eval.py --mode hybrid`
  produces a diff against `post_wave7_baseline_hybrid.json`. CI gate
  blocks coverage regressions.
- **Cache invalidation**: bump `kb_hash.txt` (or let `index/cache.py`
  detect KB JSON content change). `prewarm()` will re-encode on next
  service init.
- **New hedge**: add to `gate_rag_bridge.py` alongside existing
  `_is_*` helpers; cover defensive branches per W7-P8 pattern;
  re-run `run_eval.py` to verify no coverage regression.
- **Parallel-agent dispatch**: `git commit -o` is not race-safe.
  Dispatch agents with explicit file ownership in the orchestrator
  rather than relying on `-o` to filter out conflicting unstaged
  changes. See retro anti-pattern #5.
