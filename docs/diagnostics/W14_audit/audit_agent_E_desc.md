# Audit Agent E — Methodology Honesty Fix (M1)

**Target file**: `references/retrieval_eval/labeled_precision_at_5.json`
**Status**: DRAFT diff only (NEVER #1 — agent must not write to `references/*.json`).
**Apply with**: `cd /Volumes/Seagate/Skill/ml-leakage-guard && git apply /tmp/audit_agent_E_desc.patch` (after user approval).

---

## 1. Defect

- `description` field opens with: *"Human-labeled ground-truth Precision@5 set for the MLGG peer-review RAG..."*
- `labeling_protocol.labeled_by` reveals: `"W8-W2 + W9-A2 (Claude Opus 4.7, 1M context, MLGG agent)"`
- The labels are produced by an LLM agent in self-eval mode, not by human annotators.
- The phrase "Human-labeled ground-truth" is materially misleading and would not survive peer review or a careful internal audit. Any downstream `mean_labeled_P5` figure inherits that framing.

## 2. Description field — before / after

### Before (line 3)

> Human-labeled ground-truth Precision@5 set for the MLGG peer-review RAG (Wave 8 / W2; extended Wave 9 / W9-A2). Built post-Wave-7 (2026-05-17) to address P7 caveat in the eval roadmap: all prior eval metrics use proxy tag-overlap signals, not ground-truth labels. Original W8-W2 set was 20 queries (1 per sub-dimension) which supported aggregate claims only. ... For each query, the top-5 hits at label time were manually inspected and each marked relevant=true/false by whether the concern text DIRECTLY addresses the query intent (not just topical match). Aggregate metric: P@5 = sum(relevant=true)/5; mean_labeled_P5 = mean over queries. ...

### After (proposed)

> LLM-assisted preliminary Precision@5 baseline for the MLGG peer-review RAG (Wave 8 / W2; extended Wave 9 / W9-A2). Labels were produced by Claude Opus 4.7 (1M context) operating in self-eval mode as the MLGG agent — NOT by independent human annotators. This baseline is suitable as a preliminary internal diagnostic and as a longitudinal regression-detection anchor; it is NOT suitable as ground truth for benchmarking the Claude / LLM family that also produced the retrieval pipeline (see labeling_protocol.circularity_warning). Independent human adjudication is required before any external (manuscript, slide, blog) claim about retrieval quality. Built post-Wave-7 (2026-05-17) to address P7 caveat in the eval roadmap: all prior eval metrics use proxy tag-overlap signals, not adjudicated labels. Original W8-W2 set was 20 queries (1 per sub-dimension) which supported aggregate claims only. W9-A2 (2026-05-17) extended to 36 queries (L01-L36) by adding 16 new in-scope queries that bring the 8 highest-stakes governance sub-dimensions (those touching MLGG non-negotiable rules S01, F01, F02, P01, M01, E01, E02 — leakage_split_hygiene, leakage_definition_variable, leakage_temporal_future, preprocessing_split_leakage, split_temporal_validation, model_selection_tuning_leakage, evaluation_uncertainty_quantification, evaluation_calibration) to 3 queries each. The remaining 10 sub-dimensions retain W8-W2's single-query coverage and continue to support aggregate-only claims for now. For each query, the top-5 hits at label time were inspected by the LLM labeler and each marked relevant=true/false by whether the concern text DIRECTLY addresses the query intent (not just topical match). Aggregate metric: P@5 = sum(relevant=true)/5; mean_labeled_P5 = mean over queries (preliminary, LLM-self-eval). Stable IDs (L01..L36) so this set can be diffed forward through future retrieval changes. Off-scope probes (L19, L20) are pinned at P@5=0 — any non-zero return there is a false-positive regression. Do NOT regenerate after retrieval changes — instead append a new file labeled_precision_at_5_v2.json so longitudinal drift is auditable.

**Changes**:
- Drops "Human-labeled ground-truth" → "LLM-assisted preliminary".
- Names the labeler explicitly in the first two sentences (Claude Opus 4.7, self-eval mode).
- States both the legitimate uses (internal diagnostic, longitudinal regression anchor) and the disqualifying uses (benchmarking the same LLM family, external claims).
- Forward-references the new `circularity_warning` field.
- Rephrases "manually inspected" → "inspected by the LLM labeler" — the original phrasing implied a human.
- Tags `mean_labeled_P5` with `(preliminary, LLM-self-eval)` so downstream readers cannot lift the number out of context.
- Preserves all factual content: scope, W8-W2/W9-A2 extension provenance, sub-dimension coverage, off-scope probe handling, append-only versioning rule.

## 3. labeling_protocol section — before / after

### Before (lines 4-12)

```json
"labeling_protocol": {
  "relevance_definition": "...",
  "tie_handling": "...",
  "off_scope_handling": "...",
  "labeled_by": "W8-W2 + W9-A2 (Claude Opus 4.7, 1M context, MLGG agent)",
  "labeled_at": "2026-05-17",
  "retrieval_mode_at_label_time": "hybrid (BM25 + dense, post-Wave-7 W7P0 tag_overlap >=1 threshold)",
  "wave_9_extension_note": "L21-L36 added by W9-A2 on 2026-05-17 using identical labeling protocol; existing L01-L20 entries preserved byte-for-byte."
}
```

### After (proposed — adds `circularity_warning`)

```json
"labeling_protocol": {
  "relevance_definition": "...",
  "tie_handling": "...",
  "off_scope_handling": "...",
  "labeled_by": "W8-W2 + W9-A2 (Claude Opus 4.7, 1M context, MLGG agent)",
  "labeled_at": "2026-05-17",
  "retrieval_mode_at_label_time": "hybrid (BM25 + dense, post-Wave-7 W7P0 tag_overlap >=1 threshold)",
  "wave_9_extension_note": "L21-L36 added by W9-A2 on 2026-05-17 using identical labeling protocol; existing L01-L20 entries preserved byte-for-byte.",
  "circularity_warning": "CRITICAL: The labeler (Claude Opus 4.7, MLGG agent) is from the same model family that produced the retrieval pipeline being evaluated. Same-family relevance judgements share systematic blind spots with the retriever — both may agree a topically-adjacent hit 'directly addresses' the query when an independent human reviewer would not. mean_labeled_P5 derived from this file is therefore an OPTIMISTIC self-eval estimate, not an unbiased Precision@5 measurement, and is NOT suitable as a benchmark of the Claude / LLM family generally or of this MLGG RAG specifically for publication-grade claims. Acceptable downstream uses: (a) internal regression detection across retrieval-pipeline changes (deltas are still informative even if absolute level is biased); (b) qualitative error analysis of obvious miss patterns. Unacceptable downstream uses without independent human adjudication: (a) absolute Precision@5 figures in a manuscript, slide deck, blog post, or external report; (b) head-to-head retriever comparison framed as ground truth; (c) any claim of 'human-validated' or 'gold-standard' quality. Adjudication plan: a held-out independent reviewer (non-LLM, ideally a clinical-ML methodologist outside the MLGG project) should re-label a stratified random sample (>=30%) of L01-L36 blind to LLM labels; agreement / disagreement rates must be reported alongside any external use of the P@5 numbers."
}
```

All existing keys are byte-for-byte preserved. Only addition is the trailing `circularity_warning` key plus the required comma on the prior line.

## 4. Rationale — why this matters for publication-grade claims

**Claim integrity.** The aggregate figure derived from this file — `mean_labeled_P5 = 0.639` — is on a direct path into manuscript framing, slide decks, and the MLGG eval roadmap. As currently described, that number reads as a *human-labeled ground-truth Precision@5 of 0.639 on a 36-query benchmark*. That is the phrasing a co-author, a slide-builder, or a future agent will pattern-match on. The actual provenance is that an LLM (Claude Opus 4.7) generated retrieval rankings, then the *same* LLM family, instantiated as the MLGG agent, decided which of its own top-5 returns were "directly relevant". That is a self-eval, not a ground truth, and the number can only ever be an upper bound: anywhere the retriever and the labeler share a blind spot (e.g., both treat "no external validation" as relevant to a "tuning on the test set" query), the labeler will rubber-stamp the retriever's miss. Peer review at any of the target venues (Nature Methods, JAMA, npj Digital Medicine, journals routinely cited in the MLGG roadmap) will catch this on first read, and the correct response then is not a clarification but a retraction of the claim — exactly the failure mode the MLGG project is built to prevent in *other people's* manuscripts.

**Governance consistency.** MLGG's non-negotiable rules include M01 ("test set not used for tuning") and E01/E02 ("uncertainty quantification, calibration assessment required"). Publishing a 0.639 self-eval figure as ground truth is the retrieval-evaluation analogue of M01: the evaluator and the system-under-test share state, and the resulting number is biased toward the system. For the project to credibly enforce these standards on third-party manuscripts, its own retrieval-eval artifacts must visibly meet them. The corrected description plus the `circularity_warning` field preserve every bit of work already done (the 36 labeled queries remain useful as a longitudinal regression anchor and as a structured seed for the eventual human re-label), while moving the artifact from "misleading" to "honest preliminary baseline with an explicit adjudication plan". That is the minimum bar before any P@5 number from this file appears outside the repo.
