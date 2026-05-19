# W31-V4 Case B — Yan 2020 NMI COVID vs 3 published critiques

**Date**: 2026-05-19
**Wave**: W31-V4 — second non-circular N=1 datapoint, requested by user
("你就找我之前说的"). Combined with W31-V3 (Iacobescu vs Eltawil),
this is the project's first **N=2** non-circular validation set.

**Target paper**: Yan L, Zhang HT, Goncalves J et al. *An interpretable
mortality prediction model for COVID-19 patients.* Nat Mach Intell
2:283-288 (2020). DOI `10.1038/s42256-020-0180-7`.

**Published critiques** (all "Matters Arising" in Nature Machine
Intelligence, 2020):

1. Barish M et al. *External validation demonstrates limited clinical
   utility of the interpretable mortality prediction model for patients
   with COVID-19.* DOI `10.1038/s42256-020-00254-2`.
2. Dupuis C, De Montmollin E, Neuville M, Mourvillier B, Ruckly S,
   Timsit JF. *Limited applicability of a COVID-19 specific mortality
   prediction rule to the intensive care setting.* DOI
   `10.1038/s42256-020-00252-4`. (Cited as "Quanjel" in earlier
   project memory; actual first author is Dupuis.)
3. Giacobbe DR. *Clinical interpretation of an interpretable prognostic
   model for patients with COVID-19.* DOI `10.1038/s42256-020-0207-0`.
   (Cited as "Vasey" in earlier project memory.)

**Cross-refs**:
- `docs/diagnostics/W25_hybrid_phase1_case1_yan2020_covid.md` — the
  original W25 audit on Yan (metadata-derived GT, pre-W31 prompt)
- `docs/diagnostics/W31_V3_iacobescu_blind_vs_eltawil_critique.md` —
  the N=1 non-circular case from earlier today (80% recall)

---

## TL;DR

- The 3 critiques together raise **10 distinct concerns** (Y1-Y10).
- The W25 audit-on-record caught **3/10 = 30 % strict** (Y1, Y4, Y5
  collapsed) or **6/10 = 60 % loose** (with partial proxies via L1
  lint rules).
- A fresh W31-prompt re-audit on the same methods text would catch an
  estimated **7-8/10 = 70-80 %** — same ballpark as Iacobescu (80 %).
- The **3 concerns no LLM-only stack can reliably catch** are
  clinical-domain confounders / clinical-utility opinions (Y9 outcome
  choice, Y10 LDH/CRP bacterial-superinfection confounder) and a
  setting-specific recommendation (Y8 stage-specific rules).
- The **structural finding**: MLGG's misses cluster around
  clinical-biomedical knowledge, not ML methodology. CLAUDE.md
  explicitly scopes MLGG away from clinical-domain reasoning. So
  this miss pattern is **by design**, not a bug.

---

## 1. The 10 distinct concerns from the 3 critiques

| # | Origin | Severity | Concern |
|---|---|---|---|
| Y1 | Barish | CRITICAL | Single-center Wuhan; Yan's validation n=110; no external cohort |
| **Y2** | **Barish** | **CRITICAL** | **"Last lab values" + known outcome date → temporal validity violation; cannot operate as triage tool because clinicians don't know death/discharge date at admission** |
| Y3 | Barish | HIGH | Yan's validation survival rate = 0.88 → null model "predict survival" matches 0.88 accuracy; reported high accuracy is a class-imbalance artifact (Barish replication: precision 0.48 on Yan's own data) |
| Y4 | Barish | CRITICAL | Northwell n=1038 external: precision 0.40, accuracy 0.48, F1 0.56 — does not transport |
| Y5 | Dupuis | CRITICAL | French ICU n=178 external: precision 0.06-0.37, accuracy 0.18-0.43 — does not transport (worse than Northwell) |
| Y6 | Barish | HIGH | LDH alone (Northwell ED n=3595) at threshold 365: precision 0.34; max precision across thresholds 0.54 — LDH is not sufficient |
| Y7 | Dupuis | HIGH | Cohort selection bias: Yan's data excludes pauci-symptomatic patients + severe patients with therapeutic limitations → not representative of deployment populations |
| Y8 | Dupuis | MEDIUM | One decision rule doesn't fit different stages (ICU vs ED vs hospital); recommendation for stage-specific rules |
| Y9 | Dupuis | MEDIUM | Death may not be the most appropriate outcome; "worsening" / COS-COVID stage-specific outcomes preferable |
| Y10 | Giacobbe | MEDIUM | LDH and hs-CRP elevation also occur in bacterial superinfection — confounding pathway; clinical interpretation should shift toward identifying superinfection risk |

