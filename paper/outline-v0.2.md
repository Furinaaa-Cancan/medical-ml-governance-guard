# mlgg paper — outline v0.2

**Status**: post-OpenAlex-discovery, post-5-agent-audit, post-backport
**Owner**: Wengcan
**Last updated**: 2026-05-10
**Predecessor**: `paper/outline-v0.1.md` (118-base, 21-verified) — kept as
historical record, not deleted.

Supersedes v0.1 as the source of truth. Diffs in §0; threaded through
§§ 2, 3, 4, 5, 6, 7.

---

## 0. Diff summary vs v0.1

| Area | v0.1 | v0.2 |
|---|---|---|
| Corpus base | 118 (PR-040 quarantined) | **335 active** (111 PR-orig + 7 PR-RO + 217 PR-EXP); PR-040 still quarantined |
| Discovery method | manual curation only | OpenAlex + filename mapping + 5-parallel-agent audit |
| Cohort scope tagging | implicit data_type filter | explicit `is_cohort_retrospective_binary` field; backported from PR-EXP audit to PR-orig via data_type rules |
| In-scope subset | 32 cohort-binary (21 verified PDF) | **158 cohort-binary** across all layers |
| Trustable subset (Fig 4 input) | 21 (verified PDF only) | **31** (cohort-binary AND reviewer_concerns≥1) |
| Code availability | 17/21 with link, 12 cloned, 8 with Python | **110/125 PR-EXP cohort-binary with public code** (88%); 91 GitHub, 60 Zenodo/DOI |
| Track A audit run | 8-paper baseline (260 raw findings) | 8-paper baseline still authoritative; 110-paper expansion in flight (Agent 2, not yet merged) |
| Validation tracks | A (lint), B (Kapoor), C (sklearn) | A, A.5 (TP/FP audit), B, C, **D (R029 credentials gate, new)** |
| Audit trail | PR-040, PR-RO, PR-001 deletion | + 5-agent parallel audit, post-audit cleanup, npj DM TPR opt-out gap, PR-EXP-0214 credentials finding |
| Limitations §7 | scattered through narrative | new explicit §7 surfacing rubric divergence, corrupt-PDF residual, PR-RO abstract-only, npj DM gap |

---

## 1. Strategic positioning

Title, journal tier, competitive matrix unchanged from v0.0/v0.1. Three
claims still hold; evidence base is wider (335 vs 118) and more
provenance-tracked.

### 1.1 The three claims (must each survive reviewer attack)

| Claim | Quantitative target | Evidence | Data source | v0.2 status |
|-------|---------------------|----------|-------------|-------------|
| **C1 — Tool calibration** | Per-gate sensitivity ≥0.85 / specificity ≥0.90 | Fig 2 | sklearn negative + Kapoor positive + `examples/` | unchanged |
| **C2 — Audit findings** | ≥X% of in-scope cohort papers have ≥1 mlgg-detectable issue | Fig 3, Table 2 | 8-paper baseline → 110-paper expansion in flight | promoted from "raw data" to "raw data + expansion infrastructure ready" |
| **C3 — Reviewer-concern recovery** | ≥85% in-scope coverage | Fig 4 | 31-paper trustable subset (cohort-binary AND concerns) | promoted from "constructable in principle" to "trustable subset enumerated, ready for κ audit" |

C3 remains the story climax. Whether 31 is large enough to carry
publication-grade confusion-matrix claims is open (see §7 and Q12).

---

## 2. Corpus

### 2.1 Layered base KB

| Layer | ID pattern | Count | Source | Has reviewer_concerns | Has cohort scope flag |
|---|---|---:|---|:---:|:---:|
| Manually curated | `PR-NNN` (excl. PR-040) | 111 | Hand-curation 2024–2026 | 105 | backported via data_type |
| Reporting-only | `PR-RO-NN` | 7 | Manual; 5 with PDF metadata extracted, 2 abstract-only | 0 | partial |
| OpenAlex-discovered | `PR-EXP-NNNN` | 217 | OpenAlex 2020–2026 + Springer ESM PDFs + 5-agent audit | 0 | yes (audit-populated) |
| Quarantined | `PR-040` | 1 | Excluded; fabrication audit | n/a | n/a |
| **Active total** | | **335** | | **105** | **158 cohort=True** |

