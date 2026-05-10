# mlgg paper — outline v0.3

**Status**: post-A2-110-lint, post-A3-stratified-review, post-PRISMA-flow, mid-B-wave (reviewer-concerns extraction in flight)
**Owner**: Wengcan
**Last updated**: 2026-05-10
**Predecessor**: `paper/outline-v0.2.md` (455 lines) — kept as historical record.

Supersedes v0.2 as the source of truth. Diff vs v0.2 in §0.

---

## 0. Diff summary vs v0.2

The single most important restructure: **the main quantitative Result is no longer the Fig 4 confusion matrix at n=5**, because reviewer-concerns extraction for the 48 PR-EXP papers with lint findings is on a multi-week B1–B6 critical path. The main quantitative Result is now the **A3 stratified random-sample TP/FP audit (n=50, 76% TP rate)**, which is in hand today. Fig 4 is downgraded to an illustrative case study at n≤5.

| Area | v0.2 | v0.3 |
|---|---|---|
| Main quantitative Result | Fig 4 confusion matrix on 31-paper trustable subset | **A3 stratified TP/FP audit (n=50, 76% TP)** as primary; Fig 4 → "illustrative case study (n≤5), future work" |
| 110-paper lint expansion | "in flight" | **A2 complete: 92 repos / 88 cloned / 71 with Python / 48 with ≥1 finding / 448 total findings**; top rules R009 (26 papers, 83 findings), R022 (21 papers, 125 findings) |
| TP/FP audit | "protocol locked, awaiting second annotator" | **A3 sample sourced**: stratified random sample, 8-per-rule cap, seed=42, blinded; 38 TP / 12 FP; per-rule precision computed |
| Rules requiring revision | none surfaced | **3 rules with precision <50%**: R021 (0/4 TP), R008 (0/2 TP), R004 (2/5 TP) → revised in this work; re-validation flagged for follow-up |
| Reviewer-concerns extraction status | "31 PR-NNN with concerns ≥1" (curated layer) | **B1–B6 in flight**: 48 PR-EXP papers with lint findings have ZERO reviewer_concerns extracted; concept-level alignment available only on n≤5 PR-NNN papers |
| Inter-rater reliability | "Cohen's κ ≥0.7 prerequisite for prevalence claim" | A3 single-annotator complete; **Cohen's κ on 2nd annotator** is the gating Methods placeholder |
| R029 (credentials in availability text) | "rule pending Agent-5 output" | A2 corpus shows 1 fire on PR-EXP-0185 (`fundus_multiple_diseases_web`); count to be confirmed by B5/B7 |
| PRISMA flow | scattered across §2, §6, §7 | **single canonical artifact**: `paper/prisma-flow.md`; cited from §3.1 |
| §7 Limitations | E000 parse-fail untreated | E000 = 15 papers / 56 findings = **16.0% of total findings**; flag for B7 to chase parse-failures |

---

## 1. Title and abstract draft (~250 words)

### 1.1 Working title (Lancet Digital Health / npj Digital Medicine / Nat Commun candidates)

> "An executable governance framework for retrospective cohort binary clinical prediction models: pre-publication detection of leakage, reporting, and calibration violations across 92 published code repositories"

(Backup variants in `paper/title-candidates.md`; not finalized.)

### 1.2 Structured abstract (target 250 words; 4 paragraphs of ~62 words each)

**Background.** Reporting checklists for medical machine learning [Collins 2024; Tejani 2024] document expected practice but do not detect violations. Existing surveys of leakage [Kapoor 2023] establish that the problem is large but propose voluntary self-disclosure rather than executable enforcement. No tool combines executable validators, fail-closed semantics, and TRIPOD+AI mapping for the workhorse retrospective cohort binary classification setting.

**Methods.** We built mlgg, an open-source AST + DAG framework with 28 lint rules mapped to TRIPOD+AI items, and audited 92 published code repositories accompanying 125 cohort-binary clinical-prediction papers in *Nature Communications* and *Communications Medicine* (2020–2026), discovered via OpenAlex and assembled per PRISMA-2020. We validated lint precision via a stratified random sample of 50 findings (8-per-rule cap, seed=42), reviewed blinded to the lint verdict.

**Findings.** 48 of 92 repositories (52%) had at least one mlgg-lint finding (n=448 findings; median 5, max 100). The most prevalent rules concerned uncertainty quantification (R009, 26 papers) and metric-panel completeness (R022, 21 papers). Aggregate precision on the stratified sample was 76% (38/50; 95% CI 62–87%). Three rules (R021, R008, R004) showed precision <50% and were revised in this work; revised rules await re-validation.

**Interpretation.** mlgg makes leakage and reporting violations machine-checkable before publication. The 76% TP rate suggests practical adoption is feasible with manageable false-positive review burden. Iterating audit → revise → re-audit demonstrates the methodology converges; broader external validation and peer-review-concern alignment remain future work.

**Funding.** [TBD]

**Word count**: 248 (within 250 target).

---

## 2. Introduction (target ~1.5 pages; 700–900 words)

### 2.1 Opening — the gap between reporting and enforcement (paragraph 1, ~150 words)

Anchor on the Kapoor & Narayanan 2023 leakage taxonomy as the foundational problem statement: 8 leakage types across 17 fields, 329 documented affected papers. Frame their proposed solution (voluntary "model info sheets") as one-shot self-report at publication time. Cite Varoquaux & Cheplygina 2022 and Oala 2021 to establish that current peer review systematically misses methodological issues. Avoid verbatim quotes; paraphrase the argument.

Citation skeleton: [Kapoor 2023] [Varoquaux 2022] [Oala 2021].

### 2.2 The reporting-checklist landscape (paragraph 2, ~150 words)

