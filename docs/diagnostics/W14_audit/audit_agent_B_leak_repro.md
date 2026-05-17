# Audit Agent B — L27 retrieval failure repro

**Query**: `"standard scaler normalization fit on full dataset before split"`
**Dimension**: `preprocessing_split_leakage` · **Gate**: `split_protocol_gate` · **Codes**: `MLGG-P01`
**Labeled P@5**: **0.0 / 5** (zero relevant in top-5) — confirmed.

## 1. Production RAG status & top-5 reproduction

### 1a. Hybrid path (dense + BM25) — cannot live-run

The full hybrid ranker (`scripts/rag/retrieval/hybrid.py` → `dense.vector_search`) requires
`sentence_transformers`, which is NOT installed in `/Volumes/Seagate/Skill/.venv`. Per repo
NEVER #4 (no pip-install), I cannot live-execute that path. However, the labeled top-5 in
`references/retrieval_eval/labeled_precision_at_5.json` IS the captured production retrieval
at label time (W9-A2, today, 2026-05-17), so it serves as the authoritative top-5 snapshot.

### 1b. Labeled top-5 from `labeled_precision_at_5.json` (production hybrid output)

| Rank | concern_id          | Why labeled irrelevant                                                                 |
|------|---------------------|----------------------------------------------------------------------------------------|
| 1    | `PR-EXP-0155-C03`   | Calibration-sample reuse — adjacent split-hygiene, NOT fit-before-split                |
| 2    | `PR-EXP-0200-C02`   | Empirical split-size reasoning, not preprocessing-before-split                          |
| 3    | `PR-EXP-0084-C08`   | Hyperparameter-search clarity, generic leakage worry                                    |
| 4    | `PR-EXP-0097-C13`   | Split-ratio sensitivity, not preprocessing-before-split                                 |
| 5    | `PR-EXP-0160-C09`   | Which cohort is train vs val, not preprocessing leakage                                 |

All five are gate-relevant (`split_protocol_gate`), zero are MLGG-P01 ("all `fit()` only on
training set") — the actual non-negotiable rule the query asks about. **Failure confirmed.**

### 1c. BM25-only path (what the gate framework actually consumes via
`scripts/core/_gate_framework.py` line 274) — LIVE-RUN reproduced:

```
retrieve_for_failure('split_protocol_gate', ['MLGG-P01'], limit=5)
  1. PR-EXP-0155-C03  HIGH      score=11  calibration_leakage, fit_inflation
  2. PR-072-C01       CRITICAL  score=8   train_test_overlap (phenotype correlation)
  3. PR-109-C01       CRITICAL  score=6   sample_overlap (biobank reuse)
  4. PR-111-C01       CRITICAL  score=4   test_set_reuse / model_selection_on_test
  5. PR-113-C01       CRITICAL  score=4   smote_before_split / cv_strategy_unspecified
```

Still 0/5 on "scaler/normalization fit-before-split". PR-113-C01 (`smote_before_split`) is
the closest sibling — same *pattern* (preprocess-on-pooled-data-before-split) but applied to
synthetic resampling, not scaling. BM25 reranks against the code string `MLGG-P01` and the
gate tag — neither of which lexically intersects "scaler / normalize" in KB tag space.

## 2. SHOULD the KB have a match? Vocabulary scan of `peer-review-kb.json` (335 papers)

Searched all 1,000+ concerns for substrings in {`scaler`, `scaling`, `normaliz*`,
`standardiz*`, `z-score`, `min-max`, `fit on full/all/entire`, `preprocess.*before split`}.

**13 concerns mention normalization/scaling/standardization vocabulary. NONE describe
the canonical MLGG-P01 failure (fitting a scaler on the full pool before train/test split).**

Closest semantic candidates (still off-target):

- `PR-EXP-0155-C04` — tag `preprocessing_before_split`, but text is about tile-filtering
  selection bias (non-tumor patch %), not transform-fit before split.
- `PR-EXP-0084-C03` — `rank_normalization` + `preprocessing_complexity`, text complains
  about justification/sensitivity — no split-leak framing.
- `PR-EXP-0109-C08` — z-score normalization of QRS features — amplitude-loss concern, no
  split discussion.
- `PR-003-C03` — imputation of validation cohort, `data_leakage_via_imputation`,
  carries `MLGG-P04`. The ONLY KB entry that names a preprocessing-leakage rule, but it's
  P04 (imputation) not P01 (scaler/transform fit).