Manually curated subtotal (PR-orig + PR-RO) = **118** — exactly v0.1's
base; v0.2 adds the 217 PR-EXP layer. PR-040 preserved on disk for
audit-trail reproducibility but excluded from all analysis counts.

### 2.2 Journal coverage

| Journal | Count | Year range | n_with_sample_size | Median sample_size |
|---|---:|---|---:|---:|
| Nature Communications | 248 | 2020–2026 | 116 | 5,183 |
| Communications Medicine | 87 | 2021–2026 | 35 | 1,033 |

Only two journals in the active KB. OpenAlex discovery did not yield
PR-EXP entries from npj Digital Medicine (305 candidates, 0 PDFs — see
§7), BMJ EBM, Lancet Digital Health, JAMA, or Nature Medicine.

### 2.3 mlgg scope filter (cohort + binary + tabular)

| Filter | Count | Notes |
|---|---:|---|
| Active KB | 335 | layered base above |
| `is_cohort_retrospective_binary == true` (any layer) | 158 | 32 PR-orig (backported) + 1 PR-RO + 125 PR-EXP |
| AND `len(reviewer_concerns) > 0` | **31** | trustable subset for Fig 4 |
| AND `peer_review_pdf_path` set | 31 | all 31 have PDF on disk |

The **31-paper trustable subset** is the conservative input for Fig 4.
v0.1's 21 were filtered by PDF-verification confidence; v0.2's 31 are
filtered by explicit scope tag + concerns presence — different
predicates, ~17-entry overlap.

### 2.4 mlgg-lint runnable subset (PR-EXP cohort-binary)

| Filter | Count | % |
|---|---:|---:|
| PR-EXP cohort-binary | 125 | 100% |
| with `primary_repo` populated | 110 | 88% |
| of those: GitHub repos | 91 | 73% |
| of those: Zenodo / DOI archives | 60 | 48% |
| of those: Figshare / OSF | 1 | <1% |
| no public code link found | 15 | 12% |

Source: `paper/code-repos-cohort-binary.json` (n=125). The 110-paper
"any public code" subset is the ceiling for Track A expansion (§3).

### 2.5 Coverage & confidence (PR-EXP layer audit, n=217)

| Confidence | Count | % |
|---|---:|---:|
| high | 144 | 66.4% |
| medium | 57 | 26.3% |
| low | 16 | 7.4% |

Anomaly flags (multi-flag-allowed):

| flag | n | Notes |
|---|---:|---|
| `title_does_not_match_pdf` | 26 | 24/26 in PR-EXP-0151..0175 (chunk-4 mapping bug) |
| `topic_not_medical_ml` | 15 | filtered out of in-scope subsets |
| `pdf_corrupt_or_empty` | 6 | 3/6 redownloaded; 2/6 still failing (large-file CDN); 1/6 has no TPR file |
| `pdf_not_peer_review` | 1 | PR-EXP-0217 |

Fully populated audit detail: `paper/corpus-statistics.md` §6.

### 2.6 Cross-chunk rubric consistency (audit-quality flag)

| Chunk | ID range | n | %cohort=true | Journal mix |
|---|---|---:|---:|---|
| 1 | 0001–0044 | 44 | **9.1%** | CommMed only |
| 2 | 0045–0088 | 44 | 75.0% | mixed |
| 3 | 0089–0132 | 44 | **88.6%** | NC only |
| 4 | 0133–0176 | 44 | 59.1% | NC only |
| 5 | 0177–0217 | 41 | 56.1% | NC only |

Range = 79.5 pp; year-controlled (2025-only) gap = 4.3% vs 72.2% — a
**rubric divergence between agents**, not pure sample skew. Documented
in §7; chunk-1 re-spot recommended before 158 is published as
authoritative.

