# mlgg paper — outline v0.1

**Status**: post-spike, post-corpus-tightening, mid-expansion
**Owner**: Wengcan
**Last updated**: 2026-05-10
**Predecessor**: `paper/outline-v0.md` (pre-spike, pre-tightening). Kept as
historical record.

This document supersedes v0.0 as the source of truth for the mlgg
publication strategy. Substantive changes vs v0.0 are listed in §0
(diff summary) and threaded through §§ 2, 3, 4, 5, 6.

---

## 0. Diff summary vs v0.0

| Area | v0.0 | v0.1 |
|---|---|---|
| Corpus base | "119 NC papers" | 118 entries (PR-040 fabricated, quarantined); 119/119 with PDF on disk; 7 PR-RO entries pending validation |
| Cohort scope | implicit | 32 of 118 pass strict retrospective-cohort + binary + tabular filter; 21 with high-confidence verified PDF |
| Code availability | "unknown" blocker | 17 of 21 have a usable public code link; 12 successfully cloned, 8 with Python; PR-001 repo deleted post-publication |
| Validation strategy | "run mlgg in audit mode on 119 papers" | three-track: (a) lint audit on 8 cloned repos with 260 raw findings, FP-rate caveat; (b) Kapoor 12-paper positive controls; (c) sklearn negative controls |
| Fig 4 feasibility | "highest reviewer-attack surface" | feasible now: 260 lint findings × KB reviewer concerns → confusion matrix is constructable |
| Timeline | M1–M6 sequential | adjusted for in-flight corpus expansion (614 candidates), FP-rate audit, PR-RO backfill |
| Provenance | implicit | new §6: data-integrity audit trail (PR-040 quarantine, PR-RO pending, reconciliation script). The paper itself follows mlgg's own evidence-trail discipline |

---

## 1. Strategic positioning

Title, journal tier, pitch, and competitive matrix all unchanged from v0.0
§1. Three claims still hold; only the data behind them is tighter.

### 1.1 The three claims (must each survive reviewer attack)

| Claim | Quantitative target | Evidence | Data source | v0.1 status |
|-------|---------------------|----------|-------------|-------------|
| **C1 — Tool calibration** | Per-gate sensitivity ≥0.85 / specificity ≥0.90 | Fig 2 | sklearn negative controls + Kapoor positive controls + `examples/` | New: positive/negative control sources named |
| **C2 — Audit findings** | ≥X% of in-scope cohort papers have ≥1 mlgg-detectable issue | Fig 3, Table 2 | lint audit on 8 cloned repos (260 raw findings; 7/8 have ≥1 finding) | Promoted from "planned" to "raw data in hand, FP-rate audit pending" |
| **C3 — Reviewer-concern recovery** | ≥85% in-scope coverage (per spike test) | Fig 4 | KB reviewer concerns × per-paper lint findings | Promoted from "highest-risk" to "constructable" |

C3 remains the story climax. The spike-test 89–100% in-scope mapping
rate from v0.0 §10 is preserved; v0.1 only updates the operational
basis for computing it across the cohort.

---

## 2. Corpus

### 2.1 Base KB

| Subset | Count | Notes |
|---|---:|---|
| Total KB entries | 118 | Was 119 in v0.0; PR-040 removed after fabrication audit (commit 083c4b4 family) |
| Fully validated | 111 | Two-pass DOI + title + venue check |
| `pending_manual_validation` | 7 | PR-RO-01..07; flagged for backfill before submission |
| Quarantined (excluded) | 1 | PR-040; PDF moved to `references/case-studies/_quarantine/`; documented in §6 |

### 2.2 PDF coverage

| Status | Count |
|---|---:|
| Linked to PDF on disk | 119/119 |
| Verified high-confidence (DOI / paper-id / manual override) | 114 |
| High-multi (multi-PDF candidate set, lower confidence) | 5 |

Match performed by `scripts/diagnostics/reconcile_peer_review_pdfs.py`
using a four-strategy ladder: (0a) `PR-NNN_` filename prefix, (0b) manual
override table, (1) DOI-in-text, (2) Jaccard title overlap ≥0.5. Strategy
and confidence stored per-entry in `pdf_verification`.

