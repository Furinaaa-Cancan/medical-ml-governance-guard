# G8: BM25 "high-IDF terms don't fire" diagnostic

**Investigated:** 2026-05-17
**Scope:** Why does BM25 return `_bm25_score=0.0` on E1 Q4
("AUROC reported without confidence interval"), gate-anchored to
`evaluation_quality_gate` with codes `["MLGG-E01","MLGG-E02"]`?

---

## Symptom (E1 Q4 recap)

Free-text query "AUROC reported without confidence interval" with
gate=evaluation_quality_gate, codes=`["MLGG-E01","MLGG-E02"]`,
top_k=10 returned a fully-formed result list (10 hits) but every
`_bm25_score == 0.000`, even on `PR-EXP-0159-C06` whose `concern_text`
literally begins "The authors used AUC to evaluate the performance of
the classification model. The 95% confidence interval should be
reported…" and whose tags are
`['missing_confidence_intervals','ci_reporting']`. A high-IDF phrase
that distinctive should pin BM25 hard. It does not.

---

## Path analysis

| Path | BM25 invoked? | Observed |
|---|---|---|
| Free-text (no gate / no codes) | No (per E2; `hybrid_rank` guards on `if gate and failure_codes`) | bm25 trivially 0; expected |
| Gate-anchored (gate + codes given) | Yes | `_match_reasons` contains `"BM25 match (BM25 match) score=0.00"` — meaning the path executed but contributed 0 |

So **BM25 IS reached in the gate-anchored path**, runs
`retrieve_for_failure("evaluation_quality_gate", ["MLGG-E01","MLGG-E02"])`,
returns 10 concerns — but every one is tagged
`_retrieval_mode == "severity_fallback"` with `_score == 0`. The min-max
normalizer in `hybrid._normalize_bm25` sees an all-zero vector and
returns all 0s (per its `if hi <= 0: return [0.0…]` branch). Result:
BM25 contribution is dead weight on this query.

Live trace (top three of the actual gate-anchored rag_query):

```
PR-EXP-0159-C06 bm25=0.000 dense=0.766
   text: The authors used AUC to evaluate the performance of the classification model.
         The 95% confidence interval should be repo...
   tags: ['missing_confidence_intervals', 'ci_reporting']
   reasons: ['dense top-1 score=0.77', 'gate match: evaluation_quality_gate', …]
PR-011-C01 bm25=0.000 dense=0.763  tags: ['modest_performance', …]
PR-004-C01 bm25=0.000 dense=0.756  tags: ['inappropriate_metric', …]
```

The dense retriever IS pulling the right concern into rank 1
(`PR-EXP-0159-C06`, dense 0.766). BM25 just adds nothing.

---

## BM25 internals (from `scripts/rag/retrieval/bm25.py`)

| Aspect | Behavior |
|---|---|
| Tokenizer (`_TOKEN_SPLIT`) | `re.compile(r"[^a-z0-9]+")` over a lowercased string — whitespace, hyphens, underscores all split. No stemming. No phrase index. |
| Indexed fields (per `_score` in `retrieve_for_failure`, lines 473–480) | `concern.tags` (3× weight, tokenized) and first 600 chars of `concern.concern_text` (1× weight, tokenized). Notable omissions: `reviewer_quote`, `category`, `canonical_pattern_id`, `author_response` are NOT searched. |
| Multi-word phrase handling | None — "confidence interval" → `{confidence, interval}`, scored as two independent unigrams against the per-concern token set. No bigram/phrase index. |
| `failure_codes` treatment | Tokenized via `_issue_code_keywords` (lines 354–408): lowercased, hyphens→`_`, split on `_`. **Tokens < 3 chars are dropped** (line 393), as are 20 boilerplate stopwords (`not`, `met`, `required`, `missing`, `insufficient`, …). Whole code is also probed against `TAG_SYNONYMS`; expansion to KB tags is added only when the bare code (or a stripped suffix variant) is a synonym map key. |

The 3-char floor is the heart of the bug for CI queries: tokens
`ci`, `e01`, `e02` are all 2 chars or filtered, so `MLGG-E01`,
`MLGG-E02`, `missing_ci`, `no_ci_reported`, `ci_reporting`, even
`ci_matrix_not_passed` collapse to keyword sets that contain zero
ci-distinctive tokens.

---

## Test matrix (gate = `evaluation_quality_gate`)

