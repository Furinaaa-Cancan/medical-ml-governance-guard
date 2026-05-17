# Audit Agent J — Current-State Snapshot of mlgg RAG/KB Audit Artifacts

**Date**: 2026-05-17
**Scope**: read-only inventory of eval / audit artifacts; structural prep for the final synthesis across parallel agents A–I.
**Repo**: `/Volumes/Seagate/Skill/ml-leakage-guard`

---

## A. Eval artifact inventory

### `references/retrieval_eval/`

| File | Type | Last touched (file mtime) | Internal timestamp | Headline metric | Known caveats |
|---|---|---|---|---|---|
| `baseline.json` | baseline (bm25_only) | 2026-05-17 01:57 | none in JSON | `mean_tag_precision=0.436`, `hit_at_k_rate=0.833`, `coverage=0.867`, N=30 | mode=`bm25_only`; **m3**: bm25 mean_tag_precision is the higher figure quoted in the audit prompt |
| `baseline_hybrid.json` | baseline (hybrid) | 2026-05-17 01:57 | none | `mean_tag_precision=0.338`, `hit_at_k_rate=0.867`, `coverage=0.867`, N=30 | mode=`hybrid`; **m3**: 0.338 < bm25's 0.436 despite higher hit-rate — known MMR-diversity-vs-tag-precision tradeoff, flagged in every W7P0 report as "diversity-aware caveat: MMR lowers this by design; prefer hit@K for headline" |
| `post_wave7_baseline_hybrid.json` | scenarios (post-Wave-7) | 2026-05-17 08:26 | n/a | `mean_hit_at_k=1.0`, `mean_tag_precision=0.538`, `mean_top1=0.649`, `n_zero_hits=4` | Same 30 scenarios; reflects post-W7P0 tag-overlap re-arch + W7 BM25 fixes |
| `post_wave7_baseline_hybrid.md` | scenarios report | 2026-05-17 08:26 | `2026-05-17T00:26:37Z` | per-scenario table | 4 zero-hit off-scope queries (woodworking/music/sailing/empty) are by-design |
| `labeled_precision_at_5.json` | labeled (ground-truth) | 2026-05-17 09:17 | `labeled_at: 2026-05-17` | mean P@5 = **0.639** over 36 labeled queries (L01–L36) | **M1**: `description` field says "Human-labeled ground-truth …" but `labeling_protocol.labeled_by` = `"W8-W2 + W9-A2 (Claude Opus 4.7, 1M context, MLGG agent)"`. The labels are LLM-self-rated, not human-rated. **M2**: dimension `preprocessing_split_leakage` mean P@5 = 0.20 (3 queries, includes L27 = 0.0 "standard scaler normalization fit on full dataset before split"); dimension `split_temporal_validation` mean P@5 = 0.20 (3 queries) |
| `scenarios.json` | scenarios config | 2026-05-17 01:17 | `version: 1.1`, curated 2026-04-23, augmented 2026-05-17 (H11) | 30 scenarios + 1 unmatched dimension (`h10_unmatched_dimensions[0] = Q11_reproducibility` → `publication_gate`) | `expected_relevant_tags` and `query_text` added in 2026-05-17 augmentation; original `expected_categories` / `expected_tags` are any-of, not all-of |
| `real_gate_codes_harvest.json` | config (gate-code probe set) | 2026-05-17 10:46 | n/a | 20 gates; each maps to its harvested failure code counts | Only 20 of 33 registry gates are present here — the others have zero peer-review codes harvested (matches E5 finding for `manifest_lock`, `request_contract_gate`, `security_audit_gate`, `self_critique_gate` being rag-empty by design) |

### `evidence/disease_kb_review/`

| File | Purpose | Current status |
|---|---|---|
| `INDEX.md` (2026-05-17, KB v1.1) | Index of 11 disease review sheets | all 11 entries `pending` |
| 11 `<disease>_review.md` files (each ~4 KB, 2026-05-17) | Per-disease clinician-review checklists matching `DISEASE_KB_REVIEW.md` | 11/11 status = `pending`; no `last_reviewed`, no `reviewer`, no `clinical_guideline_anchor` filled (per W8W10 audit) |

### `docs/diagnostics/` — RAG / KB / audit / peer-review related