PDFs in `references/case-studies/nature_communications/` are Nature
Communications transparent peer review files, which the publisher
distributes under **CC-BY 4.0**. Redistribution is permitted with
attribution; the paper will state this explicitly to support open release
of the auditing artifacts.

### 2.3 Strict cohort scope filter

mlgg covers retrospective cohort, binary classification, tabular EHR /
clinical features. Applying that filter to the 118-entry base:

| Filter step | Count | Drop |
|---|---:|---:|
| KB base | 118 | — |
| Retrospective cohort + binary classification + tabular | 32 | −86 (imaging, omics, text, survival, RCT, multi-class) |
| AND high-confidence verified PDF | 21 | −11 |

The 21-paper subset is the **headline cohort** for paper-grade claims.
The 32-paper superset is reported for transparency but only the 21 carry
verifiable peer-review PDFs.

### 2.4 Corpus expansion (in progress)

To address v0.0 §6 hole 4 (sample-size + selection bias), we are
expanding beyond Nature Communications to two sister transparent
peer-review journals:

| Source | Candidates discovered (OpenAlex, 2020–2026) |
|---|---:|
| Nature Communications (existing) | 163 |
| npj Digital Medicine | 305 |
| Communications Medicine | 146 |
| **Total new candidates** | **614** |

Peer-review PDF download is running in background. Empirically, ~60% of
candidates expose a peer-review file via the Springer ESM endpoint
(based on a 5-paper smoke test; 3/5 downloaded). Projected post-expansion
cohort: 500–800 entries with PDF, of which ~150–250 will pass the strict
cohort scope filter. Final paper numbers will reflect whichever yield
materializes; current §3–§5 numbers are framed against the 21-paper
verified subset as a conservative lower bound.

---

## 3. Validation strategy (three tracks)

Replaces v0.0's single "run mlgg audit-mode on 119 papers" plan with a
three-track design that separates calibration, audit, and prevalence.

### Track A — Lint audit on cloned cohort repos (audit findings, Fig 3)

| Step | Result |
|---|---|
| GitHub repos targeted (from 21-paper subset) | 13 |
| Successfully cloned | 12 |
| Repos with Python source files | 8 |
| Repos with ≥1 mlgg-lint finding | **7 of 8** |
| Total raw findings | **260** (190 warnings + 55 info + 15 errors) |
| Top-firing rule | **R009** (`no_confidence_intervals`, TRIPOD-AI E01) — fires in **7 of 7** papers with findings |
| Other high-firing rules | R022, R021, R013, R004, R008 |

Per-paper detail in `paper/lint-audit-results.md` and
`paper/lint-audit-results.json`. Audit script: commit 083c4b4.

**FP-rate caveat (must be in paper Methods)**: the 260 figure is *raw*
lint output. Lint rules are pattern-based and over-fire on non-issues
(e.g. R009 also flags helper functions that legitimately don't compute
CIs). Paper-grade prevalence claims require a **two-annotator
true-positive-rate audit** before publication. Plan: stratified random
sample of 100 findings (proportional to rule), independent label by two
annotators, Cohen's κ ≥0.7, report TP-rate per rule with 95% CI.
Anything less is descriptive, not inferential.

### Track B — Positive controls (calibration, Fig 2)

Source: Kapoor & Narayanan 2023 *Patterns* 8-type leakage taxonomy. The
companion repository documents 41 papers across 30 fields with confirmed
leakage. Of those, ~12 fall within mlgg's retrospective-cohort scope.
Plan: re-implement the leakage manipulation in each as a fixture under
`examples/`, run mlgg, expect target gate to fire. Per-gate target ≥3
positive fixtures, supplemented by synthetic fixtures where Kapoor's
papers don't cover a gate.

### Track C — Negative controls (specificity, Fig 2)

Source: scikit-learn `examples/` directory and `model_selection`
notebooks. These are widely-vetted, leakage-free pedagogical pipelines.
Run mlgg, expect zero gates to fire. Per-gate target ≥3 negative
fixtures.