---

## 3. Validation strategy (four tracks + one new gate)

### 3.1 Track A — Lint audit on cloned cohort repos (Fig 3)

| Step | Result (current) | Result (target) |
|---|---|---|
| Repos targeted (8-paper baseline) | 13 (12 cloned, 8 with Python) | n/a |
| Repos targeted (110-paper expansion) | in flight (Agent 2) | 110 |
| Repos with ≥1 mlgg-lint finding (8-paper) | **7 of 8** | n/a |
| Total raw findings (8-paper) | **260** (190 W + 55 I + 15 E) | 110-paper expansion pending |
| Top-firing rule (8-paper) | **R009** (no_confidence_intervals, fires 7/7) | rule-frequency redo with N=110 |
| Other high-firing | R022, R021, R013, R004, R008 | same |

If `paper/lint-audit-110.json` lands before draft time, replace the
8-paper headline with the 110-paper run; otherwise the 8-paper baseline
remains authoritative and the 110-paper expansion is "in progress" in
Methods.

**FP-rate caveat (unchanged from v0.1)**: 260 is *raw* output.
Two-annotator κ ≥0.7 on stratified random sample (n=100, proportional-
to-rule) is a prerequisite for any prevalence claim. Track A.5
operationalizes this.

### 3.2 Track A.5 — TP/FP audit (calibration of audit findings)

New explicit track. Input: Track A raw findings. Output: per-rule
TP-rate with 95% CI. If `/tmp/agent03-tpfp-sample.json` lands before
draft, summarize aggregate TP-rate; otherwise: "protocol + sample size
locked, awaiting second annotator."

### 3.3 Track B — Positive controls (Kapoor 12)

Kapoor & Narayanan 2023 *Patterns* taxonomy → 41 papers / 30 fields →
~12 fall within mlgg's retrospective-cohort binary scope. Plan
unchanged from v0.1: per-gate target ≥3 positive fixtures, synthetic
where Kapoor doesn't cover a gate.

### 3.4 Track C — Negative controls (sklearn)

scikit-learn `examples/` + `model_selection` notebooks. Per-gate target
≥3 negative fixtures. Unchanged.

### 3.5 Track D — R029 credentials gate (new)

Surfaced during 5-agent audit follow-up: **PR-EXP-0214's companion
repo contains credentials** — not covered by mlgg's existing rule set.
If Agent 5's R029 rule artifact lands, Track D becomes a "discovered-
via-corpus" gate contribution and a worked Discussion example of the
audit-driven feedback loop. Paper-flag-worthy: framework evolves with
the literature it audits, not a closed checklist.

### 3.6 Track summary

| Track | Purpose | Source | Status |
|---|---|---|---|
| A — Lint audit | C2 audit findings | 8 cloned cohort repos (baseline) → 110-repo expansion (pending) | baseline in hand; expansion in flight |
| A.5 — TP/FP audit | C2 calibration of audit findings | stratified sample of Track A findings | protocol locked; awaiting second annotator |
| B — Positive controls | C1 sensitivity | Kapoor 12 papers + synthetic | not started |
| C — Negative controls | C1 specificity | sklearn examples | not started |
| D — R029 credentials gate | new contribution from corpus audit | PR-EXP-0214 finding | rule pending Agent-5 output |

---

## 4. Figures (revised feasibility)

Figs 1, 2, 5, 6 unchanged in concept from v0.1. Fig 3 and Fig 4 carry
all the substantive v0.2 movement.

### 4.1 Fig 3 — Audit on the cohort

Scope updates:
- Headline panel: **31-paper trustable subset** (cohort-binary AND
  reviewer_concerns ≥1) for the C2/C3 joint claim.
- Sensitivity panel: **110-paper PR-EXP cohort-binary with public
  code** for broader C2 prevalence, once 110-paper lint completes.
- Methods reports both: 31 conservative primary; 110 high-N sensitivity.