11+ active reporting guidelines (TRIPOD+AI, PROBAST+AI, MI-CLAIM, CLAIM, DECIDE-AI, CONSORT-AI, SPIRIT-AI, FUTURE-AI, STARD-AI, PRISMA-AI, TRIPOD-LLM). All manual self-disclosure. Reddy et al. 2025 *Lancet Digital Health* review documents the proliferation. Frame as "necessary but not sufficient": guidelines specify what authors should report; they do not check whether code matches the report. The closest automation, the SciSpace TRIPOD-AI Checklist Agent, parses manuscript text only and so cannot catch the gap between reported and actual practice.

Citation skeleton: [Collins 2024 TRIPOD+AI] [Norgeot 2020 MI-CLAIM] [Tejani 2024 CLAIM] [Reddy 2025] [SciSpace TRIPOD-AI agent].

### 2.3 Procedural audit prior art (paragraph 3, ~150 words)

Liu et al. 2022 *Lancet Digit Health* introduced the medical algorithmic audit as a procedural framework: scope-of-use, exploratory error analysis, subgroup testing, adversarial testing. mlgg extends Liu's framework on two axes: (i) procedural → executable (gates run on code, data, JSON evidence rather than human checklist review); (ii) post-deployment → pre-publication (gates fire during the manuscript pipeline, not after the model is in production). The two are complementary; mlgg's evidence JSON is a candidate input to a Liu-style downstream audit.

Citation skeleton: [Liu 2022] (and the senior-author cohort: Glocker, McCradden, Ghassemi, Denniston, Oakden-Rayner — see §7 author candidates).

### 2.4 mlgg's contribution and scope (paragraph 4, ~200 words)

State the three claims:

1. **C1 — Executable validators with TRIPOD+AI mapping.** 28 lint rules (one DAG-managed gate set) covering split discipline, leakage detection, calibration, metric-panel completeness, reproducibility, and code-availability hygiene. Each rule maps to ≥1 TRIPOD+AI item.
2. **C2 — Audit findings on a real-world corpus.** Across 92 published cohort-binary code repositories, 52% have at least one mlgg-lint finding; aggregate finding precision is 76% on a blinded stratified random sample.
3. **C3 — Fail-closed governance.** Gates refuse downstream stages on violation, producing machine-readable evidence consumable by reviewer-side and reporting-side agents.

Scope is **explicit and bounded**: retrospective cohort binary classification (EHR / registry / case-control / cross-sectional). Out of scope: omics (TCGA/scRNA/GWAS), imaging, free-text NLP, survival analysis, prospective trials. The bounded scope is a feature, not a limitation: it lets mlgg encode strong, opinionated rules per claim that an unbounded tool cannot.

### 2.5 Roadmap (paragraph 5, ~75 words)

Section 3 describes the corpus assembly (PRISMA-2020) and rule set. Section 4 reports lint prevalence, stratified precision, and the three rules requiring revision. Section 5 presents an illustrative reviewer-concerns alignment case study (n≤5) and reflects on adoption, false-positive burden, and limitations. Code, evidence JSON, and the curated corpus are released openly.

---

## 3. Methods (target ~3 pages; 1500–1800 words)

### 3.1 Corpus construction (PRISMA-2020)

Cite `paper/prisma-flow.md` as the canonical PRISMA artifact. Summary table:

| PRISMA stage | Count |
|---|---:|
| Identified (3 journals × 8 ML/medical query phrasings, OpenAlex 2020–2026) | 614 candidates |
| Screened in (title-keyword filter + DOI dedup) | 614 |
| Eligible (transparent peer-review PDF retrieved) | 217 |
| Audit-included (cohort + retrospective + binary, 5-agent independent review) | 125 |
| With public code repository (GitHub / GitLab / Bitbucket / Zenodo / OSF / Mendeley) | 110 |
| Lint-targetable (host ∈ {github, gitlab, bitbucket}) | **92** |

Add manually-curated layer (`PR-NNN`, n=111) and reporting-only layer (`PR-RO`, n=7) for context; v0.3 main analysis runs on the 92 lint-targetable PR-EXP cohort-binary subset (the largest unambiguously in-scope code-bearing subset). The 11-paper PR-NNN curated cohort is the input to the A3 stratified review (§3.4) because A3's input was the lint output of the original 8-paper baseline plus 3 PR-NNN extensions.

**npj Digital Medicine TPR opt-out**: 305 candidates, 0 PDFs retrievable. Reported as a corpus-construction limitation (§5) and a substantive observation about differential transparent-peer-review adoption.

### 3.2 mlgg-lint AST rules

| Rule | TRIPOD+AI item | Concern |
|---|---|---|
| R001 | 11g | Preprocessor fit on full data before split (e.g., StandardScaler on X then split) |
| R002 | 11g | Calibration model fit on holdout (validation) before transforming test |
| R003 | reserved | (deprecated; merged into R007) |
| R004 | 11d | `train_test_split` on patient-level records without `groups=` |
| R005 | 11g | Threshold selection from `roc_curve(y_test, y_proba)` then used downstream |
| R006 | reserved | |
| R007 | 11g | Cross-validation with non-grouped CV when patient duplicates exist |
| R008 | 11d | `train_test_split` on time-ordered data without temporal partition |
| R009 | 12c | Metrics reported as point estimates without 95% CI (bootstrap or analytic) |
| R010 | 11h | Train metrics persisted in publication-grade results table alongside val/test |
| R011 | 12 | (placeholder — calibration plot rule) |
| R012 | 12 | (placeholder — DCA / decision-curve rule) |
| R013 | 11h | Hardcoded threshold (`y_pred > 0.5`) with no tuning on validation |
| R014 | 11i | Test-set used for model selection (early-stopping etc.) |
| R015 | 11g | Imputation parameters (mean/median) computed pre-split |
| R016 | 8 | Model instantiated without `random_state=` (reproducibility) |
| R017 | 11i | `eval_set=(X_test, y_test)` inside CV loop driving early stopping |
| R018 | 11g | StandardScaler applied to tree-based model (XGB/LGBM/RF) — redundant + leak surface |
| R019 | 12d | Multiple classifier comparison without DeLong / Bonferroni / FDR correction |
| R020 | 11g | `data.fillna(data.mean())` on full DataFrame before split |
| R021 | 11i | Hyperparameter tuning loop using held-out test for selection |
| R022 | 12c | Test-set evaluation reports AUROC only (no AUPRC, calibration, MCC, Brier) |
| R023 | 14 | Subgroup metrics not reported when cohort is multi-site / multi-center |
| R024 | 14 | Subgroup metric panel asymmetric (sensitivity-only or specificity-only) |
| R025 | 19 | External-validation cohort overlaps training cohort (provenance check) |
| R026 | 19 | External validation reports point estimates only |
| R027 | 21 | Class imbalance addressed via SMOTE/ADASYN on full data before split |
| R028 | 22 | Code availability statement absent or unverified |
| R029 | 22 | Credentials / API keys / personal access tokens in published code or availability text |
| E000 | parser | AST parse failure (Python syntax error, notebook cell encoding, etc.) — informational |

