# W28-V1 — Johnson 2017 replay with W26-R1 + W27-R1 knobs

**Date**: 2026-05-18
**Wave**: W28-V1 — verifying the W26-R1 (`adaptive_top_k`) + W27-R1 (`dedup_by_code`) knobs actually reduce over-flag on the case study that motivated them (Johnson 2017, MLHC reproducibility paper — a methodology-demonstration "clean" target).

**Cross-refs**: original case in `docs/diagnostics/W25_hybrid_phase2_case4_johnson2017.md` (commit `91cba4c` aggregate); knob commits `8aa9320` (W26-R1) + `5c68530` (W27-R1).

---

## Headline

| Setting | Flags | Unique gate codes | GT-relevant gates caught (3 of 5 GT) | Notes |
|---|---:|---:|---|---|
| **Baseline** (W25 numbers) — `top_k=20, adaptive=False, dedup=False` | **20** | 8 | 3/3 | Reproduces W25 case4 §4 |
| W26-R1 only — `adaptive=True, dedup=False` | 22 | 9 | 3/3 | Adaptive bumped to 22 (query is 433 chars / 24 topic tokens, mid-band) |
| W27-R1 only — `top_k=20, dedup=True` | **8** | 8 | 3/3 | Dedup is the bulk of the win |
| **Combo (W26+W27)** — `adaptive=True, dedup=True` | **9** | 9 | 3/3 | The recommended Mode B/C default |

**Flag count: 20 → 9 (55 % reduction).**
**Noise per detectable-GT signal: 17/3 ≈ 5.67 → 6/3 = 2.0 (~2.8 × lower).**
**Recall on GT-relevant gates: 100 % preserved** (`evaluation_quality_gate`, `calibration_dca_gate`, `external_validation_gate`, `model_selection_audit_gate` all still present; combo adds `reporting_bias_gate` from the two extra adaptive picks).

## Why this is the right experiment

W26-R1 + W27-R1 are both **opt-in defaults-off** to preserve W25 benchmark reproducibility. That meant we had a code change with **no measured product effect** beyond unit tests. W28-V1 is the smallest experiment that closes that loop: run both knobs on the exact W25 query that produced the 20-flag baseline, count what changes.

Johnson 2017 is the right target because:
- W25 case4 explicitly diagnosed Johnson's 75 % over-flag rate as the worst across the 8-paper corpus.
- It's a **clean methodology paper** — RAG mis-fires not because the paper has many bugs but because its topical surface (MIMIC-III, reproducibility, K-fold, calibration) overlaps with many KB concerns.
- Dedup_by_code's whole thesis: when 7 cohort_definition concerns retrieve, they all collapse to one `cohort_definition_gate` flag.

## Decomposition: where do the 11 dropped flags come from?

Per the baseline gate distribution:

```
baseline_codes = {
    'cohort_definition_gate':    7,   # collapses to 1   → -6 flags
    'split_protocol_gate':       4,   # collapses to 1   → -3 flags
    'external_validation_gate':  3,   # collapses to 1   → -2 flags
    'evaluation_quality_gate':   1,
    'calibration_dca_gate':      1,
    'model_selection_audit_gate':1,
    'fairness_equity_gate':      1,
    'sample_size_gate':          1,
}
                                     # total: 20, post-dedup: 8
```

Three gates account for the entire 14-flag reduction (7→1 + 4→1 + 3→1 = 11 fewer). These are exactly the high-confidence "the KB has many neighbours of this concern" cases, where RAG was returning the same gate seven different ways. Post-W23 fix in `_concern_to_flag` made all seven collapse to `code="cohort_definition_gate"`, which then inflated the strict precision metric. W27-R1 closes that double-counting at the flag layer.

## Why W26-R1 alone barely helps on this query

`adaptive_top_k("the 433-char Johnson methods proxy")` returns 22 — slightly *above* the baseline's hard 20. The Johnson query length (433 chars) and topic-token count (24, vs the 35-token max-k ceiling) put it in the linear band, near the high end. The case study's original 75 % over-flag wasn't a query-length problem; it was a *KB-neighbourhood-density* problem. W27-R1 targets exactly that.

This is a useful diagnostic: it tells us **adaptive top_k earns its keep on very short queries** (Johnson-2017's 214-char even-shorter snippet hit min_k=5; this longer composite query doesn't). For paper-runner workloads where the methods text is hundreds of chars, the value comes from W27-R1 dedup.

## Recommended default for Mode B/C production callers

```python
flags = synthesize_flags_from_rag(
    methods_text,
    adaptive=True,        # cheap insurance for short queries
    dedup_by_code=True,   # main precision lever
)
```

This is the combo SKILL.md §Quick Dispatch already cites. W28-V1 confirms the citation is grounded in measurement, not just unit tests.

## What this does NOT validate

- **Other 7 papers in the W25 corpus**: untested here. Yan 2020 / Kaji 2019 / Purushotham 2018 may have different dedup wins; Phase 3 sweep should re-run all 8.
- **min_score (W27-R2)**: not exercised in this replay. The dedup wins were big enough that adding a score floor on top would be optimization, not validation.
- **Real precision on the paper's actual flaws**: the GT here is metadata-derived (circularity caveat from W25 case4 §0), so "precision" still means "matches the team-written GT," not "matches reality." The W27 N=1 plan (Quanjel critique, blocked on user) is the non-circular follow-up.

## Reproducer

```bash
cd /Volumes/Seagate/Skill/ml-leakage-guard
python3 -c "
import json, sys; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/other/johnson_2017_reproducibility_mimic/metadata.json'))
q = '. '.join([m['bibliographic']['title'],
  f'binary classification predicting {m[\"study_design\"][\"outcome\"]}',
  f'MIMIC-III ICU cohort, study period {m[\"study_design\"][\"study_period_start\"]}-{m[\"study_design\"][\"study_period_end\"]}',
  f'split strategy {m[\"dataset\"][\"split_strategy\"]}, scikit-learn ensemble with {m[\"model\"][\"n_candidate_models\"]} candidate models',
  'reproducibility evaluation across multiple model implementations, no calibration, no DCA, no bootstrap CI',
  'reproducibility methodology study, no external validation, single-center MIMIC-III'])
print('baseline:', len(synthesize_flags_from_rag(q, top_k=20)))
print('combo   :', len(synthesize_flags_from_rag(q, adaptive=True, dedup_by_code=True)))
"
# expected:
#   baseline: 20
#   combo   : 9
```

KB must be warmed (any prior `rag_query` call) or the embedding loader will print one-time progress noise around the numbers.