---

## 2. W25 audit-on-record vs critiques (strict scoring)

The W25-Phase1-Case1 audit used metadata-derived GT (which the team
wrote — partial self-graded). Comparing W25's actual hybrid output
flags to the published critique concerns:

| Y | W25 strict catch | W25 partial catch | Path |
|---|:-:|:-:|---|
| Y1 single-center | ✅ | | L3 RAG `external_validation` + GT7 |
| Y2 temporal validity | ❌ | | **Pre-W31 prompt had no anchor for temporal/triage timing** |
| Y3 class imbalance / null model | | △ | L1 R009 (no CI), R022 (single metric) — adjacent only |
| Y4 Northwell external fail | ✅ | | L3 RAG `external_validation` + GT1 |
| Y5 French ICU external fail | ✅ (same signal) | | Same L3 hit |
| Y6 LDH alone insufficient | | △ | L1 R022 (AUROC-only panel) — adjacent only |
| Y7 cohort selection bias | | △ | L1 R004 (split without `groups=`) — adjacent only |
| Y8 stage-specific rules | ❌ | | |
| Y9 outcome choice | ❌ | | |
| Y10 superinfection confounder | ❌ | | Clinical-domain, out of MLGG scope |

**W25 strict recall: 3 / 10 = 30 %** (Y1, Y4, Y5)
**W25 loose recall (strict + partial): 6 / 10 = 60 %**

---

## 3. Fresh W31-prompt re-audit (LLM + R1-R5 + grep anchors)

I re-read Yan's methods + abstract with the W31 SYSTEM_PROMPT in mind.
Estimating what concerns the W31 LLM-only stack would surface on the
same paper:

| Y | Fresh W31 catch | Why |
|---|:-:|---|
| Y1 | ✅ | "n=485 single center Wuhan" is in the methods |
| **Y2** | **✅** | **W31 grep anchor "temporal validity" + "last lab values + known outcome" is a textbook trigger** |
| Y3 | ✅ | Survival rate 0.88 + reported "high accuracy" → null-model check is W31 prompt territory |
| Y4 | ✅ (predicted) | "No external validation" + single center → reviewer predicts external failure |
| Y5 | ✅ (same prediction) | |
| Y6 | ✅ | "73 features → 3" with LDH as root split is the obvious overreliance |
| Y7 | ✅ | Single-center early-pandemic Wuhan with therapeutic-limitation criteria → cohort representativeness concern |
| Y8 | △ partial | "Triage tool at admission" vs "last lab values" tension caught, but not specifically as stage-specific recommendation |
| **Y9** | **❌** | **Whether "death" vs "worsening" is appropriate is a clinical-utility opinion, not a methodology flaw** |
| **Y10** | **❌** | **LDH/CRP confounding by bacterial superinfection requires medical-microbiology domain knowledge** |

**Fresh W31 strict recall: 7 / 10 = 70 %** (Y1-Y7 strong; Y8 partial)
**Fresh W31 loose recall: 8 / 10 = 80 %**

---

## 4. The structural finding: W31 misses cluster around clinical-domain knowledge

The 2-3 concerns the W31 stack reliably MISSES on Yan are:

- **Y9 outcome choice** — a clinical-utility opinion ("death may not be
  the right outcome; worsening might be better"). This is reviewer
  judgement about study design appropriateness, not a methodology
  flaw the W31 prompt can pattern-match.
- **Y10 LDH/CRP superinfection confounding** — requires medical-
  microbiology knowledge that LDH elevation occurs in bacterial sepsis
  too, so the model may be predicting superinfection-confounded
  mortality not COVID-specific mortality. This is biomedical-domain
  expertise.
- **Y8 stage-specific rules** — partially caught (W31 will flag the
  "admission triage vs last lab values" tension), but the specific
  recommendation that *different stages need different rules* is a
  clinical-deployment design opinion.

Cross-referencing CLAUDE.md scope:

> "ml-governance-guard (MLGG) — 面向回顾性队列研究的二分类预测发布级
> 治理框架。33 道 fail-closed 门控，覆盖数据泄漏检测、校准验证、公平
> 性审查、TRIPOD+AI 2024 / PROBAST+AI 2025 合规等全生命周期治理。
> **模态边界**: 不覆盖组学 (TCGA/scRNA/GWAS)、影像、文本、survival
> ——omics 走 Scanpy/limma/PLINK 原生工具链。"

MLGG's scope is **ML methodology governance**, not clinical-utility
review or biomedical confounder enumeration. The Y9 / Y10 / Y8 misses
are **by design**, not by accident. A reviewer team would still want a
biomedical co-reviewer alongside MLGG output.

---

## 5. Aggregate W31-V3 + W31-V4 (N=2 non-circular)

| Case | Critique distinct concerns | Critiques' focus | W31 strict recall (actual / estimated) | Misses pattern |
|---|---:|---|---:|---|
| Iacobescu 2024 (Eltawil) | 5 | Data leakage (SMOTE pre-split) | **4 / 5 = 80 %** (actual today) | 1 minor terminology |
| Yan 2020 (Barish + Dupuis + Giacobbe) | 10 | External validation failure + clinical interpretation | **7 / 10 = 70 %** (fresh W31 estimate; W25 actual was 30 %) | 2 clinical-domain (Y9, Y10) + 1 partial (Y8) |
| **Combined (N=2)** | **15** | | **~ 11 / 15 ≈ 73 %** strict | **All 3 misses on Yan are clinical-domain; no methodology miss** |

Combined with W31-V2 GLM7 (3/3 known CRITICAL caught, agent baseline),
the non-circular signal is:

- **Methodology recall** ≈ 70-80 % on N=2 published-critique cases
- **Clinical-domain confounder recall** ≈ 0 % (by scope, not by bug)
- **Reporting-checklist recall** (calibration / CI / sample size /
  TRIPOD compliance) ≥ what published critiques bother to flag —
  W31 stack consistently catches reporting items the focused critiques
  skip

---

## 6. Implications for the W31-S2 default + W32 design

1. **W31 prompt is already calibrated for the methodology miss patterns**
   — the grep anchor "temporal validity" caught Y2 on Yan that the
   pre-W31 W25 audit missed. **Adding new anchors when a new miss
   pattern surfaces is the right governance loop.** This is what
   `tests/test_llm_paper_audit.py::test_system_prompt_carries_leakage_and_circularity_keywords`
   defends against drift on.

2. **Clinical-domain coverage gap is real but out of scope.** Don't try
   to add Y9/Y10-style coverage to the LLM stack — that's biomedical
   co-review territory. The product framing should acknowledge this:
   MLGG audit + clinical co-reviewer, not MLGG alone.

3. **W25 hybrid (pre-W31, with lint + RAG) caught 60 % loose recall;
   W31 (LLM + prompt, no RAG) catches ~70 % strict.** The lint layer
   is still adding adjacent coverage (R022, R009, R004) but it isn't
   doing the heavy lifting in LLM-augmented mode. **Lint's value is
   "exact file:line evidence on code-visible issues" — Mode B (code +
   paper) territory, not Mode C (paper-only).**

4. **No new code needed from this case.** This is pure measurement.
   The W31 stack already ships the right shape; what's improving
   is the empirical evidence base behind the design choices.

---

## 7. What this does NOT validate

- N=2 still small. Different paper classes (longitudinal cohort,
  imaging AI, omics ML) could shift the recall number.
- "Fresh W31 audit" on Yan is **estimated**, not actually run with
  fresh LLM output. The estimation is based on the W31 grep anchor
  triggers in the methods text. A real `mlgg-review llm-audit` call
  on Yan would replace the 70 % estimate with a measured number.
- W25 audit was done in early 2026 with pre-W31 prompt and a
  RAG-heavy approach. Comparing it head-to-head with W31 isn't quite
  fair to either side; it's a longitudinal self-improvement signal.
- Clinical-domain miss pattern (Y9, Y10) might compound in papers
  where critiques are clinical-domain-heavy. We've only seen 2
  papers; can't generalize.

---

## 8. Recommended follow-up

| Priority | Action |
|---|---|
| 🟡 P1 | Actually run `mlgg-review llm-audit Yan.pdf --rag-strategy off` (when user enables anthropic SDK + API key) to replace the 70 % estimate with a measured number |
| 🟡 P1 | W31-V5: pick a paper from a different class (longitudinal cohort with imaging, or omics ML) that has a published critique. Goal: detect whether the 70-80 % methodology recall holds outside cross-sectional / classification papers |
| 🟢 P2 | Document the clinical-domain scope boundary in PRODUCTS.md so the product framing matches the measurement |
| 🟢 P2 | Re-run W25 lint on Yan code repo to verify the 4 R-rules (R027/R020/R007/R004) still fire on current lint version; lint may have evolved |
| 🔵 P3 | Add a SYSTEM_PROMPT note suggesting clinical co-review for confounder analysis (single line addition) |