Panels A/B/C unchanged in shape (heatmap; rule-frequency bar chart;
findings-per-paper skew-right histogram).

Data source: `paper/lint-audit-results.json` (8-paper) + (when ready)
`paper/lint-audit-110.json`.

### 4.2 Fig 4 — mlgg vs reviewer concerns (now feasible at N=31)

Confusion matrix construction (per paper × per concern) unchanged in
shape from v0.1; what's new is the input is now enumerable.

| | mlgg fires a relevant gate | mlgg silent |
|---|---|---|
| Reviewer raised the concern | TP — confirmation | FN — mlgg blind spot (recommend new gate) |
| No reviewer concern | FP — over-firing (recommend rule tightening) | TN — agreement |

Inputs:
- Reviewer concerns: 31 PR-orig entries with `is_cohort_retrospective_binary == true` AND `reviewer_concerns ≥ 1` (aggregate counts only — IP guard, no reviewer text in figure or caption).
- mlgg findings: per-paper Track A output on the 31-ID ∩ cloned-repo set.
- Mapping: each concern independently labeled by two annotators with
  the mlgg gate it would correspond to (or `out-of-scope`); Cohen's
  κ ≥0.7.

Panels: A confusion-matrix counts (n=31); B Sankey concern-category →
fired rule; C bimodal coverage breakdown (methodology / reporting /
validation: 89–100%; statistical / policy / UX: 0%); D rule-level
FP-rate from Track A.5.

If Agent 7 emits `paper/fig4-trustable-subset.json` (or similar), cite
as canonical input; otherwise reference the 31-ID list directly.

### 4.3 Other figures

