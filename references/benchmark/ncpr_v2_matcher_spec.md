# NCPR v2 — Semantic Matcher Specification (empirical-sweep variant)

**Status**: draft, pre-registration pending Phase 3 completion
**Owner**: NCPR Benchmark wave (W23)
**Reference implementation**: `scripts/rag/evals/ncpr_diagnostic_sweep.py` (W23-C1, forthcoming)
**Supersedes**: `ncpr_v1_matcher_spec.md` (cosine=0.70 frozen pre-registration)
**Companion docs**: `ncpr_v1_matcher_spec.md` §3-5 (match types, de-dup)

---

## 1. Why v2

v1 pre-registered a cosine threshold of 0.70 borrowed from generic STS
benchmarks. The W22-T4 self-challenge flagged this as rigor theater: a
threshold never validated on the NCPR corpus is not a defensible operating
point, even when frozen ahead of time. Freezing the wrong number is not
more rigorous than tuning the right one — it is just harder to fix.

v2 replaces the borrowed threshold with a small labeled mini-set, a
diagnostic sweep on that mini-set, and a deliberate operating-point choice
that is then frozen for v2.0. The freeze still gives external defensibility;
the empirical step removes the "where did 0.70 come from" footgun.

## 2. Three-phase protocol

### Phase 1 — labeled mini-set

- **Sampling**: 30 reviewer concerns × 30 candidate MLGG flags = **900
  pairs**, drawn stratified across the dimensions used in the v1 holdout
  (see `ncpr_v1_holdout_criteria.md`). Concerns sampled without
  replacement; flags sampled to span the full cosine range expected on
  this corpus (oversample 0.40-0.85 to inform the threshold question).
- **Labels**: a single W23 reviewer hand-labels each pair as `match` or
  `no_match`. The label is independent of any MLGG-emitted `code` /
  `category` agreement — it only judges whether the flag's evidence text
  and the concern text describe the **same underlying issue**.
- **Inter-rater check** (deferred to v2.1): a second reviewer relabels
  a 100-pair random subset; report Cohen's kappa. If kappa < 0.6 the
  mini-set is discarded and rebuilt with a labeling rubric revision.
- **Storage**: `references/benchmark/ncpr_v2_mini_set.jsonl`, one pair per
  line, schema `{concern_id, flag_id, concern_text, flag_evidence,
  cosine, label, labeler, label_ts}`.

### Phase 2 — diagnostic sweep

- **Script**: `scripts/rag/evals/ncpr_diagnostic_sweep.py` (W23-C1).
- **Thresholds swept**: `{0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85,
  0.90}`. Same BGE-small-en-v1.5 embedder as v1; same
  lowercase + whitespace-collapse normalization.
- **Outputs per threshold**: precision, recall, F1, support (n labeled
  pairs that fire type-3 at this threshold), and a confusion matrix.
  Numbers reported with Wilson 95% CIs since support is small.
- **Sweep is run exactly once** on the frozen mini-set. Re-running with
  any change to the mini-set invalidates Phase 3.

### Phase 3 — freeze

Pick the operating point under **one** of two declared objectives:

1. **F1-max** (default): the threshold with the highest mini-set F1.
   Ties broken toward higher recall.
2. **Recall-favoring** (≥ 0.85): the lowest threshold whose mini-set
   recall is ≥ 0.85, used when the benchmark goal is explicitly "find
   all real reviewer concerns" and downstream consumers will triage
   false positives. The objective MUST be declared in the v2 spec
   changelog **before** the sweep is run, not after seeing the numbers.

The chosen point is hard-coded into the reference matcher. Same
pre-registration rule as v1: matcher MUST refuse to read the threshold
from config in v2 mode.

## 3. Match types (carried from v1)

Unchanged from `ncpr_v1_matcher_spec.md` §3 — precedence order:

1. **exact_code** — `flag.code == g` for some `g in concern.mlgg_gates`.
2. **code_prefix** — `flag.code` starts with `g + "_"` (or equals `g`).
3. **semantic** — cosine ≥ **operating threshold from Phase 3**
   (was 0.70 in v1). See §4 for the length-aware tightening.
4. **category** — diagnostic only; not counted toward precision / recall.

First-firing wins. A pair firing none is not a match.

## 4. Length-aware threshold (new in v2)

Short clinical snippets pack high-density jargon and produce inflated
cosines relative to longer, more diluted text. To partially counter
this:

```
effective_threshold(flag_evidence, concern_text):
    if tokens(flag_evidence) < 15 or tokens(concern_text) < 15:
        return operating_threshold + 0.05
    return operating_threshold
```

Tokenization is whitespace split after the same lowercase + collapse
normalization. The +0.05 bump is itself a v2 design choice (not swept);
it is documented here so it cannot be quietly tuned later.

## 5. De-duplication (carried from v1)

Unchanged from `ncpr_v1_matcher_spec.md` §5:

- `matched_concerns = |{concern_id : exists matching flag}|`
- `matched_flags    = |{flag_id    : exists matching concern}|`

Best-precedence wins per flag-concern pair; multiple flags hitting one
concern still count as one matched concern.

## 6. Embedding model

BGE-small-en-v1.5, the current production embedder. Frozen for v2.

## 7. Pre-registration scope

Once Phase 3 lands, the following are frozen for v2.0:

- the labeled mini-set (its 900 pairs and their labels),
- the chosen operating threshold,
- the length-aware +0.05 bump,
- the match-type ordering and de-dup rules,
- the embedding model.

Any change to any of the above requires a v3 spec, a new mini-set, and a
re-run of the full benchmark. v2 numbers stay on record.

## 8. What this enables

- **Empirical defensibility for external claims.** "We chose 0.65 because
  it maximizes F1 on a held-aside 900-pair labeled mini-set drawn from
  the same corpus" is a publishable answer; "we picked a round number
  from prior STS work" is not.
- **A documented mini-set artifact** that third parties can re-label or
  contest, separately from the full benchmark labels.

## 9. What this still doesn't fix

- **BGE-small-en-v1.5 is not trained on clinical text.** A
  biomedical-domain sentence encoder (e.g., MedSBERT, BioLORD,
  PubMedBERT-sentence) might shift the precision-recall curve enough
  that no general-purpose threshold is competitive. Out of scope for
  v2; **v3 candidate**: re-run Phases 1-3 with a clinical encoder and
  compare AUC of the sweep, not just the chosen point.
- **N=30 concerns is small.** Phase 1's mini-set gives stable F1 only
  to roughly ±0.05 (Wilson CI on ~100 positives). v2.1 should expand to
  60+ concerns if budget allows.
- **Single-labeler bias.** Phase 1 deferral of inter-rater check means
  the v2.0 threshold reflects one reviewer's match definition. Kappa
  in v2.1 either validates or forces revision.
- **The mini-set is itself a corpus draw.** Reviewer / journal / year
  skew in the underlying NCPR holdout propagates into the chosen
  threshold. No fix at this layer.

## 10. Versioning

- v2 = this document. Frozen at Phase 3 completion.
- Cosmetic edits (typos, clarifications that do not change behavior)
  allowed in place with a changelog note.
- Behavioral changes (match types, threshold, length rule, embedder,
  de-dup, mini-set) require v3.

## 11. Changelog

- 2026-05-17 — v2 drafted (W23-B4, T4 followup); Phase 3 freeze pending
  W23-C1 sweep script and mini-set labeling.
