# NCPR v1 — Severity Weighting and Scoring Rationale

Status: draft for W22-T5 (NCPR Benchmark v1 wave)
Scope: defines how per-concern severity feeds the headline NCPR v1 score.

## 1. Why weight severities at all

In publication-grade peer review, the cost of a missed concern is not uniform.
Failing to catch a CRITICAL concern (e.g., undetected target leakage that would
force a post-publication correction or retraction) carries a qualitatively
different cost from missing a LOW concern (a typo, an unhelpful figure caption,
a stylistic phrasing nit). An unweighted F1 over reviewer concerns treats every
miss as identical, which systematically understates the operating cost of
CRITICAL misses and rewards systems that hit easy LOW items while leaving
hard CRITICAL items uncovered.

NCPR v1 therefore reports a severity-weighted F1 as the headline metric, with
unweighted F1 retained as a secondary diagnostic.

## 2. Weighting scheme

| Severity  | Weight | Anchor                                                     |
|-----------|--------|------------------------------------------------------------|
| CRITICAL  | 4.0    | Pre-publication retractable error if missed                |
| HIGH      | 2.0    | Requires major revision; reviewer would block acceptance   |
| MEDIUM    | 1.0    | Minor revision; reviewer would request a fix               |
| LOW       | 0.5    | Stylistic / nice-to-have; reviewer would mention in passing |

The ratios form a geometric progression (4 / 2 / 1 / 0.5, common ratio 2),
matching the working assumption that "one CRITICAL miss is roughly equivalent
in cost to two HIGH misses, four MEDIUM misses, or eight LOW misses." This
keeps the scheme easy to defend and avoids the arbitrariness of a per-tier
hand-tuned constant.

## 3. Severity source

The severity used for weighting is the reviewer's labeled `severity` field in
the held-out KB, never MLGG's own severity output for that concern. Using
MLGG's severity to weight MLGG's own evaluation would create a system-bias
loop: a system that systematically inflates severity would also inflate its
own score. The reviewer label is treated as the ground-truth cost signal.

## 4. Formula

For each held-out paper `p` with reviewer concern set `R_p` and MLGG flag set
`M_p`, and an alignment `match(r, m)` that pairs each reviewer concern with at
most one MLGG flag (and vice versa):

- weighted TP: `wTP_p = sum over matched r of weight(severity_reviewer(r))`
- weighted FN: `wFN_p = sum over unmatched r in R_p of weight(severity_reviewer(r))`
- weighted FP: `wFP_p = sum over unmatched m in M_p of weight(severity_mlgg(m)) / 2`

The FP discount of 0.5 reflects that over-flagging is less costly than
under-flagging at publication-grade review: an extra flag costs reviewer
attention but is recoverable, whereas a missed CRITICAL is not.

Per-paper precision, recall, and F1:

```
wP_p = wTP_p / (wTP_p + wFP_p)
wR_p = wTP_p / (wTP_p + wFN_p)
wF1_p = 2 * wP_p * wR_p / (wP_p + wR_p)
```

If `wTP_p + wFP_p == 0` then `wP_p := 1.0` by convention (no flags, no false
positives). If `wTP_p + wFN_p == 0` then the paper has no reviewer concerns
and is excluded from aggregation.

## 5. Aggregation

NCPR v1 macro-averages `wF1_p` over the 30 held-out papers. Each paper is
weighted equally regardless of how many concerns it carries. This prevents a
small number of concern-dense papers from dominating the headline number and
matches the spirit of "how does MLGG do on a typical paper."

## 6. Tiebreakers on severity mismatch

The `match` function pairs concerns on content (category + locus), not on
severity. Severity mismatch between MLGG and the reviewer is handled as:

- MLGG severity > reviewer severity: match still counts toward wTP, but no
  extra credit is awarded. The weight used is the reviewer's, as in section 4.
- MLGG severity < reviewer severity: match still counts toward wTP at the
  reviewer's weight, and the pair is flagged as "under-rated" in the failure
  mode analysis. Under-rating a CRITICAL down to LOW is a known operating risk
  even when the concern is technically detected.

## 7. Failure thresholds

- Per-paper: `wF1_p < 0.30` flags the paper as a problem case for qualitative
  review.
- Aggregate: macro-averaged sev-weighted F1 < 0.50 puts the benchmark in the
  RED state and blocks any "publication-grade" claim in release notes.

These thresholds are provisional and expected to be re-anchored after the
first full run on the 30-paper held-out set.

## 8. Relationship to retrieval P@5

The retrieval evaluation reports P@5: of the top-5 retrieved KB entries for a
given concern, how many are relevant. P@5 is binary per slot and ignores both
graded ground truth (a LOW concern counts the same as a CRITICAL one) and
over-flagging cost. The sev-weighted F1 in this document is the
end-to-end-review counterpart: it captures graded cost and penalizes
over-flagging, at the price of being harder to compute (requires alignment)
and harder to compare across benchmark versions if the weighting scheme
shifts. Both metrics are reported; P@5 is the upstream-retrieval health check,
sev-weighted F1 is the headline.

## 9. Deferred open question

Should the aggregate correct for category imbalance? Some concern categories
(e.g., reporting-standards items such as missing CONSORT fields) have much
higher base rates than others (e.g., subtle target leakage). A category-naive
macro-average over papers may still let high-base-rate categories dominate
within each paper. A per-category macro-then-average scheme would correct for
this but introduces its own bias when a paper has zero concerns in a category.
This is left open for NCPR v2 and is explicitly out of scope for v1.

## 10. Top assumption that may be wrong

The geometric 4 / 2 / 1 / 0.5 ratio is anchored on intuition, not on measured
reviewer cost. It is plausible that real reviewer cost is steeper at the top
(CRITICAL is more like 8x LOW than 8x LOW) or flatter at the bottom (LOW is
more like 0.1x than 0.5x). Sensitivity analysis over alternate weight vectors
should be reported alongside the headline number in the v1 results doc.
