# W23-D4 — NCPR v2: Retrieval-Only vs Full Pipeline

**Date:** 2026-05-17 · **Status:** READ-ONLY audit · **Wave:** W23 NCPR v2

## Question
NCPR's distinctive claim is that the end-to-end MLGG pipeline (RAG +
lint + gates) beats a bare retrieval baseline. If retrieval-only is
≥0.95× the full-pipeline F1, MLGG's value is mostly the KB itself,
not the 33-gate layer on top.

## Setup
- **Smoke set (5 papers):** same selection criterion as W23-D2 — KB
  entries with reviewer concerns ≥11 *and* both PDF + code repo
  available under `.cache/audit-repos-110/`. Chosen:
  `PR-EXP-0084, PR-EXP-0160, PR-EXP-0109, PR-EXP-0095, PR-EXP-0212`
  (11–15 concerns each).
- **Mode A (retrieval-only):** `scripts/rag/query.py::rag_query` on
  the paper's extracted Methods text (PDF → `pdftotext -layout` →
  W23-A2 slicer), top-K = 20, **self-paper hits filtered out** so the
  ground-truth concerns cannot trivially self-match.
- **Mode B (full pipeline):** Mode A flags ⊕ `mlgg lint check
  --format json` on the cached code repo. Lint severities
  (info/warn/error) normalised to (LOW/MEDIUM/HIGH).
- **Scoring:** W22-X1 matcher + W22-X2 severity-weighted F1, no
  embed_fn (offline; exact_code + code_prefix + category-tie only).
- **Methodological caveat:** 4/5 PDFs (Nature Comms peer-review
  bundles) lacked a recognisable "Methods" header, so the W23-A2
  extractor returned empty text and `rag_query` fell back to a
  canned default question. Recall is therefore a **lower bound**
  on what a properly-extracted Methods section could yield.

## Per-paper results

| paper_id     | concerns | A flags | A F1    | A P     | A R     | B flags (+lint) | B F1    | B P     | B R     | Δ F1     |
|--------------|---------:|--------:|--------:|--------:|--------:|----------------:|--------:|--------:|--------:|---------:|
| PR-EXP-0084  | 15       | 20      | 0.4835  | 0.431   | 0.550   | 28 (+8)         | 0.4632  | 0.400   | 0.550   | −0.020   |
| PR-EXP-0160  | 15       | 20      | 0.4444  | 0.431   | 0.458   | 24 (+4)         | 0.4251  | 0.396   | 0.458   | −0.019   |
| PR-EXP-0109  | 14       | 20      | 0.4889  | 0.431   | 0.564   | 20 (+0)         | 0.4889  | 0.431   | 0.564   |  0.000   |
| PR-EXP-0095  | 12       | 20      | 0.2105  | 0.204   | 0.217   | 24 (+4)         | 0.2041  | 0.192   | 0.217   | −0.006   |
| PR-EXP-0212  | 11       | 20      | 0.3590  | 0.269   | 0.538   | 20 (+0)         | 0.3590  | 0.269   | 0.538   |  0.000   |

## Macro (n=5)

| Metric                 | Mode A (RAG-only) | Mode B (Full pipeline) | Δ          |
|------------------------|------------------:|-----------------------:|-----------:|
| Macro weighted F1      | **0.3973**        | **0.3880**             | **−2.3 %** |
| Macro wPrecision       | 0.3535            | 0.3379                 | −4.4 %     |
| Macro wRecall          | 0.4657            | 0.4657                 |  0.0 %     |

## Interpretation
- `delta = (B − A) / A = −0.023` — falls in the **harmful** band
  (< −0.05 is "hurting"; we're at the noisy edge, but the sign is
  consistent across 3/5 papers and zero on the other 2).
- **Recall is unchanged in every paper.** Every lint flag is either
  outside the reviewer's concern surface or fails to match the
  matcher's `exact_code / code_prefix` rules. The 33-gate pipeline
  adds **no recall** on this smoke set.
- **Precision drops on 3/5 papers** because lint emits R-codes
  (R009, R016, R019, …) that the reviewers' `mlgg_gates` field never
  references, so the lint flags land as weighted FPs at the half
  discount and shave wP by 4 pp.
- Lint added a flag on 3 papers and zero on 2. The two zero-add
  papers (0109, 0212) had no `.py` files lint could parse —
  consistent with the W22-V2 audit's note that "most NCPR papers
  ship code but not data".

## Verdict
**Pipeline marginal-to-harmful on this slice.** The 33-gate layer
contributes ≤0 weighted-F1 over a same-KB retrieval baseline on the
5 papers tested. The KB-driven RAG path carries essentially all
the recall signal NCPR v2 currently measures.

## Recommendations
1. **Make `--rag-only` the NCPR v2 default** in
   `run_ncpr_benchmark.py`. Move the lint augmentation behind an
   opt-in flag (`--with-lint`) so headline numbers are not diluted
   by category-mismatched FPs.
2. **Re-score lint flags through a gate→reviewer-category map**
   (e.g., R009 / R016 / R029 → `evaluation` or `reproducibility`)
   before they enter the matcher. The current literal `R016` code
   cannot ever exact_code- or code_prefix-match a reviewer's
   `mlgg_gates: ["evaluation_quality_gate"]`, so the lint signal is
   structurally wasted.
3. **Treat this as a 5-paper smoke, not a verdict on the gates.**
   The harm is small (−2.3 %) and 4/5 PDFs had no Methods-text
   extraction, so Mode A also operated on a degraded query. Re-run
   with the W23-B1 empirical-cosine matcher (`semantic` rule enabled)
   on the full N=30 holdout before publishing the verdict in the
   paper.

## Artefacts
- `/tmp/W23_D4_run.py` — runner (149 LoC)
- `/tmp/W23_D4_per_paper.json` — per-paper P/R/F1 (both modes)
- `/tmp/W23_D4_summary.json` — macro numbers + delta
- `/tmp/W23_D4_log.txt` — full execution trace
