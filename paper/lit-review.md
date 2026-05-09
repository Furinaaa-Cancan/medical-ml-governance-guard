# Literature review: medical ML governance landscape

**Date**: 2026-05-09
**Method**: Targeted WebSearch on 10 angles + WebFetch on closest competitors. Single-pass, single-annotator. To be re-validated by senior co-author before submission.
**Purpose**: Position mlgg's contribution against existing tools and frameworks, identify true competitors, and surface authorship/citation risks.

---

## Headline finding

**No existing tool combines all four properties that define mlgg**:

1. **Executable validators** (run on actual code/data/config/metrics, not just manuscript text or self-reported checklists).
2. **Fail-closed semantics** (downstream stages refuse to run when an upstream gate fails).
3. **Comprehensive TRIPOD+AI (27 items) / PROBAST+AI (4 domains) coverage** through executable mapping rather than manual review.
4. **Scope-bounded to retrospective cohort binary classification** with explicit refusal of out-of-scope modalities (omics, imaging, text, survival).

The closest neighbours each match 1–2 of these properties at most. The unfilled corner of the matrix is mlgg's contribution.

---

## Competitive matrix

| Tool / framework | Executable | Fail-closed | TRIPOD+AI map | Medical scope | Primary mode |
|------------------|:----------:|:-----------:|:-------------:|:-------------:|--------------|
| **mlgg** (this work) | ✅ | ✅ | ✅ | ✅ | 33 gates, DAG, JSON evidence |
| TRIPOD+AI checklist [1] | ❌ | ❌ | n/a | ✅ | Manual reporting checklist |
| PROBAST+AI (in dev) [2] | ❌ | ❌ | partial | ✅ | Manual bias assessment |
| TRIPOD-AI Checklist Agent (SciSpace) [3] | partial | ❌ | ✅ | ✅ | Manuscript-text auditor |
| Kapoor et al. 2023 model info sheets [4] | ❌ | ❌ | ❌ | ❌ | Voluntary self-report |
| Medical algorithmic audit (Liu 2022) [5] | ❌ | ❌ | ❌ | ✅ | Procedural framework for deployed systems |
| ReproAudit [6] | partial | ❌ | ❌ | ❌ | General-purpose code/paper alignment |
| Algorithm Auditing & QC editorial (Oala 2021) [7] | ❌ | ❌ | ❌ | ✅ | Editorial calling for audits |
| CLAIM 2024 [8] | ❌ | ❌ | ❌ | imaging only | Imaging reporting checklist |
| DECIDE-AI [9] | ❌ | ❌ | ❌ | ✅ | Early-stage clinical eval reporting |
| MI-CLAIM [10] | ❌ | ❌ | ❌ | ✅ | Manual reporting (minimum info) |
| CONSORT-AI / SPIRIT-AI [11] | ❌ | ❌ | ❌ | ✅ | RCT reporting (out of mlgg's scope) |
| HAIRA (Hassan 2026 npjDM) [12] | ❌ | ❌ | ❌ | ✅ | Org-level governance maturity (5 levels) |
| Microsoft RepDL [13] | ✅ | ❌ | ❌ | ❌ | Low-level PyTorch determinism |
| Repro (Docker-based) [14] | ✅ | ❌ | ❌ | ❌ | Container-level run reproduction |
| Varoquaux & Cheplygina 2022 [15] | ❌ | ❌ | ❌ | imaging | Review article on failure modes |
| KT-LLM (npjDM 2025) [16] | partial | ❌ | partial | kidney transplant only | Domain-specific auditable LLM stack |
| Algorithm-audit FDA postmarket framework [17] | ❌ | ❌ | ❌ | ✅ | Regulatory postmarket surveillance |

`✅ = full`, `partial = covers some aspect`, `❌ = does not cover`.

---

## Detailed competitor profiles

### 1. Kapoor & Narayanan 2023, *Patterns* — Closest **conceptual** prior art

> Sayash Kapoor, Arvind Narayanan. "Leakage and the reproducibility crisis in machine-learning-based science." *Patterns* 4(9): 100804.

- **8-type leakage taxonomy** spanning text-book errors to open research problems.
- Surveyed 17 fields, 329 papers (later updated to 41 papers across 30 fields, 648 affected papers).
- Found **all complex-ML-vs-LR claims in civil war prediction** failed to reproduce due to leakage.
- **Solution**: voluntary "model info sheets" (manual checklist).
- **No software tool**.

**Why mlgg is differentiated**: Kapoor's work documents the problem. mlgg implements the solution. Their model info sheet is a 1-time author self-report; mlgg gates run on every CI cycle and refuse to pass when leakage is detected.

**Citation risk**: mlgg must cite Kapoor as the foundational problem statement and explicitly position mlgg as "from problem documentation to executable enforcement."

---

### 2. Liu et al. 2022, *Lancet Digital Health* — Closest **medical-domain** prior art

> Xiaoxuan Liu, Ben Glocker, Melissa M McCradden, Marzyeh Ghassemi, Alastair K Denniston, Lauren Oakden-Rayner. "The medical algorithmic audit." *Lancet Digit Health* 4(5): e384–e397.

- **Procedural framework** (not software) for auditing medical AI.
- Components: scope of intended use, exploratory error analysis, subgroup testing, adversarial testing.
- **Joint responsibility of users and developers**.
- Focuses on **deployed systems**, not pre-publication validation.

**Why mlgg is differentiated**:
- Liu's framework is conceptual; mlgg is executable.
- Liu addresses post-deployment audit; mlgg addresses pre-publication governance.
- The two are **complementary, not competing** — mlgg's evidence JSON could be the input to a Liu-style post-deployment audit.

**Citation risk**: Senior author Denniston / Oakden-Rayner are exactly the **kind of senior co-author** mlgg needs to recruit. Their paper is in the target journal (Lancet Digital Health). **Action item**: investigate whether one of the seven authors might co-sign mlgg.

---

### 3. TRIPOD-AI Checklist Agent (SciSpace) — Closest **automation** prior art

> Commercial agent at https://scispace.com/agents/tripod-ai-checklist-a70kfdk5

- Parses AI prediction model **manuscripts** and aligns content with TRIPOD+AI items.
- Outputs Met / Partially Met / Missing / N/A status with section references.
- Highlights AI-specific elements (model type, validation, hyperparameters, fairness).

**Why mlgg is differentiated**:
- SciSpace agent runs on **manuscript text only**. Cannot detect leakage that the manuscript correctly reports as "we used train/test split" but the actual code violates.
- mlgg runs on **code + data + JSON evidence**. Catches the gap between "what authors wrote" and "what the code actually did."
- This is exactly the gap ReproAudit (#6) is built for, but neither SciSpace nor ReproAudit cover the full TRIPOD+AI / PROBAST+AI surface for medical ML.

**Action item**: run SciSpace agent on UKB-MDRMF manuscript as a baseline comparator for Fig 4.

---

### 4. ReproAudit (reproaudit.com) — General-purpose code/paper auditor

- Automated reproducibility audits with agentic code exploration.
- Paper-code alignment: detects gaps between manuscript claims and code reality.
- **General purpose**, not medical-specific.
- "Early access," not yet published as a paper.
- Open-source status unclear from website.

**Why mlgg is differentiated**:
- mlgg is medical-specific with hard-coded TRIPOD+AI / PROBAST+AI mapping.
- mlgg has 33 fail-closed gates covering specific medical ML failure modes (definition leakage, immortal time bias, calibration, DCA).
- ReproAudit appears to focus on dependency/environment/code structure, not statistical methodology.

**Risk**: ReproAudit is the most likely competitor to publish a similar tool paper in 2026. Need to monitor and submit before they do.

---

### 5. Reporting checklists (TRIPOD+AI, PROBAST+AI, CLAIM, DECIDE-AI, MI-CLAIM, CONSORT-AI, SPIRIT-AI, FUTURE-AI, STARD-AI, PRISMA-AI, TRIPOD-LLM)

Approximately 11+ active reporting guidelines, all manual checklists requiring author self-disclosure. The proliferation itself is well-documented in the recent Lancet Digital Health "Navigating the landscape of medical AI reporting guidelines" review [18].

**mlgg's relationship to these**: mlgg explicitly maps each gate to the relevant TRIPOD+AI item and PROBAST+AI domain. The mapping table (Table 1 of paper) becomes a key contribution: "for each of the 27 TRIPOD+AI items, here is the executable validator that checks compliance." This is the **executable interpretation of TRIPOD+AI**.

---

### 6. HAIRA — Healthcare AI Governance Readiness Assessment (Hassan 2026, npj Digital Medicine)

> Systematic review of 35 AI governance frameworks (2019–2024), 7 critical domains.
> 5-level maturity model: from ad-hoc to optimized.

- **Organizational level** governance, not technical.
- Targets institutional readiness, not individual studies.
- Complementary to mlgg, not competitor.

**Citation strategy**: cite as "organizational governance frameworks like HAIRA address institutional readiness; mlgg complements by addressing per-study technical governance."

---

### 7. KT-LLM (npj Digital Medicine 2025)

- "Evidence-grounded and sequence text framework for auditable kidney transplant modeling."
- Domain-specific (kidney transplant only).
- Uses LLM with verifiable orchestration to ensure decisions are grounded.

**Why mlgg is differentiated**: domain-general (within retrospective cohort binary classification scope), not LLM-based, not single-disease.

**Citation strategy**: KT-LLM shows the journal accepts narrowly-scoped auditable frameworks. mlgg's broader scope strengthens its case for the same venue.

---

## What this means for mlgg's positioning

### Positioning paragraph (draft for paper introduction)

> "Existing approaches to governance of medical machine learning fall into five categories: (i) reporting checklists requiring voluntary author self-disclosure [TRIPOD+AI [1], PROBAST+AI [2], CLAIM [8], DECIDE-AI [9], MI-CLAIM [10], CONSORT-AI / SPIRIT-AI [11]]; (ii) review articles documenting failure modes [Kapoor 2023 [4], Varoquaux 2022 [15]]; (iii) procedural audit frameworks for deployed systems [Liu 2022 [5]]; (iv) organizational governance maturity models [HAIRA [12]]; and (v) general-purpose reproducibility tools [ReproAudit [6], Microsoft RepDL [13], Repro [14]]. None combine **executable validators**, **fail-closed semantics**, and **comprehensive TRIPOD+AI / PROBAST+AI coverage** into a single automated framework targeted at retrospective cohort binary classification — the workhorse of clinical prediction modeling. mlgg fills this gap with 33 gates organized in a dependency-aware DAG, producing machine-readable evidence consumable by downstream agents."

### Defensible novelty claim

The combination of:
1. **Executable** (vs. checklist)
2. **Fail-closed** (vs. warn-only)
3. **Medical-specific** (vs. general-purpose)
4. **Per-study** (vs. organizational)
5. **Pre-publication** (vs. post-deployment)
6. **Agent-consumable JSON** (vs. human-only reports)
7. **Scope-bounded with explicit refusal** (vs. one-size-fits-all)

is unique. No single tool in the survey covers more than 3 of these 7 dimensions.

### Risks to monitor

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ReproAudit publishes general-purpose paper first | Medium | Submit mlgg within 6 months |
| PROBAST-AI lands and overlaps mlgg's bias-domain gates | Medium | Map mlgg gates to PROBAST-AI v1 within 1 week of release |
| SciSpace publishes their TRIPOD-AI agent as a peer-reviewed tool | Low-medium | Run SciSpace agent on our 119-paper corpus as a baseline; show mlgg detects what manuscript-only auditors miss |
| Liu et al. write a follow-up "executable medical algorithmic audit" paper | Low | Recruit one of the seven Liu 2022 authors as senior co-author |

---

## Action items (out of pure literature review)

1. **Run SciSpace TRIPOD-AI Agent on UKB-MDRMF manuscript** — generate baseline comparator data for Fig 4.
2. **Read Kapoor et al. 2023 full taxonomy of 8 leakage types**, map to mlgg's gates, identify any gap in mlgg coverage.
3. **Read Liu et al. 2022 medical algorithmic audit** in full, extract terminology to use in mlgg's introduction (frame as "extending Liu 2022 from procedural to executable").
4. **Check whether ReproAudit has any publication or preprint** as of submission date.
5. **Identify candidate senior co-authors**: Denniston, Oakden-Rayner, Glocker, Ghassemi, McCradden — all on Liu 2022. Approach via supervisor / network.

---

## References

[1] Collins GS, Moons KGM, Dhiman P, et al. TRIPOD+AI statement: updated guidance for reporting clinical prediction models that use regression or machine learning methods. BMJ 2024;385:e078378.

[2] Collins GS, Dhiman P, Andaur Navarro CL, et al. Protocol for development of a reporting guideline (TRIPOD-AI) and risk of bias tool (PROBAST-AI) for diagnostic and prognostic prediction model studies based on artificial intelligence. BMJ Open 2021;11:e048008.

[3] SciSpace TRIPOD-AI Checklist Agent. https://scispace.com/agents/tripod-ai-checklist-a70kfdk5

[4] Kapoor S, Narayanan A. Leakage and the reproducibility crisis in machine-learning-based science. Patterns 2023;4(9):100804.

[5] Liu X, Glocker B, McCradden MM, Ghassemi M, Denniston AK, Oakden-Rayner L. The medical algorithmic audit. Lancet Digit Health 2022;4(5):e384–e397.

[6] ReproAudit. https://reproaudit.com (early-access tool; no peer-reviewed publication as of search date).

[7] Oala L, Murchison AG, Balachandran P, et al. Machine learning for health: algorithm auditing & quality control. J Med Syst 2021;45(12):105.

[8] Tejani AS, Klontzas ME, Gatti AA, et al. Checklist for Artificial Intelligence in Medical Imaging (CLAIM): 2024 Update. Radiol Artif Intell 2024;6(4):e240300.

[9] Vasey B, Nagendran M, Campbell B, et al. Reporting guideline for the early-stage clinical evaluation of decision support systems driven by artificial intelligence: DECIDE-AI. Nat Med 2022;28:924–933.

[10] Norgeot B, Quer G, Beaulieu-Jones BK, et al. Minimum information about clinical artificial intelligence modeling: the MI-CLAIM checklist. Nat Med 2020;26:1320–1324.

[11] Liu X, Cruz Rivera S, Moher D, et al. Reporting guidelines for clinical trial reports for interventions involving artificial intelligence: the CONSORT-AI extension. Nat Med 2020;26:1364–1374.

[12] [Title and authors to be confirmed.] Advancing healthcare AI governance through a comprehensive maturity model based on systematic review. npj Digit Med 2026 (DOI s41746-026-02418-7).

[13] Microsoft RepDL. https://github.com/microsoft/RepDL (open-source PyTorch reproducibility library).

[14] Logan IV RL, Saphra N, Bhagavatula C, Sap M. Repro: An Open-Source Library for Improving the Reproducibility and Usability of Publicly Available Research Code. arXiv:2204.13848.

[15] Varoquaux G, Cheplygina V. Machine learning for medical imaging: methodological failures and recommendations for the future. npj Digit Med 2022;5:48.

[16] [Title and authors to be confirmed.] KT-LLM: an evidence-grounded and sequence text framework for auditable kidney transplant modeling. npj Digit Med 2025 (DOI s41746-025-02323-5).

[17] [Title and authors to be confirmed.] A general framework for governing marketed AI/ML medical devices. npj Digit Med 2025 (DOI s41746-025-01717-9).

[18] Reddy S, et al. Navigating the landscape of medical artificial intelligence reporting guidelines. Lancet Digit Health 2025 (DOI 10.1016/S2589-7500(25)00107-4).

---

## Limitations of this review

1. **Single-pass single-annotator**. Final paper requires PRISMA-style systematic review with two annotators.
2. **English-only sources**. Chinese-language journal coverage skipped.
3. **No grey literature**. Conference proceedings, GitHub repos, technical reports excluded.
4. **No FDA / EMA regulatory documents**. Should add for the "regulatory alignment" subsection.
5. **Several sources couldn't be fetched** (CALIFRAME PMC, Liu 2022 full text, npj governance framework) due to captcha/redirect. Need direct PDF access via institutional library before submission.
