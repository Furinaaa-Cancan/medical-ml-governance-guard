# W14 RAG Audit — Evidence Index

**Date**: 2026-05-17
**Scope**: `scripts/rag/` production RAG + KBs (`peer-review-kb.json` 335 papers, `literature-knowledge-base.json` 67 papers, `disease-definition-knowledge-base.json` 11 entries) + eval (`references/retrieval_eval/`) + reporting (`scripts/reporting/`) + gates (`scripts/gates/`).
**Reviewer role**: per `CLAUDE.md` — Nature Methods / JAMA-level, skeptical, organized as Major / Minor / Questions.
**Method**: 10 parallel audit agents (A–J), each writing a self-contained `.md` report. Findings cross-validated where overlapping; disagreements explicitly noted (see C vs I on cohort supporter IDs).

---

## Audit agents (full reports)

| Agent | Focus | Report | Finding tier | Resolved by |
|---|---|---|---|---|
| **A** | Dense-only ablation on production hybrid | [audit_agent_A_ablation.md](audit_agent_A_ablation.md) | Stale-baseline Major (new) | commit `d53a9e5` |
| **B** | L27 preprocessing-leak retrieval reproduction | [audit_agent_B_leak_repro.md](audit_agent_B_leak_repro.md) | **M2** (upgraded: KB content gap) | commit `c8e651c` (band-aid); long-term 7-rule KB audit |
| **C** | KB gate-tag completeness draft (M5+m4) | [audit_agent_C_kb_tags.md](audit_agent_C_kb_tags.md) | **M5** Major (upgraded), m4 | commit `de27889` |
| **D** | `entries[:20]` sort-before-truncate fix | [audit_agent_D_sort_fix.md](audit_agent_D_sort_fix.md) | m7 Minor | commit `dd7678b` (D itself) |
| **E** | M1 "human-labeled" description correction | [audit_agent_E_desc.md](audit_agent_E_desc.md) | **M1** Major | commit `93e6e3d` |
| **F** | `bm25.py:271` `[:5]` truncation forensics | [audit_agent_F_bm25_trunc.md](audit_agent_F_bm25_trunc.md) | m8 RETRACTED (false positive) | — (no fix needed) |
| **G** | Hybrid fusion-weight grid search | [audit_agent_G_hybrid_grid.md](audit_agent_G_hybrid_grid.md) | M3 RETRACTED + M3' (metric contract) | commit `49e1222` (METRIC_CONTRACT.md) |
| **H** | `peer-review-kb.json` schema validation (335 entries) | [audit_agent_H_schema.md](audit_agent_H_schema.md) | New Major (24 partial-promote) + KB metadata Minor | commit `ca1f2e3` (metadata fix); 24-entry contract still open |
| **I** | Zero-support gates deep-dive | [audit_agent_I_zero_support.md](audit_agent_I_zero_support.md) | **M5** Major (concurrent with C) | commit `de27889` (used C's variant) |
| **J** | Synthesis prep — current-state inventory | [audit_agent_J_current_state.md](audit_agent_J_current_state.md) | New Major: W7-W13 CHANGELOG gap + F-01 disease KB | commit `aaf8ee0` (CHANGELOG); commit `6fa5883` (F-01 banner) |

---

## Findings → commits map

| Finding | Tier | Resolution commit | Notes |
|---|---|---|---|
| **M1** — `labeled_precision_at_5.json` mis-claims "human-labeled" | Major | `93e6e3d` | Test docstring at `tests/test_labeled_precision.py:1-10` synced in same commit |
| **M2** — `peer-review-kb` has 0 concerns for MLGG-P01 canonical pattern | Major | `c8e651c` (band-aid via curated fallback in `scripts/core/gate_rag_bridge.py`) | Long-term fix: 7-rule (S01/P01/F01/F02/M01/E01/E02) KB-coverage audit |
| **M3** — Hybrid mean_tag_precision drop vs BM25-only | **RETRACTED** | — | Was based on W11-era stale `baseline_hybrid.json`. Reframed as M3'. |
| **M3'** — Metric contract missing (proxy tag_p vs labeled_P@5 disagree) | Major (new) | `49e1222` (METRIC_CONTRACT.md) | Owner currently unassigned; flagged for W15. |
| **M5** — `cohort_definition_gate` zero lit support × 46% concern volume | Major (upgraded from Minor m5) | `de27889` | `shap_interpretability_gate` still 0-support (true KB-gap, content-add task) |
| **m4** — 14 fragile single-source gates | Minor | `de27889` | 7 lifted to ≥3 supporters; 5 to 2; 2 SLSA by design |
| **m6** — 4 untagged entries | Minor | `de27889` | LIT-018/019 tagged; LIT-004/042 out-of-scope by design |
| **m7** — `entries[:20]` no-sort truncation | Minor | `dd7678b` | Composite sort key + 7 new tests |
| **m8** — `bm25.py:271 [:5]` | **RETRACTED** | — | Intentional shape-sampling in `_validate_kb_shape()` |
| New Major — stale `baseline_hybrid.json` blocks `--strict` | — | `d53a9e5` | tag_p 0.338→0.669, hit@5 0.867→1.0 |
| New Major — W7-W13 RAG work absent from CHANGELOG | — | `aaf8ee0` | Retroactive log + W14 audit block in `[Unreleased]` |
| New Major — F-01 disease KB unsigned (cohort/definition/lineage) | Partial | `6fa5883` | PROVISIONAL banner emits; fail-closed escalation deferred |
| New Major — 24 partial-promote PR-EXP-* schema violations | **OPEN** | — | Contract-design decision needed from owner |
| New Minor — KB self-report `total_concerns: 449 ≠ actual 817` | — | `ca1f2e3` | Synced to 817; stats file regenerated via `parse_peer_reviews.py --stats` |

---

## Open items (owner decision required)

1. **24 partial-promote `PR-EXP-*` entries** (audit H): extend META_ONLY contract to accept "has concerns but missing other fields", OR backfill the missing 6-8 core fields per entry. Decision needed before next schema validation pass.
2. **F-01 fail-closed escalation**: should `cohort_definition_gate` / `definition_variable_guard` / `feature_lineage_gate` exit 2 when `claim_tier=publication-grade` AND any disease entry is `clinician_review_status=pending`? Currently emits warning only.
3. **SHAP gate KB-gap**: `shap_interpretability_gate` cites Lundberg & Lee 2017 (NeurIPS), Lundberg 2020 (Nat Mach Intell), PMC11513550 (2024 SHAP guide), arXiv 2505.24612 (2025 rank aggregation) — none exist in `literature-knowledge-base.json`. Needs 4 new KB entries (content authoring, not just tagging).
4. **METRIC_CONTRACT.md owner**: file is on `main` but `Owner` field is "currently unassigned". No enforcement teeth until assigned.
5. **C vs I disagreement on cohort_definition_gate supporter IDs**: audit C tagged LIT-001/031/041/058; audit I proposed LIT-001/005/034/035. Commit `de27889` used C's version. If owner reviews and prefers I's set, hand-edit.

---

## Method-honesty notes (self-audit of this audit)

Three substantive errors in the initial round, all caught by cross-validation:
1. **M3 was based on stale baseline** — read `baseline_hybrid.json` (W11) instead of `post_wave7_baseline_hybrid.json` (W13). Should have `ls -lat` the directory before drawing conclusions. Caught by agent G.
2. **m5 framed as Minor when it was Major** — the 2/33 gates fraction undercounted; the 46% reviewer-concern-volume routing through those gates is the right metric. Caught by agent I.
3. **m8 was a false positive** — read `[:5]` as truncation, didn't read the function's docstring. Caught by agent F.

These are documented in commit `aaf8ee0` (CHANGELOG W14 audit block) under the explicit "RETRACTED" tags.

---

## Provenance

All 10 agent reports were produced by parallel Claude Opus 4.7 (1M context) sub-agents on 2026-05-17 between 12:22 and 12:36 local time. Reports are pinned snapshots; if a finding is referenced elsewhere it should cite this directory rather than re-derive.