Fig 1 (framework overview), Fig 2 (per-gate calibration; data from
Tracks B+C), Fig 5 (UKB-MDRMF case study; optional PR-001 xOAML "repo
disappeared" add-on), Fig 6 (counterfactual impact) — all unchanged
from v0.1.

---

## 5. Six-month timeline (revised)

v0.2 collapses v0.1's "expansion" milestone (now done at N=335) and
pushes κ-audit + 110-paper lint expansion to the critical path.

| Month | Milestone | Output | Δ vs v0.1 |
|---|---|---|---|
| **M1** | Track B (Kapoor positive) + Track C (sklearn negative) fixtures, ≥3 each per gate | Fig 2 raw data | unchanged |
| **M1.5** | `multiple_testing_gate` (R3.0.5) implementation per spike-test gap | new gate | unchanged |
| **M1.5** | Track D: R029 credentials gate stabilized + tests | new gate | new from v0.2 |
| **M2** | Chunk-1 cohort-flag re-spot (10-paper sample) + corpus statistics frozen | final N for paper | replaces v0.1 "expansion completes" |
| **M2** | 110-paper Track A lint expansion (in flight as of v0.2) | 110-paper findings JSON | new from v0.2 |
| **M2.5** | Two-annotator FP-rate audit on Track A findings (κ ≥0.7) | per-rule TP-rate with 95% CI | unchanged |
| **M3** | UKB-MDRMF re-audit + SUPPORT2 dual-path consolidation + worst-offender deep dive | Fig 5 raw data | unchanged |
| **M3.5** | Two-annotator reviewer-concern → gate mapping for Fig 4 (n=31 input) | confusion matrix | tightened scope (was "21-paper subset") |
| **M4** | First draft (abstract, intro, methods, results) | 30-page manuscript | unchanged |
| **M5** | mlgg self-audit on the paper's own methods + figure refinement + co-author review | submission-ready PDF | unchanged |
| **M6** | Senior co-author recruitment + final revisions + cover letter | submission | unchanged |

Critical path: M2 (chunk-1 re-spot + 110-paper lint) → M2.5 (FP-rate κ
audit) → M3.5 (concern→gate κ audit). C2 and C3 numerical claims
cannot be finalized until all three κ audits complete.

---

## 6. Data-integrity audit trail (extended)

The paper follows mlgg's own evidence-trail discipline. Five artifacts
document this and ship with submission.

### 6.1 PR-040 fabrication + quarantine (from v0.1)

DOI/title/concerns triangle did not resolve to any real NC paper.
Entry deleted; PDF moved to `_quarantine/`; excluded from all counts.
Recounted in Methods as a worked example for hand-curated-KB
reconciliation.

### 6.2 PR-RO-01..07 partial backfill

5 of 7 now have PDF metadata; 2 (PR-RO-01, -02) remain
`metadata_source == 'abstract_only'` (no PR file exists for the
underlying papers). None has reviewer_concerns. **Partial
completion**; excluded from the 31-paper trustable subset.

### 6.3 PR-001 post-publication repo deletion (from v0.1)

`novonordisk-research/xOAML` deleted post-publication. One Discussion
paragraph cites this as evidence for pre-publication governance over
post-hoc audit.

### 6.4 Five-parallel-agent audit + cleanup (new in v0.2)

| Pass | When (UTC) | Method | Output |
|---|---|---|---|
| Initial audit | 2026-05-10T05:38 | 5 parallel agents, ~44 PR-EXP/agent | cohort=125, corrupt=6, out-of-scope=15, title-mismatch=26 |
| Post-audit cleanup | 2026-05-10T06:06 | Redownload corrupt PDFs; backport scope flag to 118 | 3 redownloaded, 2 large-file fail, 1 no-TPR; 118 backported |
| 10-agent follow-up | in flight | finer-grain redo + R029 surfacing | pending |

**IP guard**: agents extracted structured field labels only
(categorical `data_type`, one-line `prediction_task`, boolean flags,
brief structural `evidence_basis`). NO reviewer-text, abstract, or
title-verbatim emitted. Rule extends to the paper.

### 6.5 PR-EXP-0214 credentials finding (paper-flag-worthy)

Agent follow-up flagged PR-EXP-0214's companion repo as containing
credentials — not covered by pre-audit rule set. Becomes the
proof-point for Track D (R029, §3.5) and a Discussion worked example.

### 6.6 npj Digital Medicine TPR opt-out gap (worth discussing)

305 npj DM candidates, **0 PDFs** retrievable via Springer ESM —
authors largely do not opt in to TPR despite the journal supporting
it. Methods reports as (a) corpus-construction limitation and (b)
substantive observation about differential TPR adoption across
Springer Nature medical AI journals.

### 6.7 Reconciliation and discovery scripts

| Script | Purpose | Output |
|---|---|---|
| `scripts/diagnostics/reconcile_peer_review_pdfs.py` | KB ↔ on-disk PDF matching with confidence | `paper/reconciliation-report.{md,json}`, `pdf_verification` per entry |
| `scripts/diagnostics/discover_corpus.py` | OpenAlex candidate discovery | `paper/discovery-candidates.json` (614 candidates) |
| `scripts/diagnostics/download_discovered_pdfs.py` | Fetch peer-review PDFs from Springer ESM | `paper/expanded-corpus-status.json` |
| `scripts/diagnostics/find_code_repos.py` | Code-repo discovery + classification | `paper/code-repos-cohort-binary.json` (110/125 with code) |

All four versioned; output reproducible from clean checkout. Methods
adds a "Reproduction" subsection.

---

## 7. Limitations & known gaps (new explicit section)

Surfacing what v0.1 had implicit. Each item gets paper Methods or
Discussion airtime — not buried.

### 7.1 Audit-rubric divergence between agent chunks

5-agent run produced cohort=true rates of **9.1% (chunk 1, 4/44) vs
75–89% (chunks 2–3) vs 56–59% (chunks 4–5)**. Year-controlled (2025
only): 4.3% vs 72.2%. **Not** explained by year or journal alone — a
labeling-rubric drift between agents. Mitigation: chunk-1 re-spot of
~10 hand-labeled entries before publishing the 158 in-scope number.

### 7.2 Two corrupt PDFs still pending

3 of 6 redownloaded (PR-EXP-0150, -0188, -0190). **2 still failing**
(PR-EXP-0044, -0080) due to Nature CDN per-request cap; need chunked
download. **1 has no TPR file** (PR-EXP-0007) — underlying paper opts
out.

### 7.3 PR-EXP-0007 — no peer review file

Single-paper case, methodologically interesting: TPR is opt-in even
within NC. The opt-out rate within NC/CommMed is **not measured
systematically** in v0.2 — recommended follow-up.

### 7.4 PR-RO-01 / PR-RO-02 are abstract-only

Metadata from abstract only; no PR file for these two papers. Excluded
from all in-scope subsets; reported as known PR-RO-layer coverage gap.

### 7.5 npj Digital Medicine: 305 candidates, 0 PDFs

Restated from §6.6 as a limitation: corpus is **two-journal-only** (NC
+ CommMed) despite scaffolding for 7 venues. npj DM TPR opt-out
substantively interesting but limits external validity.

### 7.6 Two "corrupt PDF" markers disagree

`_pdf_status == 'corrupt_needs_redownload'` set on 4 entries;
audit-flag layer flags 6. Pre-submission cleanup task; not blocking
v0.2.

### 7.7 Trustable subset n=31 may be undersized for Fig 4

31 is the conservative input for the Fig 4 confusion matrix. Whether
31 supports the per-category coverage breakdown at publishable CI is
Q10 (§9). Options: (a) ship at n=31 with explicit CIs; (b) extract
reviewer concerns for the 125 PR-EXP cohort-binary entries (≥1
person-week + IP-guard re-audit; payoff: n→~150).

---

## 8. Versioning

- v0.0 (`outline-v0.md`): pre-spike, frozen.
- v0.1 (`outline-v0.1.md`): 118-base / 21-verified / Track A 8-paper. Frozen.
- v0.2 (this): 335 / 158 / 31 / 110-of-125. Track D added.
- v0.3 (planned): post-110-lint, post-FP-rate κ, post-chunk-1 re-spot.
- v1.0: post first-author review, ready for co-author distribution.

---

## 9. Open questions for user

Carried from v0.1 (full text in that doc):

Q1. Senior clinical co-author profile?
Q2. Disease-KB clinical review owner?
Q3. Time commitment (3 / 6 / 12 months)?
Q4. Authorship preference?
Q5. English-only or bilingual?
Q6. Wait-for-expansion vs draft-now? **Resolved in v0.2**: expansion
    done at N=335; draft against the 31 trustable subset.
Q7. PR-RO backfill vs drop? **Partially resolved**: 5/7 have PDF
    metadata; 2 remain abstract-only.
Q8. Second annotator for κ audit?
Q9. PR-001 xOAML — subsection or Discussion paragraph?

New in v0.2:

Q10. **Is n=31 large enough for Fig 4?** Or invest ≥1 person-week to
     extract reviewer concerns for the 125 PR-EXP cohort-binary
     entries (full IP-guard protocol) → n≈150?
Q11. **R029 credentials gate**: ship as paper-flag-worthy Discussion
     paragraph ("framework evolves with corpus"), or stand-alone gate
     paper later?
Q12. **Chunk-1 re-spot** (~10 entries): same annotator as κ audit, or
     independence required?
Q13. **npj DM TPR opt-out**: 0.5-page Methods observation, Discussion
     bullet, or stand-alone short report?
Q14. **PR-EXP-0214 credentials in Discussion**: how much detail is
     responsible? IP guard forbids title-verbatim; the finding itself
     (credentials in published code) is a public-code fact, but
     ID-to-finding linking may be a soft IP risk.

---

## 10. IP-compliance note (sticky)

Aggregate counts + structured IDs only. No reviewer-text quotation.
Paper-title verbatim is forbidden; factual identifiers like
"TransformEHR (PR-004)" are allowed.

Same rule binds the paper, figures, supplements, and any released
artifact. Codified in `peer-review-kb.json` →
`provenance.integrity_audits[*].ip_compliance_note`.
