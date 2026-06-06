# Integration Benchmark — N=1 record: GLM7

> The **first cross-layer** record for NCPR-Bench v2 (see `docs/integration-benchmark-PLAN.md`).
> Every prior benchmark exercises **one** layer in isolation; this one runs the deterministic
> floor + RAG + LLM advisory on **one real paper** and reports all three against an isolated
> ground truth. It was hardened by an independent 4-lens adversarial review (see
> "Honest limitations" — several first-pass over-claims were caught and corrected before commit).

**Paper:** GLM7 composite index, *Advanced Science* 2025, DOI `10.1002/advs.202510552` (PMC12622479).
**Tier:** **B+** — real paper, methods-text + declared-feature coverage. NOT full 33-gate execution
(the gates consume `evidence/*.json` from an instrumented training run, which a published paper does
not emit — see PLAN §5). The deterministic layer here is the **disease-KB definition check on the
declared feature manifest**, which *is* runnable on a paper.

## Result (regenerate with `python3 scripts/rag/evals/run_glm7_n1.py`)

| Layer | Verdict | Number | What the number means |
|---|---|---|---|
| **Deterministic** (`definition_variable_guard`) | **FAIL** (binds) | concern 2/6 · **column 3/5** | **Measured + reproducible.** Flags DM + CKD definition leakage; caught HbA1c, Insulin, BUN; **missed FBG, Cr** (disease-KB abbreviation gap). |
| **RAG** (`retrieve_for_failure`, BM25) | concern | self-consistency 5/6 | **Retrieval self-consistency, NOT blind recall** — the GT's `rag_concern_ids` were observed from retrieval (see caveat below). 8 distinct KB concerns credited. |
| **LLM** (frozen Claude reviewer) | not_publication_grade | **self-attested** 6/6 | Scored from the frozen file's own `addresses_gt`; **not independently adjudicated; non-reproducible.** |

**Verdicts:**
- **`reproducible_verdict = min(deterministic=FAIL, rag=concern) = FAIL`** — from the two reproducible
  layers alone, the deterministic floor already binds the paper to FAIL.
- `frozen_augmented_verdict = FAIL` — folding in the frozen LLM does not change it.
- **Union of the reproducible layers alone = 5/6**; only **GT-4** (CHARLS re-fit) rests *solely* on the
  non-reproducible LLM layer.

## What this N=1 actually shows

- **The deterministic floor earns its place** — it FAILS the paper non-fabricably on the circular
  diabetes result (GT-1) and the kidney leakage (GT-6), and it does so reproducibly. Its limit is
  *breadth* (it cannot see design issues like cross-sectional-as-prediction) and *synonym coverage*
  (the FBG/Cr miss).
- **The LLM adds real breadth** — it is the only layer reaching GT-4, and it caught a defect in
  *neither* the KB nor the gates: an "ElasticNet … superior" sentence inside the XGBoost methods
  (full text line 139) — a genuine copy-paste/reproducibility artifact, independently verified.
- **Overlap** — det ∩ rag ∩ llm = {GT-1, GT-6}; rag∩llm adds {GT-2, GT-3, GT-5}; llm-only = {GT-4}.

## Actionable follow-up (NOT auto-applied)

`record.json → followups`: the deterministic layer missed **FBG** and **Cr** because the disease-KB
lists `fpg`/`fasting_plasma_glucose` and `creatinine` but not the abbreviations `fbg`/`cr`. Adding
those synonyms would raise column recall to 5/5. **Per CLAUDE.md S1, `references/*.json` is never
edited unattended — this is a proposal for human confirmation.**

## Honest limitations (what this N=1 does NOT show)

This record was revised after an adversarial review flagged first-pass over-claims. The corrected
position:

1. **The RAG number is self-consistency, not recall.** `ground_truth.json`'s `rag_concern_ids` were
   read off a retrieval run, so "5/6" measures whether the shipping path surfaces an on-topic KB
   concern per failure class — it does **not** measure recall against a blind, pre-registered key. A
   true precision/recall needs a key authored from concern *text* before any retrieval (plan P2).
2. **The LLM number is self-attested.** The runner credits the LLM via the frozen file's own
   `addresses_gt` tags; the same author wrote both files, so 6/6 is coverage-by-construction, not an
   independent match. A blind LLM→GT adjudicator is future work (plan P2 / control C3).
3. **Only 2 of 3 layers are reproducible.** `final` and the 6/6 union depend on the frozen LLM file;
   the runner re-verifies only the deterministic + RAG layers (hence the separate
   `reproducible_verdict` and `union_reproducible_layers_only = 5/6`).
4. **Asymmetry is a structural invariant here, not an empirical result.** `final = min(...)` can never
   raise a verdict by construction, and in this case every layer lands at ≤ concern with `rag_verdict`
   fixed — so nothing was in a position to test it. It is reported as a design property.
5. **N=1.** The runner is data-driven from `ground_truth.json` (failure classes, deterministic targets,
   definition columns) so a second case is a new folder, **but** the failure classes are still authored
   per paper rather than derived from a live gate run. The general multi-paper harness (auto-deriving
   failure classes; blind adjudication) is plan P1/P2, not this record.

## Files

| File | Role |
|---|---|
| `inputs/paper.json` | Frozen, faithfully-extracted GLM7 declarations + `fulltext_sha256`. |
| `inputs/phenotype_spec.json` | Deterministic-check spec; `defining_variables` copied verbatim from the disease-KB (v1.1). |
| `inputs/features.csv` | The 49 declared predictors + GLM7 as a header-only feature manifest. |
| `ground_truth.json` | **Isolated** answer key (C5): 6 concerns → rule, severity, quote, expected layer(s); plus data fields driving the runner. |
| `llm_review.frozen.json` | Frozen LLM layer (Claude Code agent, not a paid call; non-reproducible). |
| `record.json` | Generated result: per-layer flags, attribution, metrics, verdicts, follow-ups. |

## Reproduce

```bash
python3 scripts/rag/evals/run_glm7_n1.py          # check vs frozen record.json (exit 2 on drift)
python3 scripts/rag/evals/run_glm7_n1.py --write   # regenerate after an intentional input/KB change
```

The **deterministic** and **RAG** layers reproduce from the frozen inputs + the live disease-KB /
peer-review-KB. The **LLM** layer is frozen; its method is recorded in `llm_review.frozen.json`.

## Validity controls in force

- **C1 LOPO** — `excluded_paper_ids` threaded through retrieval; a declared **no-op** here because
  GLM7 is **not** in the peer-review KB (confirmed) → no self-leakage.
- **C5 GT isolation** — `ground_truth.json` is loaded but consumed only *after* each layer emits flags.
- **Honesty** — column misses (FBG, Cr), the off-prediction RAG hit (GT-6), and the self-consistency /
  self-attested metric caveats are recorded, not hidden.