| File | Theme | Last touched |
|---|---|---|
| `E1_retrieval_precision.md` | 12-query free-text P@5 audit; verdict CONDITIONAL | 2026-05-17 |
| `E2_hybrid_decomposition.md` | hybrid vs dense vs bm25 Spearman / Jaccard@5 | 2026-05-17 |
| `E3_edge_cases.md` | Defensive-path edge cases in `rag_query` | 2026-05-17 |
| `E4_cache_perf.md` | Embedding cache + retrieval perf | 2026-05-17 |
| `E5_gate_coverage.md` | 33-gate KB-coverage audit | 2026-05-17 |
| `F4_kb_curation_proposal.md` | KB curation roadmap | 2026-05-17 |
| `G2_gate_taxonomy_decision.md` | Gate taxonomy decision record | 2026-05-17 |
| `G8_bm25_diagnostic.md` | BM25 `_bm25_score=0.0` on CI queries (3-char floor, MLGG-Exx synonym gap) | 2026-05-17 |
| `H14_eval_delta.md` | Post-Wave-1 E1 re-run (free-text P@5 regressed 0.717 → 0.608; gate-anchored P@5 = 0.792) | 2026-05-17 |
| `H17_ci_drift_gate_proposal.md` | CI-side README drift gate (proposal-only) | 2026-05-17 |
| `H19_rag_llm_loop_eval.md` | RAG+LLM 5-scenario synthesis self-audit (RICH/WEAK/ZERO) | 2026-05-17 |
| `W2_q9_regression_diagnosis.md` | Q9 free-text regression (P@5 dropped 1.0 → 0.4; MMR over-penalising) | 2026-05-17 |
| `W6W1_off_scope_roi.md` / `W6W2_external_validation_kb_enrichment.md` | KB tag-enrichment proposals | 2026-05-17 |
| `W7P0_*` (baseline/baseline2/C1/C1_v2/C3/final/final2/tag_overlap_arch) | Wave-7 tag-overlap architecture experiments | 2026-05-17 |
| `W7P1_zero_hit_diagnosis.md` | 4 zero-hit scenarios diagnosed | 2026-05-17 |
| `W7P4_all_cp_fragmentation.md` / `W7P6_singleton_tags_audit.md` | Tag/canonical-pattern fragmentation (89.5% singletons; 64 prefix narrowings) | 2026-05-17 |
| `W7P7_e2_redo.md` | E2 hybrid decomposition redo post-Wave-7 fixes | 2026-05-17 |
| `W7P8_rag_coverage_audit.md` | scripts/rag test coverage (65% lines, harness/run_eval/query/bm25 below 70%) | 2026-05-17 |
| `W7P9_mlgg_stream_audit.md` | mlgg.py stdout/stderr stream-routing | 2026-05-17 |
| `W8W10_disease_kb_provenance_audit.md` | Disease KB provenance: 11/11 LLM-compiled, 0 clinician-reviewed | 2026-05-17 |
| `h2_proposed_remediation.md` | Tag-system remediation proposal | 2026-05-17 |

---

## B. Prior audit findings (status against today)