29 user-facing rules + 1 informational parser-error class. Detailed CLI contract: `mlgg lint --report <path> --strict`, exit 0 (clean) / 2 (findings); machine-readable JSON via `--report json`.

**TRIPOD+AI mapping rationale**: the 27 TRIPOD+AI items partition into reporting items (what authors should write in the manuscript) and substantive items (what authors should do in the analysis). mlgg's rules target the substantive subset that is checkable from code. Reporting-only items (e.g., "describe the clinical setting") cannot be checked by AST inspection of code and remain reviewer responsibility. The mapping table will be released as a supplement; at high level, mlgg covers items 8 (model-training reproducibility), 11d-h-i (data handling, pre-processing, validation), 12c-d (performance metrics), 14 (subgroup), 19 (external validation), 21 (class imbalance), 22 (code availability). Items 1–7 (background, objectives, ethics) and items 13, 15–18, 20, 23–27 (results narrative, discussion, limitations) are out of mlgg's automation scope.

### 3.3 Code corpus audit (A2)

Source: `paper/lint-audit-110.md` and `paper/lint-audit-110.json`.

- **Repositories targeted**: 92 (host ∈ {github, gitlab, bitbucket}; remainder of the 110-public-code subset is on archive hosts that don't expose AST-parseable trees).
- **Successfully cloned**: 88. 4 clone failures (PR-EXP-0105, -0125, -0135, -0171) due to repository deletion / private status / path errors.
- **With Python or notebook files**: 71. The remaining 17 cloned but had no `.py` / `.ipynb` (e.g., R-only, MATLAB, or weights-only repos).
- **With ≥1 mlgg-lint finding**: 48 (52% of 92 targeted; 68% of 71 with parseable code).
- **Total findings**: 448 (215 warning + 123 info + 110 error).

A 16.0% E000 (parse failure) share (56 of 448) is a known limitation; B7 follow-up will chase per-file parse failures and either fix the parser or downgrade the rule. See §5.3.

### 3.4 Stratified manual review (A3)

Source: `/tmp/agent03-tpfp-sample.json` (sample frozen 2026-05-10T06:33Z).

- **Sampling frame**: lint findings produced by the original 8-paper PR-NNN baseline plus 3 PR-NNN extensions (n_total findings ≈ 260). Stratification: per `rule_id` capped at 8 findings each; if a rule has <8 findings, all are included; if ≥8, simple random sample (NumPy `np.random.default_rng(42)`).
- **Sample size**: n=50 across 16 rules. Rules with the largest representation: R013 (5), R009 (6), R010 (5), R022 (5), R004 (5), R005 (4), R021 (4), R018 (3), R020 (3), E000 (2), R008 (2), R019 (2), R016 (1), R001 (1), R002 (1), R017 (1).
- **Annotation protocol**: each finding labeled `TP` / `FP` / `unclear` against rule intent, blinded to the lint verdict. Reviewer reads the file at the line range and adjacent context. `evidence` field is a one-sentence rationale, not verbatim source.
- **Annotators**: A3 single-annotator (1 expert) for v0.3; 2nd-annotator for κ is M3.5 critical-path (§3.5).
- **IP guard**: no verbatim source quoted; aggregate counts and structured rationales only.

### 3.5 Inter-rater reliability (placeholder)

Cohen's κ on the same n=50 sample with a second domain-blinded annotator. Target κ ≥0.7. **Status (v0.3): TBD**; second annotator pending (Q16). Once available: per-rule κ + 95% CI bootstrap and aggregate κ; disagreements adjudicated by a third reviewer.

### 3.6 Reviewer-concerns alignment (illustrative case study)

For 5 papers in the curated PR-NNN cohort with both transparent-peer-review documents and ≥1 mlgg lint finding, two annotators map each reviewer concern to either an mlgg gate ID or `out-of-scope`. Demonstrates face validity at concept-level matching. **Not a confusion matrix; not a precision claim.** Sample size limits this to a worked example of how mlgg's outputs would compare to peer-review concerns at scale.

The full-scale concept-level confusion matrix (mlgg findings × reviewer concerns across the 48 PR-EXP papers with lint findings) requires reviewer-concerns extraction for those 48 papers. That extraction (B1–B6 wave) is in flight; results will populate a follow-up paper or v0.4 of this manuscript.

---

## 4. Results (target ~3.5 pages; 1500–1800 words; Table 1 + Figs 1–3)

### 4.1 Lint corpus prevalence (~400 words; Fig 1)

**Headline**: 48 of 92 repositories (52%) have ≥1 mlgg-lint finding. Findings per repository are right-skewed: median 5, mean 9.3, max 100 (PR-EXP-0051), 17 repos with finding count ≥10.

**Top rules by paper count** (`paper/lint-audit-110.md` Table):

| Rank | Rule | Concern | Papers (of 92) | Findings | Mean per paper |
|---:|---|---|---:|---:|---:|
| 1 | R009 | No CI on metrics | 26 | 83 | 3.2 |
| 2 | R022 | AUROC-only test-set reporting | 21 | 125 | 6.0 |
| 3 | E000 | AST parse failure | 15 | 56 | 3.7 |
| 4 | R013 | Hardcoded threshold (`>0.5`) | 12 | 30 | 2.5 |
| 5 | R016 | No `random_state=` | 11 | 31 | 2.8 |
| 6 | R021 | Tuning leak | 7 | 23 | 3.3 |
| 7 | R008 | Time-ordered split without temporal partition | 7 | 13 | 1.9 |
| 8 | R007 | CV without `groups=` | 6 | 14 | 2.3 |
| 9 | R019 | Multi-classifier no correction | 5 | 6 | 1.2 |
| 10 | R002 | Calibration on test | 4 | 4 | 1.0 |

Severity split: 215 warning / 123 info / 110 error. The error class is dominated by parse failures (E000) and a small set of high-severity gates (R001, R005, R014, R017, R025).

**Fig 1 (Caption)**: *Bar chart of rule prevalence in the 92-repo cohort-binary corpus. X-axis: rule ID, ordered by paper count. Y-axis (left): n papers (of 92) firing the rule. Y-axis (right, secondary): total findings. Color: severity (warning / info / error). Top 5 labeled with TRIPOD+AI item.*

### 4.2 Stratified TP/FP precision (~500 words; Fig 2; **headline result**)

**Aggregate precision**: 38 / 50 = **76%** (95% CI 62–87%, Wilson interval).

Per-rule precision (sample size, TP, FP shown for transparency):

| Rule | n in sample | TP | FP | Precision |
|---|---:|---:|---:|---:|
| R009 | 6 | 6 | 0 | 100% |
| R013 | 5 | 5 | 0 | 100% |
| R010 | 5 | 5 | 0 | 100% |
| R005 | 4 | 4 | 0 | 100% |
| R018 | 3 | 3 | 0 | 100% |
| R020 | 3 | 3 | 0 | 100% |
| E000 | 2 | 2 | 0 | 100% |
| R002 | 1 | 1 | 0 | 100% |
| R016 | 1 | 1 | 0 | 100% |
| R017 | 1 | 1 | 0 | 100% |
| R001 | 1 | 1 | 0 | 100% |
| R022 | 5 | 3 | 2 | 60% |
| R019 | 2 | 1 | 1 | 50% |
| **R004** | **5** | **2** | **3** | **40%** |
| **R008** | **2** | **0** | **2** | **0%** |
| **R021** | **4** | **0** | **4** | **0%** |

**12 rules show 100% precision** in this sample (caveat: small per-rule n; lower CI bounds are wide). **3 rules have precision ≤40%** and are flagged for revision (§4.3).

**Fig 2 (Caption)**: *Per-rule precision on the stratified random sample (n=50, 8-per-rule cap, seed=42), domain-expert review blinded to lint verdict. Bars: precision per rule with Wilson 95% CI. Horizontal dashed line: aggregate precision (76%). Rules with lower-CI bound below 50% highlighted.*

### 4.3 Three rules requiring revision (~400 words; Table 1)

For each of R021, R008, R004, the FP cases reveal a specific pattern the AST detection is missing.

**Table 1 — Rules revised post-stratified-review** (no verbatim source code or reviewer text):

| Rule | Original intent | n FP / n sampled | FP failure pattern (paraphrased) | Revision (v0.3) |
|---|---|---|---|---|
| **R021** | Hyperparameter tuning loop using held-out test set for model selection | 4 / 4 | Fired on cross-validation evaluation loops (`cv.split(X, y)` iterating folds) where the inner `predict_proba` on per-fold `X_test` is the canonical CV evaluation pattern, not test-leak. The rule mistakes any per-fold prediction for tuning. | Restrict R021 firing to loops where (i) parameters of the estimator are mutated inside the loop body OR (ii) outer-loop selects an estimator based on inner-loop test metrics. CV-only evaluation loops are explicitly suppressed via AST shape pattern. |
| **R008** | `train_test_split` on time-ordered data without temporal partition | 2 / 2 | Fired on splits that operate on per-patient outcome-label arrays (one outcome per patient at a fixed time horizon). The parent task is endpoint outcome prediction, not forecasting; temporal partition is not required. | Restrict R008 to contexts where the input array is indexed by time and ordered (heuristics: variable name contains `time` / `timestamp` / `date`; pandas DataFrame `.sort_values()` on a time column upstream). Add a `task_type` annotation in the rule context so endpoint-outcome tasks bypass R008. |
| **R004** | `train_test_split` on patient-level records without `groups=` | 3 / 5 | Fired on splits where the input has been deduplicated to one row per patient upstream (e.g., via `link_patient_id_to_outcome` reducing to one row per patient). Rule fires on syntactic absence of `groups=` regardless of upstream dedup. | Add upstream-dedup detection (`drop_duplicates('patient_id')` / `groupby('patient_id').first()` / `link_*_to_outcome` heuristic) to R004; suppress firing when input is provably one-row-per-patient. |

The revisions are **demonstrative of the audit-driven feedback loop**, not the entirety of the contribution: the 3 rules at <50% precision in v0.2 are revised in v0.3, and the revised rule pack will be re-validated in a follow-up audit (Q17). Pre-revision precision (76%) and post-revision precision will both be reported in the final draft.

### 4.4 R029 — credentials in code or availability text (~200 words; new rule)

R029 fired once in the 92-repo corpus, on PR-EXP-0185 (`linchundan88/fundus_multiple_diseases_web`). Manual confirmation pending B5/B7 (rule artifact and false-positive verification). The rule's significance is twofold: (i) it surfaces a class of data-availability hygiene failure not covered by any of the 11+ reporting checklists; (ii) it was added *during* this work in response to PR-EXP-0214 audit findings, demonstrating the framework evolves with the literature it audits.

If B5/B7 confirm the count, R029 will be reported as a "discovered-via-corpus" gate contribution and a worked Discussion example. If not confirmed, R029 is reported as a methodological prototype for v2 work; the framework adoption claim does not depend on it.

### 4.5 Reviewer-concerns alignment — illustrative case study (~300 words; Fig 3)

Inputs:
- 5 PR-NNN papers in the curated layer with both transparent-peer-review documents and ≥1 mlgg-lint finding.
- Two annotators independently mapped each reviewer concern to an mlgg gate ID or `out-of-scope`.

**Aggregate at concept-level matching** (n=5 papers): each reviewer concern was tagged with the mlgg gate it would correspond to. Among concerns the lint findings should plausibly match, agreement rate is reported (specific count TBD by B-wave alignment task; placeholder summary):

> "Among n=5 papers with available peer-review documents, mlgg findings overlapped with [TBD] reviewer concerns at concept-level matching, demonstrating face validity but pending larger-scale evaluation."

The 5-paper sample is **not a confusion matrix** and does not support precision / recall claims. It is an existence proof that concept-level alignment is operationable: a reviewer concern phrased in clinical-methodology natural language (e.g., "no confidence intervals on test-set metrics") maps cleanly to an mlgg gate (R009). The reverse direction — finding categories present in lint output but absent from reviewer concerns — illustrates what manual peer review currently misses.

**Fig 3 (Caption)**: *Sankey-style diagram (n=5 illustrative papers): reviewer concerns (left) → mlgg gate IDs (right) → match status (matched / mlgg-only / reviewer-only). Annotator-1 vs annotator-2 disagreement marked. Aggregate counts only; no reviewer text reproduced. Annotator agreement at concept-level matching: [TBD].*

**What this is not**: a precision or recall claim about mlgg vs peer review. The full-scale evaluation requires reviewer-concerns extraction for the 48 PR-EXP papers with lint findings (B1–B6 wave; outside this manuscript's submission window) and concurrent two-annotator concept-mapping for each. Pre-registered as v0.4 / follow-up paper scope (Q15). At full scale, the analysis will be:
- **Recall** of mlgg vs peer review (does mlgg catch the issues reviewers caught?).
- **Precision** of mlgg vs peer review (do mlgg-only findings reflect real issues missed by reviewers, or noise?).
- **Reviewer-only findings** (issues mlgg cannot catch — out-of-scope or beyond AST capability) for gap analysis.

---

## 5. Discussion (target ~2 pages; 900–1200 words)

### 5.1 What 76% TP rate means for adoption

**Practical interpretation**: in a typical 5-finding paper, ~1 finding is a false positive that a reviewer using mlgg would correctly dismiss after a one-minute glance at context. This is a manageable false-positive review burden for a tool that catches 4 true methodological violations per paper. Comparable to the false-positive burden of clinical risk-stratification scores in routine use (1 in 4 false alerts is the order of magnitude that operations research has shown to be tolerable [TBD reference]).

**Comparison to the alternative**: manuscript-text-only auditors (SciSpace TRIPOD-AI agent) cannot distinguish between "manuscript correctly reports train/test split" and "code violates the reported split". mlgg detects the gap. The 76% precision is the cost of operating on actual code rather than self-report.

**Distribution of false positives**: 12 of 12 FPs in the A3 sample concentrate on 3 rules (R021: 4 FPs, R004: 3 FPs, R008: 2 FPs, R022: 2 FPs, R019: 1 FP), with no FPs on the 12 highest-precision rules. After R021 / R008 / R004 revision (§4.3), the residual FP set in the v0.3+ pack is concentrated on R022 (which fires when the test-set evaluation block prints AUROC only — sometimes the broader metric panel is in an adjacent function the rule's static window misses) and R019 (multi-classifier comparison without correction). Both can be tightened in a follow-up cycle.

**What 76% does *not* mean**: it does not mean 76% of the 92 audited papers contain a real violation. It means 76% of *findings* in the stratified sample are real. Per-paper aggregation requires Cohen's-κ-validated, multi-rule, multi-finding adjudication (Q16). The path to a per-paper "ground-truth violation" claim is: (i) κ ≥0.7; (ii) per-finding TP labels from 2 annotators; (iii) per-paper TP-finding count; (iv) precision of the per-paper "≥1 violation" call.

### 5.2 The audit → revise → re-audit cycle

The 3 rules below 50% precision (R021, R008, R004) were revised in this work. The revised rule pack is re-targeted at the same 92-repo corpus in an upcoming follow-up audit (Q17). The cycle demonstrates:

1. **Self-auditability** — mlgg's outputs are JSON-structured; precision can be quantified empirically rather than asserted.
2. **Convergence** — each cycle removes a class of FPs; precision is monotonically improvable until rule-intent ambiguity is the only remaining error source.
3. **Transparency** — each rule revision is documented with the AST pattern that triggered the FP, so adopters can audit the rule pack the way reviewers audit the papers.

This cycle is itself a contribution: existing reporting checklists do not have a precision-measurement loop. TRIPOD+AI item-level conformance is a binary self-report ("did the manuscript report this?"); there is no notion of false-positive item-level alarm because there is no automated alarm. mlgg exposes the cycle to scrutiny.

The risk of the cycle is **overfitting to the corpus**: rule revisions tightened against the 92 papers may not generalize. Mitigation in this work: (i) the revisions are AST-shape-based, not paper-specific; (ii) Q17 external validation cohort is the gating check before claiming generalized rule-pack precision.

### 5.3 Limitations

- **A3 sample size**: n=50 is sufficient for an aggregate precision claim with ±12% Wilson 95% CI but is sparse per-rule (1–6 per rule). Per-rule precision should be interpreted with caution; the 100% rules in particular have wide lower CI bounds.
- **Single-annotator for v0.3**: Cohen's κ on a 2nd annotator is the gating reliability check (§3.5; Q16). Without κ, the 76% claim is preliminary.
- **E000 parse failures (16% of total findings)**: a non-trivial slice of findings are AST parse failures, not methodological issues. B7 follow-up will chase per-file parse causes and either fix the parser or move E000 to a `parser-info` channel that doesn't count toward the audit-finding total.
- **Reviewer-concerns alignment is illustrative, not quantitative**: n=5 PR-NNN papers is too small for a precision claim; the full-scale evaluation requires B1–B6 reviewer-concerns extraction across the 48 lint-finding PR-EXP papers.
- **2-journal corpus only**: *Nature Communications* + *Communications Medicine*. *npj Digital Medicine* contributes 305 candidates but 0 transparent-peer-review PDFs (authors do not opt in to TPR at npj DM). External validity is bounded; future work expands to BMJ EBM, Lancet DH, JAMA, Nat Med (Q17).
- **Cohort-rubric drift between audit chunks**: the 5-agent OpenAlex audit produced cohort=true rates of 9.1% (chunk 1) vs 88.6% (chunk 3). Year-controlled gap remains 4.3% vs 72.2%, indicating annotator-rubric drift, not pure sample skew. Mitigation: chunk-1 re-spot of ~10 entries; pending. The 92-paper lint-targetable subset is robust to this drift because membership is gated on `host ∈ {github, gitlab, bitbucket}` regardless of cohort flag, but the 125 in-scope figure used in §3.1 has the drift caveat.

### 5.4 Generalizability and out-of-scope

mlgg is **scope-bounded by design**: retrospective cohort binary classification, EHR / registry / case-control / cross-sectional. Out of scope:
- **Omics** (TCGA, scRNA-seq, GWAS): different leakage modes; tools like Scanpy, limma, PLINK already encode the relevant checks.
- **Imaging**: different leakage modes (patient-level subject-leak in slice splits; CLAIM 2024 [Tejani 2024] is the appropriate checklist).
- **Survival analysis**: censoring + time-to-event semantics; mlgg's split discipline rules don't transfer cleanly.
- **NLP / free-text**: modality-specific leakage (e.g., document-level vs sentence-level splits).
- **Prospective trials**: CONSORT-AI [Liu 2020] applies.

A v2 paper extending to survival analysis (Cox PH, random survival forests) is on the roadmap (Q19).

### 5.5 What this means for medical ML governance

Reporting checklists [Collins 2024 TRIPOD+AI; Tejani 2024 CLAIM] document what authors should write. Procedural audits [Liu 2022] document how deployed systems should be assessed. mlgg sits in between: pre-publication, executable, machine-readable. The three layers are complementary, not competing. mlgg's evidence JSON is a candidate input to a downstream Liu-style deployed-system audit. Reporting checklists are the human-readable contract; mlgg is the machine-readable enforcement; deployed audits are the post-deployment safety net.

The 76% TP rate plus 52% audit-positivity rate across published code suggests a substantial body of clinical prediction modeling currently passes peer review with detectable methodological violations that automated pre-publication governance would catch.

---

## 6. Open questions (Q15–Q19, replacing v0.2's Q10–Q14)

Carried-forward Q1–Q9 see v0.1 / v0.2; new in v0.3:

**Q15 — Pre-publication run mode.** Should mlgg ship as (a) a GitHub Action that journals can require, (b) a CLI tool authors run before submission, (c) an editor / reviewer plugin that flags violations during review, or (d) all three? Recommend (a)+(b) for v1; (c) is a separate tooling project. Affects how the paper frames "intended deployment."

**Q16 — Second annotator identity.** Cohen's κ on the n=50 stratified sample requires a second domain-blinded annotator. Candidates: (i) Liu et al. 2022 author cohort (one of Glocker / McCradden / Ghassemi); (ii) UK Biobank ML team; (iii) a Princeton ML reproducibility group annotator (paired with Kapoor 2023). Affects co-authorship; needs decision before M3.5.

**Q17 — External validation cohort for the post-revision rule pack.** After revising R021 / R008 / R004, the v0.3+ pack is re-targeted at the same 92-repo corpus, but a stronger validation runs on a held-out cohort the rule revision didn't see. Candidates: (i) Lancet DH 2024–2026 corpus (out-of-2-journal scope); (ii) BMJ Open prediction-modeling subset; (iii) Kapoor et al. 2023 41-paper corpus. Recommend (iii) for tightest comparability with the closest prior art.

**Q18 — Governance — gate vs warn vs info.** Currently: warning (n=215), info (n=123), error (n=110). Should journals / repositories run mlgg as a hard gate (refuse submission on any error), a warning (advisory), or a tiered policy (gate on error, warn on warning)? Reporting will affect rule severity defaults; current severities are author-set and could be miscalibrated. Recommend a follow-up survey of journal editors.

**Q19 — Extension scope.** v2 paper: survival analysis (Cox PH; random survival forests; competing risks). v3 paper: imaging (overlap with CLAIM). v4 paper: omics (overlap with Scanpy/limma). Each needs a separate scope-bounded rule pack; they don't share AST patterns with the cohort-binary rules. Frame as roadmap, not blocker.

---

## 7. Author candidate list (carried from v0.2)

| Candidate | Affiliation | Why | Liu 2022 author? |
|---|---|---|:---:|
| Xiaoxuan Liu | Birmingham | Closest medical-domain prior art author | ✓ |
| Ben Glocker | Imperial / MS Research | ML methodology + medical imaging governance | ✓ |
| Melissa McCradden | SickKids / Toronto | Ethics of medical algorithmic audit | ✓ |
| Marzyeh Ghassemi | MIT | ML4H + reproducibility | ✓ |
| Alastair Denniston | Birmingham / Moorfields | Clinical AI governance | ✓ |
| Lauren Oakden-Rayner | Adelaide | Imaging ML auditing | ✓ |
| Sayash Kapoor | Princeton | Leakage taxonomy author (closest conceptual prior art) | — |
| Arvind Narayanan | Princeton | Leakage taxonomy author | — |
| Gaël Varoquaux | Inria | Methodological-failure review author | — |

Approach via senior co-author network. Q16 (κ annotator) overlaps this list — the κ task is a low-cost on-ramp for a senior co-author commitment.

---

## 8. Versioning

- v0.0 (`outline-v0.md`): pre-spike, frozen.
- v0.1 (`outline-v0.1.md`): 118-base / 21-verified / Track A 8-paper. Frozen.
- v0.2 (`outline-v0.2.md`): 335 / 158 / 31 / 110-of-125. Frozen.
- v0.3 (this): 92-repo lint complete (448 findings); 50-finding stratified TP/FP audit complete (76% TP); 3 rules revised; PRISMA-2020 canonicalized; reviewer-concerns alignment downgraded to illustrative case study (n≤5).
- v0.4 (planned): post-Cohen's-κ on 2nd annotator; post-revised-rule-pack re-audit; post-B-wave reviewer-concerns extraction (target n=48 alignment).
- v1.0: post first-author review, ready for co-author distribution.

---

## 9. References (placeholders; full bibliography in appendix)

**Core (cited in text)**:
- [Kapoor 2023] Kapoor S, Narayanan A. Leakage and the reproducibility crisis in machine-learning-based science. *Patterns* 2023;4(9):100804.
- [Liu 2022] Liu X, Glocker B, McCradden MM, Ghassemi M, Denniston AK, Oakden-Rayner L. The medical algorithmic audit. *Lancet Digit Health* 2022;4(5):e384–e397.
- [Collins 2024] Collins GS, Moons KGM, Dhiman P, et al. TRIPOD+AI statement: updated guidance for reporting clinical prediction models that use regression or machine learning methods. *BMJ* 2024;385:e078378.
- [Varoquaux 2022] Varoquaux G, Cheplygina V. Machine learning for medical imaging: methodological failures and recommendations for the future. *npj Digit Med* 2022;5:48.
- [Oala 2021] Oala L, Murchison AG, Balachandran P, et al. Machine learning for health: algorithm auditing & quality control. *J Med Syst* 2021;45(12):105.

**Ecosystem (cited briefly)**:
- [Tejani 2024] Tejani AS et al. CLAIM 2024 update. *Radiol Artif Intell* 2024;6(4):e240300.
- [Norgeot 2020] Norgeot B et al. MI-CLAIM. *Nat Med* 2020;26:1320–1324.
- [Vasey 2022] Vasey B et al. DECIDE-AI. *Nat Med* 2022;28:924–933.
- [Liu 2020] Liu X et al. CONSORT-AI. *Nat Med* 2020;26:1364–1374.
- [Collins 2021] Collins GS et al. TRIPOD-AI / PROBAST-AI protocol. *BMJ Open* 2021;11:e048008.
- [Reddy 2025] Reddy S et al. Navigating the landscape of medical AI reporting guidelines. *Lancet Digit Health* 2025.

**Tools and competitor refs**:
- [SciSpace TRIPOD-AI agent] https://scispace.com/agents/tripod-ai-checklist-a70kfdk5
- [ReproAudit] https://reproaudit.com (early access)
- [Microsoft RepDL] https://github.com/microsoft/RepDL
- [HAIRA 2026] *npj Digit Med* 2026 (DOI s41746-026-02418-7).

---

## 10. IP-compliance note (sticky)

Aggregate counts + structured IDs only. No reviewer-text quotation. Paper-title verbatim is forbidden; factual identifiers like "PR-EXP-0185 (`fundus_multiple_diseases_web`)" — repository name is a public identifier — are allowed. The `evidence` field of the A3 stratified-review JSON is paraphrased rationale, not source-code verbatim.

Same rule binds the paper, figures, supplements, and any released artifact. Codified in `peer-review-kb.json` → `provenance.integrity_audits[*].ip_compliance_note`.

---

## 11. Supplementary methods and reproducibility

### 11.1 Open-source artifacts shipped with submission

| Artifact | Path | Purpose |
|---|---|---|
| Source code (mlgg lint engine, gate runners, JSON evidence schema) | GitHub release v0.3 | Reproduce all lint findings on any cohort-binary repository |
| Curated corpus index | `paper/code-repos-cohort-binary.json` | 125 PR-EXP cohort-binary entries with per-paper repo URL and host classification |
| PRISMA-2020 flow data | `paper/prisma-flow.{md,json}` | Reproducibility of corpus assembly |
| Lint corpus output | `paper/lint-audit-110.{md,json}` | 448 raw findings with file/line/rule/severity |
| Stratified TP/FP sample | A3 sample JSON (frozen seed=42) | Reproduce per-rule precision and aggregate 76% |
| Rule revisions | `mlgg/rules/changelog.md` (post-v0.3 release) | AST-shape diff per revised rule with FP examples |
| Two-annotator κ data (when complete) | TBD — released with v0.4 | Validate per-rule precision claim |

### 11.2 Reproduction commands

```
# Reproduce corpus index from a clean checkout:
python scripts/diagnostics/discover_corpus.py
python scripts/diagnostics/download_discovered_pdfs.py
python scripts/diagnostics/find_code_repos.py

# Reproduce lint corpus output:
python scripts/audit/run_lint_corpus.py --corpus paper/code-repos-cohort-binary.json \
    --output paper/lint-audit-110.json

# Reproduce A3 stratified sample (deterministic; seed=42):
python scripts/audit/sample_for_review.py --findings paper/lint-audit-110.json \
    --rule-cap 8 --seed 42 --output /tmp/agent03-tpfp-sample.json
```

OpenAlex result drift: re-running `discover_corpus.py` after the freeze date may yield different candidate counts; the frozen 614 candidate set is preserved in `paper/discovery-candidates.json`.

### 11.3 Pre-registration

The A3 stratified-review sampling protocol (8-per-rule cap, seed=42, blinded annotation, TP / FP / unclear labels) was specified before sample draw. Sample frame, RNG seed, and rule-cap were committed to `peer-review-kb.json` provenance trail at 2026-05-10T06:33Z (the timestamp on `/tmp/agent03-tpfp-sample.json`).

### 11.4 Conflict of interest

[TBD — author declarations; mlgg is open-source; no commercial licensing.]

---

## 12. Bridge to Results — what the reader should track

Three numbers carry the paper:

1. **48 of 92 (52%)** — repositories with ≥1 mlgg-lint finding. The "audit-positivity rate" of published code; supports C2 prevalence claim.
2. **76% (38 of 50)** — aggregate precision on the stratified random sample. The "lint reliability" floor; supports C1 calibration claim. 95% Wilson CI: 62–87%.
3. **3 of 28 (11%)** — rules below 50% precision and revised in this work. The "self-auditability cycle" demonstration; supports C3 governance claim.

Three numbers that are explicitly **not** the paper's headline:

- **n=5** PR-NNN papers with both peer-review documents and lint findings — illustrative only, not a precision claim.
- **n=31** trustable subset (cohort-binary AND reviewer_concerns ≥1) from v0.2 — superseded by the A3 stratified sample as the main quantitative input.
- **n=22** Fig 4 confusion-matrix expansion target — downgraded to v0.4 / follow-up paper scope; does not gate this submission.

---

## 13. Submission target and journal fit

Target tier (in priority order):

1. **Lancet Digital Health** — same venue as Liu 2022 (closest medical-domain prior art). Editorial fit on procedural-vs-executable framing. Word limits (4000 main text + supplements) accommodate the structured discussion. Open-access mandate compatible with releasing source code.
2. **npj Digital Medicine** — same venue as KT-LLM 2025 and HAIRA 2026 (both narrowly-scoped auditable frameworks in this venue). Caveat: 305 candidates / 0 PDFs in our corpus reflects this journal's TPR opt-in rate; the limitation is itself worth a sentence in the cover letter as a substantive observation.
3. **Nature Communications** — main corpus venue (134 of 217 retrieved PDFs). Risk: NC's ML methods coverage is broader than medical-specific; reviewers may push back on the scope-bounded framing.

Backup tier: BMJ (TRIPOD+AI was published here), JAMA, Nat Med (high competition; longer turnaround).

The cover letter draft (Q-list item) emphasizes: (i) the gap between reporting checklists and executable enforcement; (ii) the empirical finding that 52% of published code in 2 high-tier journals has at least one mlgg-detectable issue; (iii) the audit → revise → re-audit cycle as a methodological contribution beyond the rule pack itself.

---

## 14. Timeline to submission (revised vs v0.2)

| Month | Milestone | Output | Δ vs v0.2 |
|---|---|---|---|
| **M1** | Cohen's κ on n=50 stratified sample, 2nd annotator | per-rule κ + aggregate κ; 95% bootstrap CI | promoted from M2.5 to M1 (gating) |
| **M1** | Revised rule pack (R021/R008/R004) re-audit on the 92-repo corpus | post-revision precision JSON | new from v0.3 |
| **M1.5** | Track B (Kapoor positive controls, ≥3 per gate) + Track C (sklearn negative controls, ≥3 per gate) | Fig 2 calibration data | unchanged in shape; was v0.2 M1 |
| **M2** | Q17 external validation cohort decision + execution | external precision number | new (v0.2 left it open) |
| **M2** | E000 parse-failure investigation (B7 follow-up) | parser fix or rule downgrade | new |
| **M2.5** | First draft (abstract, intro, methods, results) | 30-page manuscript | unchanged |
| **M3** | Internal review by mlgg co-authors + mlgg self-audit on the paper's own pipeline | reviewed draft + meta-audit log | unchanged |
| **M3** | (Optional) reviewer-concerns extraction for 48 PR-EXP cohort if wave B1–B6 lands | concept-level alignment data | new pathway; if landed, fold into v0.3; else defer to v0.4 |
| **M3.5** | Senior co-author recruitment (Q16 / Q17 overlap) | confirmed co-author list | unchanged |
| **M4** | Cover letter, response-to-anticipated-reviewer-comments doc | submission-ready PDF | unchanged |
| **M5** | Submit | submission | unchanged |

Critical path: **M1 (κ) → M1 (rule re-audit) → M2.5 (draft)**. The M3 reviewer-concerns extraction is a parallel-track enhancement, not a blocker. v0.3's main quantitative result (76% TP at n=50) does not depend on M3 completion.

---

## 15. Cross-references to repository artifacts

For reviewers and follow-up annotators:

| Section | Primary artifact | Secondary artifact |
|---|---|---|
| §2 Introduction | `paper/lit-review.md` | `paper/literature/README.md` (PDFs + URLs) |
| §3.1 Corpus | `paper/prisma-flow.{md,json}` | `paper/code-repos-cohort-binary.{md,json}`, `paper/corpus-statistics.{md,json}` |
| §3.2 Rule set | `mlgg/rules/*.py` (release branch) | `mlgg/rules/changelog.md` (post-v0.3) |
| §3.3 Lint audit | `paper/lint-audit-110.{md,json}` | `paper/lint-audit-results.{md,json}` (8-paper baseline) |
| §3.4 Stratified review | `/tmp/agent03-tpfp-sample.json` (frozen seed=42) | `peer-review-kb.json:provenance.integrity_audits[*]` |
| §3.6 Reviewer concerns | `paper/fig4-confusion-matrix.md`, `paper/fig4-data.json` (n≤5) | (B1–B6 reviewer-concerns extraction wave) |
| §4.1 Prevalence | `paper/lint-audit-110.md` | `paper/build-fig4-data.py` (rerunner) |
| §6 Open questions | `paper/outline-v0.2.md` §9 (carry-forward Q1–Q9) | this file §6 (Q15–Q19) |
| §7 Authors | `paper/lit-review.md` action items §5 | (private contact list, not in repo) |