| Input codes | Tokenized keywords | Mode | Top _score | Top-1 concern |
|---|---|---|---|---|
| `["MLGG-E01","MLGG-E02"]` (E1 Q4) | `{e01, e02, mlgg}` — none informative | severity_fallback | 0 | PR-006-C01 (severity sort) |
| `["confidence_interval"]` | `{confidence, interval}` | keyword_match | 5 | PR-EXP-0159-C06 ✓ |
| `["missing_confidence_intervals"]` (actual KB tag) | `{confidence, intervals}` | keyword_match | 8 | PR-EXP-0198-C04 ✓ |
| `["no_ci"]` (synonym key) | `{bootstrap, narrow, suspiciously}` (via TAG_SYNONYMS) | keyword_match | 7 | PR-035-C05 ✓ |
| `["no_ci_reported"]` | `{}` — `ci` < 3 chars; `reported` is in `_CODE_TOKEN_STOPWORDS`; no synonym key | severity_fallback | 0 | PR-006-C01 |
| `["missing_ci"]` | `{}` — `ci` filtered; `missing` is in `_CODE_TOKEN_STOPWORDS` | severity_fallback | 0 | PR-006-C01 |
| `["ci_reporting"]` | `{reporting}` (single mid-IDF token) | keyword_match | 1 | PR-EXP-0112-C04 |
| `["confidence interval"]` (the literal phrase) | `{confidence, interval}` if split — but BM25 receives it as the whole-code string and tokenizes correctly | severity_fallback | 0 | PR-006-C01 (NOTE: this fell through — `confidence interval` does not equal a synonym key, and there is no probe matching the full lowercased string; the per-token loop still yields `{confidence, interval}`, but mode was still severity_fallback because gate filter and word-set semantics interact — verified empirically) |
| `[]` (no codes) | `{}` | severity_fallback | 0 | PR-006-C01 |
| `["interval"]` | `{interval}` | keyword_match | 1 | PR-EXP-0112-C04 |
| Real gate codes from `evaluation_quality_gate.py`: | | | | |
| `["missing_ci_method"]` | `{method}` (lost `ci`) | keyword_match | 3 | PR-RO-07-C05 (off-target) |
| `["ci_width_exceeds_threshold"]` | `{exceeds, threshold, width}` (lost `ci`) | keyword_match | 4 | PR-011-C01 (off-target) |
| `["insufficient_ci_resamples"]` | `{resamples}` (`insufficient`, `ci` filtered) | severity_fallback | 0 | PR-006-C01 |
| `["ci_matrix_not_passed"]` | `{matrix, passed}` (lost `ci`, `not`) | severity_fallback | 0 | PR-006-C01 |
| `["missing_ci_matrix_report"]` | `{matrix, report}` (lost `ci`, `missing`) | keyword_match | 1 | PR-EXP-0092-C03 (off-target) |

Key result: every real ci-related failure code emitted by
`evaluation_quality_gate.py` loses the discriminative `ci` token at
keyword construction. The CI concerns in the KB are reachable only via
the spelled-out tag `confidence_interval` / `confidence_intervals`,
which the gate never passes in.

---

## KB analysis

- Total CI-related concerns (text mentions "confidence interval" /
  "95% CI" / tags include `missing_ci`/`ci_reporting`/
  `missing_confidence_intervals`): **17**
- Tagged with `evaluation_quality_gate`: **17/17** — KB tagging is correct
- Also tagged with `ci_matrix_gate`: 16/17 — these concerns are well-tagged
- Surfaced by Step-1 gate-anchored query in the dense top-5:
  **1/17 (PR-EXP-0159-C06)** — the rest don't surface because dense
  embedding pulls AUROC-shaped concerns before CI-shaped ones; BM25
  could break the tie but doesn't.

So the KB has the content. The KB has the right tags. The retrieval
plumbing fails to convert `MLGG-E01`-style codes into the keywords
needed to find them.

---

## Diagnosis

**Primary cause: (c) failure_codes ↔ tag matching.** The
gate is reached, the BM25 ranker is reached, the KB has correctly
tagged CI concerns. The break is between gate-emitted codes and the
keyword extractor:

1. The `min-len-3` filter in `_issue_code_keywords` drops the only
   distinguishing token in every ci-prefixed failure code (`ci` is 2
   chars).
2. `TAG_SYNONYMS` covers `no_ci` but not `missing_ci`, `ci_reporting`,
   `missing_ci_method`, `ci_width_exceeds_threshold`,
   `insufficient_ci_resamples`, `ci_matrix_not_passed`,
   `missing_ci_matrix_report`, `no_ci_reported`, or the canonical
   `MLGG-E01` / `MLGG-E02` rule codes from CLAUDE.md.
3. Test inputs in E1 used the CLAUDE.md canonical codes `MLGG-E01` /
   `MLGG-E02`. Those don't appear in `TAG_SYNONYMS` either, so even
   the synonym escape hatch fails.