| Source doc | Finding | Status |
|---|---|---|
| `peer-review-kb-audit-2026-04.md` Finding (A) | Category field is acceptable (0/30 clear miscategorisations) | resolved (no action needed) |
| `peer-review-kb-audit-2026-04.md` Finding (B) | 13/16 leakage-tagged concerns NOT mapped to `leakage_gate` | **resolved** — CHANGELOG: "Leakage coverage on existing KB … `--gate leakage_gate` went from 3 → 13 concerns" |
| `peer-review-kb-audit-2026-04.md` Finding (C) | 73.6% (276/375) of concerns have empty `mlgg_gates` | **resolved** — CHANGELOG: "added `scripts/review/backfill_peer_review_gates.py` … brought empty count to 0/375" |
| `peer-review-kb-audit-2026-04.md` rec P0-3c | SKILL.md to disclose actual KB coverage | **resolved** — CHANGELOG: "Peer-review KB section rewritten to disclose actual coverage" |
| E1 Defect 1 — canonical-pattern boost over-weights | Topical drift on Q5, Q8 | partially resolved — W7P7 verifies CP gating now active with `CP_TAG_BOOST_DENSE_FLOOR=0.70`; H14 Q5 P@5 still soft; Q8 improved |
| E1 Defect 2 — severity-boost on thin topics (Q7) | Off-topic CRITICALs displace HIGH | open / partial — no W-wave doc shows the severity-bonus cap was added |
| E1 Defect 3 — BM25 dead on negation queries | Q4 (`AUROC … without CI`) returns bm25=0 | **diagnosed not fixed** — G8 identifies cause (3-char floor + missing MLGG-Exx synonyms); fix is a 30–50 LOC patch in `bm25.py` but no CHANGELOG entry yet |
| E5 systemic issue 1 — `hybrid_rank` rejects empty query | gate-filter-only retrieval broken | open (no follow-up entry seen) |
| E5 systemic issue 2 — circular import `scripts.rag.__init__` ↔ `gate_rag_bridge` | external import path crashes | open (W7P8 coverage audit still shows bridge functioning but via direct imports) |
| E5 issue 3 — `prediction_replay_gate` KB=1, score 0.033 | curation gap | open / curation-pending |
| E5 issue 4 — `robustness_gate` KB=7, top-1=0.368 | borderline curation gap | open / curation-pending |
| E5 issue 6 — 4 infra gates lack `rag_optional=True` | governance-honesty | **partially resolved** — H19 confirms `self_critique_gate` now uses `rag_optional=True` |
| W2 / Q9 regression — MMR over-penalising siblings (cos 0.81) | external-validation P@5 1.0 → 0.4 | open — explanation diagnosed; `MMR_COSINE_FLOOR=0.88` now live (W7P7) but Q9 still under-performing per H14 |
| W7P6 — 89.5% singleton tags / 64 prefix-narrowings | tag fragmentation kills `tag_overlap` | open (curation proposal, no KB writes yet) |
| W8W10 — F-01..F-07 disease KB provenance | F-01 zero clinician sign-off; F-02 no per-disease guideline anchor; F-03 lab thresholds un-versioned; F-04 no content change_log; F-05 ukb_validation only on T2D; F-06 review log empty; F-07 no kb_governance block | **all open** (audit explicitly read-only; user must approve v1.2 migration) |
| `peer-review-kb-audit-2026-04.md` recommendation NOT to recategorise `category` field | Avoid subjective recategorisation | superseded by m1/m2 — recategorisation is no longer the debate; ground-truth labelling protocol is |

---

## C. Recent change history (RAG / KB / eval)

From `CHANGELOG.md [Unreleased]` 2026-04-19 session + 2026-04 earlier session, and from `references/methodology/literature-knowledge-base.json change_log` (only 1 entry total). Bullets in reverse-chronological emphasis:

- **2026-04-22** — lit-KB `change_log` entry: added LIT-059..LIT-066 (deployment_monitoring); surfaces two **un-implemented** future gates `silent_trial_gate`, `postmarket_surveillance_gate`. (Only entry in lit-KB change_log; m4/m5 baselines were measured against this state.)
- **scopes / safety** — R028 omics-feature-prefix lint rule (Scanpy / TCGAbiolinks / PLINK redirect); `cohort_definition_gate` cascade structural checks (`COHORT_CASCADE_*` codes + Table 1 generator).
- **`leakage_gate`** — added `IMMORTAL_TIME_RE` (received_/prescribed_/treated_with_/…); fail-closed; Suissa 2008 / Hernán 2016 citations. Closes red-team r4 fixture.
- **`leakage_gate`** — five new post-index regex groups (LOS, num_procedures, discharge_*, ventilation_*, vasopressor_*); validated on diabetes_130 (5/6 caught).
- **`cohort_definition_gate`** — split `_GENERIC_PATTERNS` vs `_DISEASE_SPECIFIC_PATTERNS` (fixes SUPPORT2 glucose false positive); adds `inferred_target_disease`, `pattern_scope`.
- **Peer-review KB retrieval** — `retrieve_for_failure(gate_name, issue_codes)` replaces severity-only sort; re-rank `3 × tag_overlap + text_overlap`; severity-fallback retained. This is the path G8 still finds keyword-starved for CI queries.
- **Peer-review KB retrieval** — bridge now retrieves for `failures or warnings` (warning-only gates were previously empty).
- **Peer-review KB index** — `scripts/review/backfill_peer_review_gates.py` brought empty `mlgg_gates` arrays from 276/375 to 0/375; `--gate leakage_gate` went 3 → 13 concerns. **Closes peer-review-kb-audit-2026-04 Findings B+C.**
- **Disease KB provenance** — 11/11 entries got a `provenance` block with `clinician_review_status=pending`; `scripts/codebooks/_kb_provenance.extract_kb_provenance()` shared helper; downstream gate messages append `[KB entry is LLM-compiled and not yet clinician-reviewed]`.
- **Reviewer agent** — `score_paper_metadata.py` audits positive leakage claims against paired `_evidence` quotes; missing quotes emit `unsubstantiated_claims`; contract bumped to `paper_score.v1.1`.
- **Reviewer agent** — added "Leakage Prevention" (weight 15) as 12th scoring dimension; tool named `ml-leakage-guard` previously scored papers without evaluating leakage.
- **Gate reliability** — `distribution_generalization_gate`, `calibration_dca_gate`, `ci_matrix_gate`, `self_critique_gate`, `feature_engineering_audit_gate`, `shap_interpretability_gate`, `missingness_policy_gate` all received argparse / fallback / encoding fixes.
- **Onboarding** — auto-generates `configs/outcome_definition.json` stub (source=`exploratory_auto_generated`) so cohort_definition_gate skips publication-grade rigor checks for exploratory runs.
- **Docs / SKILL.md** — 12-dim scoring drift resolved across SKILL.md / README*/ reviewer.yaml; `check_docs_consistency.py` added; peer-review KB section rewritten for honest coverage; 27/28-rule count drift removed.
- **Scope narrowing** — explicit "retrospective cohort binary-classification" framing; omics out of scope.
- **Wave-7 RAG architecture** (from diagnostics, not yet in CHANGELOG `[Unreleased]` body but reflected in artifact mtimes 2026-05-17): tag-overlap re-architected (W7P0 baseline → C1 → C1_v2 → C3 → final → final2); `MMR_COSINE_FLOOR=0.88`, `CP_TAG_BOOST_DENSE_FLOOR=0.70`; H1 BM25 synonym expansion live; mean tag-precision@K = 0.538 (post-wave-7).
- **Wave-8/Wave-9** (per `labeled_precision_at_5.json description`): W8-W2 built 20-query labeled set; W9-A2 extended to 36 queries on 2026-05-17.

---

## D. Open governance questions / pending items (from doc grep `TODO|FIXME|pending|deferred|backlog|KNOWN GAP|caveat`)

1. **All 11 disease KB entries `clinician_review_status: pending`** — both `DISEASE_KB_REVIEW.md` and every `evidence/disease_kb_review/*_review.md` sheet still says "Status: pending — Notes: —" (W8W10 F-06).
2. **No per-disease guideline anchor / `kb_governance` block** — W8W10 F-02 / F-07; open recommendation `disease-kb-v1.2`.
3. **No per-threshold `effective_date` / `guideline_version`** — W8W10 F-03 (ADA/KDIGO drift undetectable).
4. **Lit-KB `change_log` has 1 entry only** — and surfaces 2 un-implemented "future gates" (`silent_trial_gate`, `postmarket_surveillance_gate`) explicitly noted as awaiting MLGG scope extension.
5. **`scripts/rag/evals/harness.py` / `run_eval.py` / `query.py` test coverage 31–45 %** — W7P8 marks the CLI drivers "acceptable" but flags `bm25 retrieve_by_text` (755–788) as a Wave-8 backlog test.
6. **G8 BM25 keyword-extractor fix not yet landed** — diagnosed, ≈ 30–50 LOC patch; no CHANGELOG entry.
7. **E5 systemic issue 1** — `hybrid_rank` empty-query rejection contract is unmet; bridge docstring promise un-fulfilled.
8. **E5 systemic issue 2** — circular import via `scripts/rag/__init__.py` re-export.
9. **`prediction_replay_gate` (KB=1) + `robustness_gate` (KB=7)** — KB curation gaps (E5).
10. **MMR over-penalising on tight-cosine clusters (Q9)** — W2 diagnosis; `MMR_COSINE_FLOOR=0.88` raised but H14 still shows Q9 P@5 = 0.4 free-text.
11. **89.5 % of tag vocabulary is singleton** — W7P6 ROI estimate ~111 canonicalisations; KB writes deferred.
12. **`labeled_precision_at_5.json` "Human-labeled" claim** is contradicted by `labeled_by: Claude Opus 4.7 …` — **M1** in current audit prompt.
13. **`H17_ci_drift_gate_proposal.md`** — explicit "proposal only, no workflow files modified" per CLAUDE.md NEVER rule #2.
14. **`H19` known limitation** — co-presence of resolved+unresolved concerns on same paper can let LLM silently elide unresolved half.

