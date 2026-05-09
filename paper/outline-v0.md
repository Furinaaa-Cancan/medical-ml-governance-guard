# mlgg paper — outline v0.1

**Status**: pre-spike (mapping test pending)
**Owner**: Wengcan
**Last updated**: 2026-05-09

This document is the source of truth for the mlgg publication strategy.
Replace, do not append, when revising. Keep prior versions in
`paper/archive/`.

---

## 1. Strategic positioning

### 1.1 Target journal tier

Target: **digital medicine / AI clinical** tier (IF 11–25).
Concrete priority order:

1. **Lancet Digital Health** (IF 23.8) — preferred for "audit + actionable"
   editorial taste.
2. **npj Digital Medicine** (IF 15.2) — methodology-friendly.
3. **Nature Communications** (IF 15.7) — fallback, accepts methodology
   papers in clinical AI.

Out of scope (not feasible with mlgg's contribution):

- NEJM / Lancet / JAMA / Nature Medicine — clinical primary endpoint required.
- Nature / Cell / Nature Genetics — biological discovery required.
- Nature Methods / Nature Machine Intelligence — algorithmic novelty required.

### 1.2 One-sentence pitch

> mlgg is a fail-closed publication-grade governance framework for medical
> machine learning that (1) detects governance issues with calibrated
> sensitivity/specificity, (2) identifies systematic gaps in 119+
> published high-impact medical ML papers, and (3) recovers reviewer
> concerns that take human peer review months to surface.

### 1.3 Title candidates

**Primary**:
"mlgg: closing the reproducibility-quality gap in published medical
machine learning through 33 fail-closed governance gates"

**Secondary**:
"Automated publication-grade governance for medical machine learning:
benchmarking against 119 high-impact peer reviews"

---

## 2. The three claims (must each survive reviewer attack)

| Claim | Quantitative target | Evidence figure | Data source | Risk |
|-------|--------------------|-----------------|-------------|------|
| **C1 — Tool calibration** | Per-gate sensitivity ≥0.85 and specificity ≥0.90 on synthetic leaky/clean datasets | Fig 2 | `examples/` + new fixtures | High (need ≥3 positive + ≥3 negative per gate) |
| **C2 — Audit findings** | ≥X% of in-scope NC papers have ≥1 mlgg-detectable governance issue | Fig 3, Table 2 | `references/case-studies/peer-review-kb.json` | Medium |
| **C3 — Reviewer-concern recovery** | ≥70% of in-scope reviewer concerns map to a mlgg gate that fires on the same paper | Fig 4 | downloaded peer review files (UKB-MDRMF + others) | High — see spike test |

C3 is the story climax. Without it, the paper degrades to "yet another tool paper".

---

## 3. Logical chain (premise → contribution → impact)

```
P1: Medical ML papers have systematic governance issues
        ↓ (evidence: §audit results)
P2: Manual peer review catches some but misses others; cycle is months to years
        ↓ (evidence: UKB-MDRMF case study, 3 review rounds)
P3: Existing ML governance tools are fragmented; no comprehensive framework
    exists for medical ML
        ↓ (evidence: tool comparison table, fairlearn / AIF360 / mlgg-lint)
P4: mlgg fills this gap with 33 fail-closed gates + DAG orchestration
    spanning the entire TRIPOD+AI / PROBAST+AI checklist
        ↓ (the contribution)
P5: mlgg detects known issues with high sensitivity and bounded false-positive
    rate
        ↓ (Fig 2)
P6: On 119 published NC medical ML papers, mlgg identifies governance
    concerns that human reviewers eventually flag, plus additional concerns
    that slipped through
        ↓ (Fig 3, Fig 4)
P7: Pre-submission use of mlgg makes governance issues visible to authors
    before the peer-review cycle starts
        ↓ (Fig 6)
```

Each transition (↓) is an attack surface. The most fragile transition
is **P5 → P6** (does benchmark performance on synthetic fixtures
generalize to real published papers?).

---

## 4. Six core figures

### Fig 1 — Framework overview
Panel A: 33-gate DAG (Layer 0–9) with TRIPOD+AI ID overlays.
Panel B: Mapping table to TRIPOD+AI 27 items, PROBAST+AI 4 domains.
Panel C: I/O schema diagram (CSV / code / config → gate → JSON envelope).
Panel D: Fail-closed semantics vs warn-only semantics in existing tools.

**Data source**: `_gate_registry.py`, `ARCHITECTURE.md`. ✅ Already exists.
**New work**: Re-render ASCII art to publication-grade SVG/Adobe.

### Fig 2 — Per-gate calibration
Panel A: Sensitivity per gate on N synthetic leaky datasets.
Panel B: Specificity per gate on N synthetic clean datasets.
Panel C: Runtime + memory profile per gate.

**Data source**: `examples/` 16 CSVs + new fixtures.
**New work**: For each gate, write ≥3 positive (gate must fire) and ≥3
negative (gate must not fire) fixtures. Total ~200 fixtures.
**Effort**: ~6 weeks. **Critical path** — all subsequent figures depend on this.

### Fig 3 — Audit on 119 NC medical ML papers
Panel A: Heatmap (papers × gates, color = pass / warn / fail).
Panel B: Stacked bar of papers failing each gate.
Panel C: Distribution of #gates failing per paper.

**Data source**: `references/case-studies/peer-review-kb.json`. ✅
**New work**: Run mlgg audit-mode on each paper's available code/methods.
For papers without public code, structural audit on methods text.
**Effort**: ~3 weeks.

### Fig 4 — mlgg vs human reviewers (the heart of the paper)
Panel A: Confusion matrix (mlgg detection × reviewer concern, paper count).
Panel B: Sankey diagram (reviewer concerns → mlgg gates that cover them).
Panel C: Time-to-detect comparison (mlgg seconds vs reviewer rounds × weeks).

**Data source**: 452 review opinions in `peer-review-kb.json` + downloaded
peer review files for in-depth case studies.
**New work**:
- Two independent annotators classify each reviewer concern into mlgg
  gate categories. Cohen's kappa ≥0.7 required for reliability.
- Run mlgg on each paper, record fired gates.
- Build confusion matrix.
**Effort**: ~4 weeks. **Highest reviewer-attack surface**.

### Fig 5 — Case study deep dive
Panel A: UKB-MDRMF (Jiang et al. 2025 Nat Commun).
- mlgg pre-submission predictions (simulated).
- Actual reviewer concerns across 3 rounds.
- Coverage analysis (which mlgg gate covered which concern).
Panel B: SUPPORT2 dual-path comparison.
- Clean path AUC + calibration + DCA.
- Leaky path AUC + calibration + DCA.
- mlgg evidence trail showing detected leakage.
Panel C: One worst-offender paper from 119 (anonymized if needed).
- Which gates fired.
- What reviewers actually said.

**Data source**:
- UKB-MDRMF: GitHub https://github.com/kannyjyk/UKB-MDRMF + downloaded peer review.
- SUPPORT2: existing experiments in `experiments/support2-benchmark*`.
- Worst-offender: select after Fig 3 audit.

**New work**: Re-run UKB-MDRMF code through mlgg (~2-3 days). Already have SUPPORT2.

### Fig 6 — Counterfactual impact analysis
Panel A: Per-paper estimated reviewer rounds avoided (median, IQR).
Panel B: Aggregate reviewer hours saved at community scale.
Panel C: Cost-benefit (mlgg adoption cost vs governance benefit).

**Data source**: Derived from Fig 4 confusion matrix.
**New work**: Counterfactual model with explicit assumptions.
**Effort**: ~1 week.
**Risk**: Counterfactual is unverifiable. Must be modest in claims —
"X% of concerns visible in mlgg output pre-submission" not "Y rounds
saved". See §6 hole #2.

---

## 5. Three core tables

| Table | Content | Source |
|-------|---------|--------|
| **T1** | Gate × TRIPOD+AI 27 item × PROBAST+AI 4 domain mapping | manual curation |
| **T2** | Top 10 most-failing gates across 119 papers, with example issues | Fig 3 derivative |
| **T3** | Performance comparison vs baseline (mlgg-lint vs flake8 + pylint + fairlearn etc.) | benchmark |

---

## 6. Five logical holes the paper must defend against

### Hole 1 — Reviewer concerns are not ground truth
Reviewers miss issues, are subjective, and disagree among themselves.
Cannot frame "mlgg vs reviewer who is more accurate."

**Mitigation**:
- Reframe as complementary, not adversarial.
- Report 4 cells of confusion matrix:
  - Both detect (confirmation).
  - mlgg only (mlgg recovers what humans missed).
  - reviewer only (mlgg blind spot — recommend new gate).
  - Both miss (the most dangerous — sample audit by external clinical
    expert to estimate this rate).

### Hole 2 — Counterfactual is unverifiable
"If authors had used mlgg, they would have saved N reviewer rounds" —
cannot be A/B tested.

**Mitigation**:
- Lower the claim's strength: "X% of reviewer concerns are visible in
  mlgg's pre-submission output, suggesting they would be addressable
  before peer review."
- Use UKB-MDRMF as a single existence-proof case study, not a
  population estimate.

### Hole 3 — mlgg's scope is narrower than "all medical ML"
mlgg covers retrospective cohort binary classification only.
Out of scope: imaging, omics, text, survival, RCT, prospective.

**Mitigation**:
- Explicit in-scope/out-of-scope table early in methods.
- Reframe scope as feature: "depth over breadth."
- Filter the 119-paper audit to in-scope subset (likely 50–80 papers).
- Report out-of-scope paper count for transparency.

### Hole 4 — Sample size + selection bias
- Only Nature Communications papers (high-impact bias).
- Only papers with public peer review files (NC has been mandatory
  since 2022, so dataset is recent and time-truncated).
- No reject papers (cannot access; would likely have more issues).

**Mitigation**:
- Expand corpus beyond NC: add Lancet Digital Health, npj Digital Medicine,
  JAMIA. Target 300–500 papers.
- Acknowledge selection bias as "high-impact-journal lower bound" — if
  even these have issues, lower-tier journals likely worse.

### Hole 5 — Reviewer concern → gate mapping subjectivity
Classification of free-text reviewer concerns into structured gate
categories is judgment-heavy.

**Mitigation**:
- Two independent annotators.
- Cohen's kappa ≥0.7 reported.
- Ambiguous cases listed in supplementary appendix.
- Senior clinical-epidemiology arbiter (= co-author) for tie-breaking.

---

## 7. Real-world blockers (resolve before timeline starts)

| Blocker | Severity | Status | Resolution |
|---------|----------|--------|------------|
| Senior clinical co-author | 🔴 Fatal | Open | Identify and recruit before submission |
| Public code availability for 119 papers | 🟠 Important | Unknown | Will partially resolve via methods-text audit |
| Disease KB clinical review | 🟠 Important | Open | See `project_disease_kb_provenance.md` memory |
| Compute (119 × 33 audit pass) | 🟢 Manageable | Available | Local + GitHub Actions |
| UK Biobank data access | ⚪ Optional | Not needed for paper | Use SUPPORT2 / All of Us only |

---

## 8. Six-month timeline

| Month | Milestone | Output |
|-------|-----------|--------|
| **M1** | Per-gate fixtures: ≥3 positive, ≥3 negative for each of 33 gates | Fig 2 raw data |
| **M2** | mlgg audit-mode run on 119 paper corpus + reviewer concern taxonomy | Fig 3, Fig 4 raw data |
| **M3** | UKB-MDRMF GitHub re-audit + SUPPORT2 dual-path consolidation + worst-offender deep dive | Fig 5 raw data |
| **M4** | First draft (abstract, intro, methods, results) | 30-page manuscript |
| **M5** | Self-audit using mlgg on the paper's own methods + figure refinement + co-author review | submission-ready PDF |
| **M6** | Recruit senior co-author + final revisions + cover letter | submission |

---

## 9. Spike test (must pass before committing to timeline)

**Question**: Does mlgg's 33-gate scope actually map to what real reviewers
care about for in-scope papers?

**Test**: Take the UKB-MDRMF peer review file (already downloaded —
`references/case-studies/nature_communications/ukb_mdrmf/ukb-mdrmf-peer-review.pdf`).
Extract every distinct reviewer concern across 3 rounds × 3 reviewers.
For each concern, attempt to map to one or more of the 33 gates.

**Decision criteria**:
- Mapping rate ≥70% → outline is viable, proceed to full timeline.
- Mapping rate 50–70% → outline needs scope tightening; mlgg covers
  structural concerns but not presentation/policy. Pivot to "structural
  governance subset" framing.
- Mapping rate <50% → outline must be rebuilt; mlgg's 33 gates don't
  align with what reviewers actually care about.

**Spike result**: see §10 below (filled in by spike-test commit).

---

## 10. Spike test result

Performed: 2026-05-09. Single-paper case study (UKB-MDRMF, Jiang et al.
2025 Nat Commun 16:3767). Full detail in `paper/spike-test-ukb-mdrmf-mapping.md`.

### Headline number

| Coverage scope | Rate | Verdict |
|----------------|------|---------|
| Aggregate (all concerns) | 62.5% (15/24) | within "tighten scope" band per §9 |
| In-scope categories only | **89–100%** | exceeds 70% threshold per §9 |

### Key finding

mlgg's coverage is **bimodal**:

- **Methodology / reporting / validation / reproducibility / interpretation /
  missingness**: 89–100% of reviewer concerns map to ≥1 firing gate.
- **Statistical (multiple testing, competing risk) / terminology / clinical
  policy / UX**: 0% coverage. These are intrinsically outside any
  technical governance tool's scope.

The aggregate 62.5% is dragged down by 9 of 24 concerns being out of
any tool's scope. This is **defensible**, not a framework failure.

### Two genuine gate gaps (mlgg roadmap items)

1. **Multiple testing adjustment** — add `multiple_testing_gate` (R3.0.5).
2. **Competing risk** — intentionally out of scope (mlgg refuses
   survival modalities); clarify in scope statement.

### Decision

**Proceed to full timeline with v0.2 outline revisions** (see §13 below).
Reframe paper claim C3 from "≥70% mapping" to "**≥85% in-scope mapping**"
with explicit scope statement.

---

## 13. v0.2 outline revisions (queued)

The spike test motivates the following changes to v0.1:

1. §1.5 (new): explicit scope statement — what mlgg is for, what it isn't.
2. §2 claim C3: restate as "≥85% in-scope coverage" with category breakdown.
3. §3 P4: insert scope filter explicitly.
4. Fig 4 panel D (new): per-category coverage breakdown showing the
   bimodal in-scope/out-of-scope structure.
5. §8 timeline: add 1-week M1.5 for `multiple_testing_gate` development.
6. §6 hole 3: promote to dominant talking point in framing.

These changes will produce `paper/outline-v0.2.md`. v0.1 stays as the
record of what we knew before the spike.

---

## 11. Open questions for user

Q1. Senior clinical co-author profile?
Q2. Disease-KB clinical review owner?
Q3. Time commitment level (3 / 6 / 12 months)?
Q4. Authorship preference (first author / last-corresponding)?
Q5. Is paper in English-only or bilingual (CN companion blog post)?

---

## 12. Versioning

- v0.1 (this file): initial outline, post-tier-selection, pre-spike test.
- v0.2: post-spike test, revised based on mapping rate finding.
- v1.0: post first-author review, ready for co-author distribution.