Secondary contributing factors:

- (b) is also true but tertiary: `_STOPWORDS` would knock out `the`,
  `was`, etc., but the BM25 path under test never hits the text-query
  branch — the failure path is code → keyword extraction, not text →
  word tokenization.
- (a) is NOT the cause: 17/17 CI concerns are tagged
  `evaluation_quality_gate`; KB curation is fine.

In short: BM25 IS fine at tokenizing the corpus. It is fine at
matching keywords to tokens. **It is starved of keywords because the
code→keyword extractor cannot turn `MLGG-E01` or `missing_ci_method`
into anything CI-shaped.**

---

## Recommended fix (scope estimate: 10–25 LOC, one file)

All edits in `scripts/rag/retrieval/bm25.py`:

1. **Lower the token-length floor for ci-style abbreviations.** Either:
   - Drop the `len(tok) >= 3` floor to `>= 2` (1 LOC); risks adding
     noise from `id`, `or`, etc. — manageable since
     `_CODE_TOKEN_STOPWORDS` can absorb them.
   - OR add a small `_PRESERVE_SHORT_TOKENS = frozenset({"ci","r2","ml","ai"})`
     exception above the length filter (3 LOC). Safer.

2. **Add MLGG canonical-rule synonyms to `TAG_SYNONYMS`** (10–15 LOC).
   The codes in CLAUDE.md (`MLGG-E01`, `MLGG-E02`, `MLGG-S01`,
   `MLGG-P01`, `MLGG-F01`, `MLGG-F02`, `MLGG-M01`) are the documented
   public interface for rule violations and should each expand to the
   KB tag family they describe. Concretely for E01/E02:

   ```python
   "mlgg_e01": ["missing_ci", "no_bootstrap_ci",
                "missing_confidence_intervals", "ci_reporting",
                "ci_needed", "suspiciously_narrow_ci"],
   "mlgg_e02": ["missing_calibration", "calibration_plot_missing",
                "missing_dca", "auprc_missing", "metrics_in_supplement_only"],
   ```

   Then `_issue_code_keywords` will pull `confidence`, `intervals`,
   `bootstrap`, `calibration`, etc. into the keyword set whenever a
   gate emits a CLAUDE.md canonical code. (Note: `_issue_code_keywords`
   already lowercases and replaces `-` with `_`, so `MLGG-E01` will
   normalize to `mlgg_e01` and hit the synonym key directly.)

3. **Add ci-specific failure-code synonyms** so the gate's own emitted
   codes work even without spelled-out canonical labels (5–10 LOC):

   ```python
   "missing_ci": ["missing_ci", "no_bootstrap_ci",
                  "missing_confidence_intervals", "ci_reporting",
                  "suspiciously_narrow_ci"],
   "missing_ci_method": ["missing_ci", "ci_reporting", "no_bootstrap_ci"],
   "ci_width_exceeds_threshold": ["suspiciously_narrow_ci",
                                  "missing_ci", "no_bootstrap_ci"],
   "insufficient_ci_resamples": ["no_bootstrap_ci", "missing_ci"],
   "ci_matrix_not_passed": ["missing_ci", "ci_reporting",
                            "missing_confidence_intervals"],
   "no_ci_reported": ["missing_ci", "no_bootstrap_ci",
                      "missing_confidence_intervals", "ci_reporting"],
   ```

No change required to `hybrid.py` or to the KB. Total change is
contained in the `TAG_SYNONYMS` dict + one tweak to the token filter.
Add 6–8 unit tests in `tests/test_bm25.py` (parametrized: each new
synonym key should yield keyword_match mode and top-1 score ≥ 3 for
its expected concern_id). Total churn ≈ 30–50 LOC including tests.

---

## Most surprising finding

The bug is in the *keyword extractor*, not the ranker. BM25's
`_score` formula and corpus indexing are correct, the KB is correctly
tagged, dense retrieval already pulls `PR-EXP-0159-C06` to rank 1, and
the gate passes the right codes — but the keyword extractor's 3-char
floor is the choke point. **Two characters of input (`ci`) erase the
entire CI-signal pathway through BM25.** The same flaw silently
affects every other 2-char clinical abbreviation a gate might emit
(`r2`, `ml`, `ai`, `df`, etc.), so this is not a one-off CI quirk.
A second-order surprise: even after the 3-char floor would be relaxed,
`MLGG-E01`/`MLGG-E02` still go nowhere because none of the canonical
CLAUDE.md rule codes are present in `TAG_SYNONYMS`, despite being the
documented public interface for MLGG.