---

## E. Hooks for current audit (M1 / M2 / M3 / m4 / m5 / m6 / m7 / m8)

| Finding | Prior work touching it | Existing handle |
|---|---|---|
| **M1** "human-labeled" misleading in `labeled_precision_at_5.json` | None — file is brand-new (2026-05-17 09:17). `description` field literally opens "Human-labeled ground-truth Precision@5 set"; `labeling_protocol.labeled_by` literally reads `"W8-W2 + W9-A2 (Claude Opus 4.7, 1M context, MLGG agent)"`. Mismatch is in-file. | `references/retrieval_eval/labeled_precision_at_5.json` lines ~3 (description) and ~8 (labeled_by) |
| **M2** P@5 = 0.0 on `preprocessing_split_leakage` L27 and 0.20 on temporal split | Adjacent: W7P1_zero_hit_diagnosis (4 zero-hit scenarios), W7P7_e2_redo, H14_eval_delta (free-text regression). L27 specifically = `"standard scaler normalization fit on full dataset before split"`. Dimension-level: `preprocessing_split_leakage` mean = 0.2 (L11/L27/L28); `split_temporal_validation` mean = 0.2 | `references/retrieval_eval/labeled_precision_at_5.json` L27 + dimension aggregates derivable on the fly. No prior fix; same root cause as G8 (BM25 keyword starvation + tag-overlap collapse on narrow phrasing). |
| **M3** hybrid mean_tag_precision 0.338 < bm25 0.436 despite higher hit-rate | W7P0 reports note this as "diversity-aware caveat: MMR lowers this by design; prefer hit@K for headline." W7P7 redo confirms MMR-driven. Post-wave-7 number now 0.538 (`post_wave7_baseline_hybrid.json`) so the gap closed by ~0.2. | `baseline.json` vs `baseline_hybrid.json` vs `post_wave7_baseline_hybrid.json`; W7P0_final2.md commentary line 7. |
| **m4** 14 gates with single-source lit support | None explicitly. Derived live from `literature-knowledge-base.json`: `ci_matrix_gate, execution_attestation_gate, feature_engineering_audit_gate, feature_lineage_gate, generalization_gap_gate, imbalance_policy_gate, manifest_lock, metric_consistency_gate, permutation_significance_gate, prediction_replay_gate, publication_gate, seed_stability_gate, self_critique_gate, tuning_leakage_gate` | `references/methodology/literature-knowledge-base.json entries[].gates_implementing` |
| **m5** 2 gates with zero lit support | None explicitly. Confirmed: `cohort_definition_gate`, `shap_interpretability_gate` are absent from any `entries[].gates_implementing` set | same file as m4 |
| **m6** 4 entries with no `gates_implementing` tag | None explicitly. Confirmed entries: `LIT-004`, `LIT-018`, `LIT-019`, `LIT-042` have empty `gates_implementing: []` | same file |
| **m7** `entries[:20]` no-sort truncation in `export_review_prompt.py` | **ALREADY FIXED** — `scripts/reporting/export_review_prompt.py:216-222` now sorts via `_lit_relevance_key(e, context_gates, context_dims)` before `[:20]`; comment at L198-200 literally cites "audit finding m7". The script is at `scripts/reporting/`, not `scripts/review/`. | `scripts/reporting/export_review_prompt.py:222` |
| **m8** `bm25.py:271 entries[:5]` possibly debug residue | **NOT debug residue** — it's inside `_validate_kb_shape` (or equivalent), a deliberate sampling shape-check: iterates the first 5 entries to confirm each is a `dict` (anything else is fail-loudly `KBMalformedError`). Comment at L269-270: "Sampling check: non-dict entries would crash retrieval loops the moment they iterate `.get("reviewer_concerns")`. Fail loudly." | `scripts/rag/retrieval/bm25.py:264-275` |