### Track summary

| Track | Purpose | Source | Status |
|---|---|---|---|
| A — Lint audit | C2 (audit findings) | 8 cloned cohort repos | Raw data in hand; FP-rate audit pending |
| B — Positive controls | C1 sensitivity | Kapoor 12 papers + synthetic | Not started |
| C — Negative controls | C1 specificity | sklearn examples | Not started |

---

## 4. Figures (revised feasibility)

Figs 1, 2, 5, 6 unchanged from v0.0 §4 in concept; only Fig 3 and Fig 4
get a v0.1 update.

### Fig 3 — Audit on the cohort

Scope updated from "119 NC papers" to **the 21-paper verified subset
(headline) plus the 32-paper cohort superset (sensitivity panel)**.
Post-expansion, redo with the larger N when ready.

Panel A: heatmap (papers × top-20 rules, color = #findings).
Panel B: bar chart of papers triggering each rule, with R009 dominant.
Panel C: distribution of #findings per paper (skew-right, expected).

Data source: `paper/lint-audit-results.json`.

### Fig 4 — mlgg vs reviewer concerns (now feasible)

v0.0 marked this as the highest reviewer-attack surface and listed it
as blocked on the audit run. With Track A complete at the raw level, the
construction is now concrete:

**Confusion matrix construction** (per paper × per concern):

| | mlgg fires a relevant gate | mlgg silent |
|---|---|---|
| Reviewer raised the concern | TP — confirmation | FN — mlgg blind spot (recommend new gate) |
| No reviewer concern | FP — over-firing (recommend rule tightening) | TN — agreement |

Inputs:
- Reviewer concerns: `peer_review_kb.json` per-entry concern list
  (already structured by category in KB).
- mlgg findings: per-paper output of `mlgg lint` from Track A.
- Mapping: each reviewer concern is independently labeled by two
  annotators with the mlgg gate(s) it would correspond to (or
  `out-of-scope`). Same Cohen's κ ≥0.7 protocol as v0.0 §6 hole 5.

Panels:
- A: confusion-matrix counts on the 21-paper subset.
- B: Sankey of reviewer-concern category → fired rule.
- C: per-category coverage breakdown reproducing the spike-test bimodal
  finding (methodology / reporting / validation: 89–100%; statistical /
  policy / UX: 0%).
- D (new): rule-level FP-rate from the two-annotator audit.

### Other figures

- **Fig 1** (framework overview): unchanged.
- **Fig 2** (per-gate calibration): unchanged in concept; data sources
  are now Track B + Track C.
- **Fig 5** (case study): UKB-MDRMF deep dive unchanged. Optional add-on:
  PR-001 (xOAML) as a "the repo disappeared" data point for the
  reproducibility-crisis framing — see §5 risk.
- **Fig 6** (counterfactual impact): unchanged.

---

## 5. Six-month timeline (revised)

v0.0's M1–M6 assumed corpus was final and audit was unstarted. v0.1
threads three new realities: corpus expansion in progress, FP-rate
audit needed before C2 prevalence claims, PR-RO backfill needed before
N=118 becomes N=125.

| Month | Milestone | Output | Δ vs v0.0 |
|---|---|---|---|
| **M1** | Track B (Kapoor positive) + Track C (sklearn negative) fixtures, ≥3 each per gate | Fig 2 raw data | unchanged |
| **M1.5** | `multiple_testing_gate` (R3.0.5) implementation per spike-test gap | new gate | from v0.0 §13 |
| **M2** | Corpus expansion completes; PDFs reconciled; PR-RO-01..07 backfilled or dropped; strict cohort filter re-applied | final N for paper | new |
| **M2.5** | Two-annotator FP-rate audit on Track A findings (κ ≥0.7) | per-rule TP-rate with 95% CI | new |
| **M3** | UKB-MDRMF GitHub re-audit + SUPPORT2 dual-path consolidation + worst-offender deep dive | Fig 5 raw data | unchanged |
| **M3.5** | Two-annotator reviewer-concern → gate mapping for Fig 4 | confusion matrix | partly new |
| **M4** | First draft (abstract, intro, methods, results) | 30-page manuscript | unchanged |
| **M5** | mlgg self-audit on the paper's own methods + figure refinement + co-author review | submission-ready PDF | unchanged |
| **M6** | Senior co-author recruitment + final revisions + cover letter | submission | unchanged |

Critical path: M2 → M2.5 → M3.5. C2 and C3 numerical claims cannot be
finalized until the FP-rate audit (M2.5) and the κ audit (M3.5) both
complete.

---

## 6. Data-integrity audit trail (new)

The paper itself follows mlgg's own evidence-trail discipline. Three
artifacts document this and will be released alongside submission:

### 6.1 PR-040 fabrication and quarantine

During final pre-paper validation, PR-040 was found to have an entry
in `peer-review-kb.json` whose DOI, title, and reviewer concerns did
not match any real Nature Communications paper. The entry was deleted;
the associated PDF was moved to
`references/case-studies/_quarantine/` and is excluded from all
analyses. This event is recounted in the paper Methods as a worked
example of why automated provenance reconciliation matters even for
hand-curated KBs.

### 6.2 PR-RO-01..07 pending status

Seven entries (PR-RO-01..07) are flagged `pending_manual_validation`
in the KB. They are excluded from headline numbers and will either be
backfilled before submission or dropped. Their existence is reported
in the paper as part of the conservative-N framing.

### 6.3 PR-001 post-publication repo deletion

The `novonordisk-research/xOAML` GitHub repository linked from PR-001
was deleted after publication. This is a real-world reproducibility-
crisis data point and is discussed as such in the Discussion (one
paragraph), citing the deletion as evidence for why pre-publication
governance, not post-hoc audit, is the load-bearing intervention.

### 6.4 Reconciliation and discovery scripts

| Script | Purpose | Output |
|---|---|---|
| `scripts/diagnostics/reconcile_peer_review_pdfs.py` | KB ↔ on-disk PDF matching with confidence | `paper/reconciliation-report.{md,json}`, `pdf_verification` field per KB entry |
| `scripts/diagnostics/discover_corpus.py` | OpenAlex candidate discovery for corpus expansion | `paper/discovery-candidates.json` |
| `scripts/diagnostics/download_discovered_pdfs.py` | Fetch peer-review PDFs from Springer ESM | `paper/expanded-corpus-status.json` |

All three are versioned in the repository and their output is
reproducible from a clean checkout. The paper Methods will include a
"Reproduction" subsection pointing to these scripts.

---

## 7. Open questions for user

Carried over from v0.0 §11:

Q1. Senior clinical co-author profile?
Q2. Disease-KB clinical review owner?
Q3. Time commitment level (3 / 6 / 12 months)?
Q4. Authorship preference (first author / last-corresponding)?
Q5. Is paper in English-only or bilingual (CN companion blog post)?

New in v0.1:

Q6. Do we wait for the corpus expansion to finish (estimated N = 500–800
    base, ~150–250 cohort-scope) before drafting, or draft against the
    21-paper subset and add the larger N as a sensitivity panel?
Q7. PR-RO-01..07: backfill effort (~½ day each) vs drop-and-cite?
Q8. Two-annotator audit: do we have a second annotator lined up, or does
    M2.5 / M3.5 need a recruitment step prepended?
Q9. Should PR-001 xOAML repo deletion get its own short subsection
    ("when reproducibility evaporates") or one Discussion paragraph?

---

## 8. Versioning

- v0.0 (`outline-v0.md`): pre-spike outline, frozen as historical record.
- v0.1 (this file): post-spike, post-corpus-tightening, mid-expansion.
  Reflects 118-entry KB, 21-paper verified subset, Track A lint audit,
  and the data-integrity audit trail.
- v0.2 (planned): post-corpus-expansion, post-FP-rate audit. Final N,
  final per-rule TP-rates, finalized Fig 4 confusion matrix.
- v1.0: post first-author review, ready for co-author distribution.
