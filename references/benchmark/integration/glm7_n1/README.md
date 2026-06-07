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
| **Deterministic** (`definition_variable_guard`) | **FAIL** (binds) | concern 2/6 · **column 5/5** | **Measured + reproducible.** Flags DM + CKD definition leakage; catches all five definition columns (HbA1c, FBG, Insulin, BUN, Cr) after the disease-KB v1.2 synonym fix below (was 3/5 at v1.1). |
| **RAG** (`retrieve_for_failure`, BM25) | concern | self-consistency 5/6 · **independent precision 8/16** | Self-consistency (a concern retrieved for 5/6 themes) *masked* the precision: judged blind to rank, **only half the retrieved concerns are genuinely on-topic** (definition_leakage 1/4, cross_sectional 2/4, selection 2/4, eval 3/4). |
| **LLM** (frozen Claude reviewer) | not_publication_grade | self-attested 6/6 · **blind-adjudicated 6/6 ✓** | A 3-panelist blind matcher (never saw `addresses_gt`) re-derived the same mapping **3/3 unanimous on every concern** → the self-attestation **held** under independent scrutiny. Still non-reproducible. |

**Verdicts:**
- **`reproducible_verdict = min(deterministic=FAIL, rag=concern) = FAIL`** — from the two reproducible
  layers alone, the deterministic floor already binds the paper to FAIL.
- `frozen_augmented_verdict = FAIL` — folding in the frozen LLM does not change it.
- **Union of the reproducible layers alone = 5/6**; only **GT-4** (CHARLS re-fit) rests *solely* on the
  non-reproducible LLM layer.

## What this N=1 actually shows

- **The deterministic floor earns its place** — it FAILS the paper non-fabricably on the circular
  diabetes result (GT-1) and the kidney leakage (GT-6), and it does so reproducibly. Its limit is
  *breadth* (it cannot see design issues like cross-sectional-as-prediction); its earlier *synonym
  coverage* gap (the FBG/Cr miss) was a real defect this N=1 found and got fixed (see closed loop below).
- **The LLM adds real breadth** — it is the only layer reaching GT-4, and it caught a defect in
  *neither* the KB nor the gates: an "ElasticNet … superior" sentence inside the XGBoost methods
  (full text line 139) — a genuine copy-paste/reproducibility artifact, independently verified.
- **Overlap** — det ∩ rag ∩ llm = {GT-1, GT-6}; rag∩llm adds {GT-2, GT-3, GT-5}; llm-only = {GT-4}.

## Blind adjudication (turning the soft numbers honest)

The two non-deterministic layers' first-pass numbers were *self-graded*. A blind-to-labels
adjudication pass (`adjudication.frozen.json`) re-measured both independently:

- **LLM coverage — validated.** 3 panelists, blind to `addresses_gt`, each matched the 6 LLM messages
  to GTs; **3/3 unanimous on all six**, 6/6 agreement with the self-declared mapping. The LLM layer's
  claims hold up — the self-attested 6/6 was not inflation.
- **RAG precision — deflated and made honest.** Judging each retrieved concern's relevance blind to
  rank: **8/16 (50%)**. Per class: definition_leakage **1/4** (3 of 4 are *different* leakage
  mechanisms — NSAID-proxy, confounding, reverse-causation), cross_sectional 2/4, selection 2/4,
  eval 3/4. → a concrete BM25 gate-path precision finding the rosy "5/6" hid.
- **Caveat:** adjudicators are the *same model family* (no paid cross-model call). This catches
  self-attestation inflation and rank-driven self-consistency, **not** shared-model bias — true
  independence needs a different model. The adjudication is itself frozen / non-reproducible.

## Closed loop — the disease-KB gap this N=1 found, and fixed (RESOLVED)

At disease-KB **v1.1**, the deterministic layer missed **FBG** and **Cr** (column recall 3/5): the KB
listed `fpg`/`fasting_plasma_glucose` and `creatinine` but not the common abbreviations `fbg`/`cr`, so
the guard under-caught column-level leakage on any paper using them. **This N=1 surfaced that real
shipping-gate gap.** With user confirmation (CLAUDE.md S1 — `references/*.json` is not edited
unattended), disease-KB **v1.2** added `fbg` (→ `type_2_diabetes`) and `cr` (→ `chronic_kidney_disease`)
as synonyms — a pure abbreviation expansion, no new clinical claim. The guard now catches all five
definition columns (**recall 5/5**). `test_kb_synonym_gap_closed` is the regression. This is the
benchmark doing exactly what it exists to do: find a concrete defect the shipping product had, and
close it.

## Honest limitations (what this N=1 does NOT show)

This record was revised after an adversarial review flagged first-pass over-claims. The corrected
position:

1. **The RAG "5/6" is self-consistency; the honest number is precision 8/16.** `ground_truth.json`'s
   `rag_concern_ids` were read off a retrieval run, so 5/6 only measures that *something* on-topic was
   retrieved per theme. The **blind relevance adjudication** (judging each retrieved candidate on-topic
   blind to rank) gives the real number: **8/16 = 50% precision** — half the retrieved KB concerns are
   the right broad category but a *different specific mechanism*. Use the precision, not the 5/6.
2. **The LLM "6/6" is self-attested but was independently validated.** The runner credits the LLM via
   the frozen file's own `addresses_gt`. A **3-panelist blind matcher** (never shown `addresses_gt`)
   independently re-derived the mapping **3/3 unanimous on all six** → the self-attestation held. Caveat:
   the adjudicators are the *same model family* (no paid cross-model call), so this catches
   label-copying / inflation, **not** shared-model bias. See `adjudication.frozen.json`.
3. **Only 2 of 3 layers are reproducible.** `final` and the 6/6 union depend on the frozen LLM file;
   the runner re-verifies only the deterministic + RAG layers (hence the separate
   `reproducible_verdict` and `union_reproducible_layers_only = 5/6`).
4. **Asymmetry is a structural invariant here, not an empirical result.** `final = min(...)` can never
   raise a verdict by construction, and in this case every layer lands at ≤ concern with `rag_verdict`
   fixed — so nothing was in a position to test it. It is reported as a design property.
5. **N=1.** The runner is data-driven from `ground_truth.json` (failure classes, deterministic targets,
   definition columns) so a second case is a new folder, **but** the failure classes are still authored
   per paper rather than derived from a live gate run. Blind adjudication (control C3) is now done for
   this case; what remains for the general harness (plan P1/P2): auto-deriving failure classes from a
   live gate run, **cross-model** adjudication (not same-family), and scaling to N>1.

## Files

| File | Role |
|---|---|
| `inputs/paper.json` | Frozen, faithfully-extracted GLM7 declarations + `fulltext_sha256`. |
| `inputs/phenotype_spec.json` | Deterministic-check spec; `defining_variables` copied verbatim from the disease-KB (v1.1). |
| `inputs/features.csv` | The 49 declared predictors + GLM7 as a header-only feature manifest. |
| `ground_truth.json` | **Isolated** answer key (C5): 6 concerns → rule, severity, quote, expected layer(s); plus data fields driving the runner. |
| `llm_review.frozen.json` | Frozen LLM layer (Claude Code agent, not a paid call; non-reproducible). |
| `adjudication.frozen.json` | Frozen blind-to-labels adjudication: 3-panelist LLM→GT match (no `addresses_gt`) + per-class RAG relevance (blind to rank). Non-reproducible. |
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
- **Honesty** — the earlier column misses (FBG, Cr; now fixed in KB v1.2), the off-prediction RAG hit (GT-6), and the self-consistency /
  self-attested metric caveats are recorded, not hidden.