- `PR-EXP-0147-C02`, `PR-EXP-0198-C06` — normalization-undocumented in MS / imaging,
  not split-related.

**Counter-evidence — KB-coverage indicators**:

- `mlgg_rules` field across all 1,005 concerns: **MLGG-P01 appears exactly ONCE** —
  on `PR-006-C01`, which is actually about same-dataset GWAS + PRS reuse (overfitting),
  NOT about scaler fit. The single attestation is itself a mis-tag.
- Tag `preprocessing_before_split`: 1 occurrence (`PR-EXP-0155-C04`, off-target).
- 29 concerns gate-tagged `split_protocol_gate`, but none describe scaler/transform fit on
  full data — they cover patient-overlap, temporal split, smote_before_split, single_split.

## 3. Root cause

**KB COVERAGE GAP — primary.** The 335-paper peer-review-kb has near-zero coverage of the
canonical "fit_transform on full data → leak via scaler statistics" failure pattern. Only
sibling forms exist (SMOTE before split, imputation on validation, calibration sample reuse).
The corroboration on the 67-doc lit-KB (TF-IDF top-1 = 0.083) using completely different
vocabulary statistics points the same way: it's not a tokenizer/embedding quirk, the concept
just isn't in either corpus.

**Vocab/embedding miss — secondary contributor.** The KB DOES have ~13 normalization-aware
concerns but none get surfaced because:

1. BM25 reranks on the failure-code string (`MLGG-P01`), and only `PR-006-C01` carries that
   tag — and it's mis-tagged (about GWAS reuse, not scaler fit). So BM25 keyword-overlap
   collapses to the gate-only severity-fallback regime, which is why the top-5 surface
   high-severity split-related but topically off concerns.
2. The hybrid dense leg sees a thin pool (no candidate has both "scaler"-vocab AND a
   `split_protocol_gate` tag), and `CP_TAG_BOOST_DENSE_FLOOR=0.70` then likely suppresses
   any pattern bonus, leaving severity-and-gate fallbacks to dominate.
3. The 29 `split_protocol_gate` concerns are heavily biased toward patient-overlap and
   temporal-split flavours of leakage; preprocessing-time fit-leakage is structurally
   under-represented despite being an MLGG non-negotiable.

So: the **first-order fix is KB coverage** (curate concerns covering scaler / encoder /
imputer / PCA / target-encoding fit-before-split). Until then, the **second-order fix** is
a hand-curated rule-based fallback that bypasses RAG for known-blind queries.

## 4. Patch

`/tmp/audit_agent_B_fallback.patch` — unified diff against `scripts/core/gate_rag_bridge.py`
(NOT applied; per ASK-FIRST rule for gate-adjacent CLI surface).

**Summary**: insert a `_canonical_fallback_concerns(query, gate, codes)` map keyed by
canonical-failure-signatures. When the synthesised query matches any of:

- token set `{scaler|standardize|normalize|z-score|minmax|preprocess|fit}` AND
  `{before|prior|full|entire|all data|split}` (matches L27 verbatim),
- OR `failure_codes` contains `MLGG-P01` AND `gate_name == 'split_protocol_gate'`,
- OR `failure_codes` contains `MLGG-P04` (imputation-before-split sibling),

`rag_context_for_failure` returns a hand-curated concern record (synthetic
`concern_id="MLGG-CURATED-P01-fit_before_split"`, severity CRITICAL, with a paragraph
written from MLGG-P01's text and pointing to PR-003-C03 / PR-113-C01 / PR-EXP-0155-C04
as sibling-evidence). The override fires BEFORE the call to `hybrid_rank`, so it has no
dependency on the BGE stack and works in `sentence_transformers`-less environments. Real
RAG hits, if any, are appended below the curated entry to top_k.

Curated records are tagged `_synthetic_curated=True` + `_match_reasons=["curated_fallback:MLGG-P01"]`
so existing weak-match hedging is bypassed (these are AUTHORITATIVE, not weak) and
downstream consumers can audit / disable via env-var (`MLGG_RAG_DISABLE_CURATED=1`).

Patch does NOT modify any gate CLI interface, does NOT touch `references/*.json`, and
does NOT change `hybrid_rank` itself — pure additive at the bridge layer.
