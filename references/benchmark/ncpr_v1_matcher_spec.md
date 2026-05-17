# NCPR v1 — Semantic Matcher Algorithm Specification

**Status**: pre-registered (v1, frozen)
**Owner**: NCPR Benchmark wave (W22)
**Reference implementation**: `scripts/rag/evals/ncpr_matcher.py` (W22-X1)
**Companion docs**: `references/benchmark/ncpr_v1_protocol.md`, `ncpr_v1_metrics.md`

---

## 1. Why a matcher

MLGG emits structured concern flags shaped as:

```json
{"code": "<gate_code>", "severity": "<low|med|high>",
 "category": "<dimension>", "evidence_text": "<free text span>"}
```

Reviewer concerns harvested from the NCPR corpus are free text with
optional reviewer-supplied gate hints. To compute precision / recall of
MLGG against real reviewer feedback we need a **deterministic** function

```
match(mlgg_flags, reviewer_concerns) -> List[(flag_id, concern_id, match_type)]
```

that any third party can replay bit-for-bit from the same inputs. This
document specifies that function. It is **pre-registered**: the algorithm,
threshold, and tie-breaking rules below are frozen for NCPR v1. Any change
requires a new ADR plus a benchmark version bump (`ncpr_v2`).

## 2. Inputs

- `mlgg_flags`: list of flag dicts as above; `code` and `category` required,
  `evidence_text` optional (may be empty string).
- `reviewer_concerns`: list of concern records of the form
  ```json
  {"concern_id": "...", "concern_text": "...",
   "dimension": "<one of N>", "mlgg_gates": ["gate_a", "gate_b"]}
  ```
  where `mlgg_gates` may be empty when the reviewer did not pre-label a
  gate.

## 3. Match types, ranked by precision

Each MLGG flag is evaluated against each reviewer concern in this order
and assigned the **first** type that fires. Lower-numbered types dominate.

1. **Exact code match** — `flag.code == g` for some `g in concern.mlgg_gates`.
   Highest precision; only fires when the reviewer pre-labeled the gate.
2. **Code-prefix match** — `flag.code` starts with `g + "_"` (or equals `g`)
   for some `g in concern.mlgg_gates`. Example:
   `code=clinical_metrics_ppv_too_low` matches `mlgg_gates=[clinical_metrics_gate]`
   after stripping the trailing `_gate` suffix from the gate name. Prefix
   comparison is lowercase, ASCII, underscore-separated.
3. **Semantic match** — cosine similarity of BGE-small-en-v1.5
   embeddings of `flag.evidence_text` vs `concern.concern_text` is
   `>= 0.70`. Both strings are stripped, lowercased, and collapsed on
   internal whitespace before embedding. Empty strings on either side
   disqualify this type.
4. **Category match** — `flag.category == concern.dimension`. Weakest;
   **not counted** toward precision / recall. Used only to compute the
   `category_coverage` diagnostic metric in `ncpr_v1_metrics.md`.

A pair that fires none of types 1-4 is **not** a match.

## 4. Cosine threshold rationale (0.70)

The 0.70 cutoff is borrowed from prior text-similarity work using the same
BGE-small-en-v1.5 model — empirical sweeps in retrieval and STS benchmarks
place 0.65-0.75 as the operating range where precision and recall cross
for short clinical / technical snippets. We pick 0.70 as a round
mid-range value **before** seeing NCPR results to avoid post-hoc tuning.

**Pre-registration rule**: the threshold is frozen for v1. Sweeping it on
NCPR labels and reporting the best number would invalidate the benchmark.
The reference implementation MUST hard-code `0.70` and refuse to read it
from config in v1 mode.

## 5. De-duplication

If multiple MLGG flags match the same reviewer concern via any rule, the
pair `(concern_id)` counts as **one** matched concern for recall, and each
participating flag counts as **one** matched flag for precision — but
duplicate flags pointing at the same concern do **not** inflate either
numerator. Concretely:

- `matched_concerns = |{concern_id : exists matching flag}|`
- `matched_flags    = |{flag_id    : exists matching concern}|`

This prevents a verbose gate that emits three near-identical flags from
scoring 3x on a single reviewer comment.

## 6. Failure modes the implementation MUST handle

- **Flag with empty `evidence_text`** — types 1 and 2 still apply;
  type 3 is skipped for that flag.
- **Concern with empty `mlgg_gates`** — types 1 and 2 are skipped for that
  concern; type 3 may still fire.
- **Embedding service unavailable** — fail loud. The matcher MUST raise
  and the eval MUST abort; silently dropping type-3 matches would
  understate recall without warning. No fallback to lexical similarity in
  v1.
- **Unicode / casing** — gate codes and category labels are ASCII-normalized
  lowercase before comparison; embedded text is lowercased and
  whitespace-collapsed before embedding (no stemming, no stop-word removal).

## 7. Testability

The reference implementation MUST ship unit tests covering:

- one synthetic flag + concern firing each match type in isolation,
- a flag that would qualify under both types 1 and 3 is recorded as
  type 1 (precedence test),
- de-duplication: 3 flags vs 1 concern -> `matched_concerns == 1`,
  `matched_flags == 3`,
- empty `evidence_text` and empty `mlgg_gates` edge cases,
- embedding-service exception propagates (not swallowed).

Tests use a stub embedder returning fixed vectors so they are
deterministic and offline.

## 8. Comparison to the current retrieval eval

The existing retrieval eval (`references/retrieval_eval/`) scores MLGG
against **author-curated `expected_tags`** — gates the case author
expected the system to fire. NCPR scores MLGG against **real reviewer
concerns** harvested from published peer review. Both are useful; they
have different bias profiles:

| Axis | retrieval eval | NCPR v1 |
|---|---|---|
| Ground truth source | case author | external reviewer |
| Coverage | only gates author anticipated | whatever reviewers raised |
| Bias risk | author teaches to the test | reviewer corpus skew (journal, year, specialty) |
| Update cost | cheap (author edits tags) | expensive (re-harvest + re-label) |

NCPR is the harder benchmark and the one we report externally; the
retrieval eval remains the fast inner-loop signal during development.

## 9. Versioning

- v1 = this document. Frozen.
- Any change to match types, ordering, threshold, normalization rules,
  embedding model, or de-duplication logic requires:
  1. new ADR in `references/methodology/adr/`,
  2. version bump to `ncpr_v2` with its own spec file,
  3. re-run of the full benchmark on v2; v1 numbers remain on record.

Cosmetic edits (typos, clarifications that do not change behavior) are
allowed in place with a changelog note at the bottom of this file.

## 10. Changelog

- 2026-05-17 — v1 frozen (W22-T4).
