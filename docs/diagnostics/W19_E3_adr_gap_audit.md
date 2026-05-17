# W19-E3 — ADR Coverage Gap Audit

**Date**: 2026-05-17
**Author**: W19-E3 (strict-review Wave 19, final wave)
**Scope**: identify major design decisions not captured by an ADR; rank top gaps by ROI
**Mode**: READ-ONLY (no source modifications)

## 1. Existing ADRs (4)

| # | Title | Wave | Scope |
|---|-------|------|-------|
| 0001 | `_mmr_breakdown` consumer = `mlgg rag --explain` | W11-I2 | small (one UX surface) |
| 0002 | Race-proof commit protocol | W13-C0 | medium (process) |
| 0003 | Unused analysis tools wiring (`subgroup_dca` shipped; 2 deferred) | W13-T0 | small |
| 0004 | Worktrees default-on for parallel sessions | W14-X1 | medium (process) |

Three of four ADRs are **process** decisions; only 0001 + 0003 cover product/design. The product surface (33 gates, hybrid RAG, KB governance, report envelope, MLGG canonical rules) is essentially undocumented as ADRs — rationale lives in wave retros and diagnostics, which are append-only narratives, not living decision records.

## 2. Candidate gap inventory (12 found)

For each I checked whether the rationale is already captured *somewhere durable*. "Buried" = present but not as a decision record; "absent" = no rationale anywhere; "ADR-shaped" = decision is durable + controversial enough that future contributors will re-litigate without an ADR.

| # | Candidate decision | Where rationale lives today | ADR-shaped? |
|---|---|---|---|
| C1 | Hybrid 4-signal architecture (dense + BM25 + tag + severity) + MMR | `docs/ARCHITECTURE.md` §"Hybrid ranker"; `RAG_WAVE_1_TO_8_RETRO`; `E2_hybrid_decomposition`; `W18_D1_post_p0_ablation` | YES — distributed across 4 docs, no single canonical source |
| C2 | `WEIGHT_DENSE` 0.5 → 0.1 (W13-P0) | retro §W11-I1; commit `cc3c717`; `W18_D1` confirmed post-P0 | YES — numeric tuning lives only in commit body + retro narrative |
| C3 | MLGG 7 canonical unchallengeable rules (S01/P01/F01/F02/M01/E01/E02) | `CLAUDE.md` lists them; `SKILL.md` references; no design doc on **why these 7** vs the other 26 | YES — load-bearing for every gate; "why not more, why not fewer" is unanswered |
| C4 | `build_report_envelope` v2.0.0 single source of truth | `scripts/core/_gate_framework.py:185`; `W15_A2_report_schema_audit` | YES — schema version is a contract; bump policy + scope unwritten |
| C5 | Disease KB fail-closed triple (reviewer + last_reviewed + status) | retro §W11-F2; commit `04ad7d7`; `W17_C2_disease_kb_audit` | YES — security boundary; "why AND not OR" is the entire fix |
| C6 | `mlgg workflow` vs `mlgg audit` mode split | `SKILL.md` §"怎么选" (3 lines) | YES — top-level UX dichotomy with no design doc explaining the boundary |
| C7 | `--strict` tier semantics (when required, what it adds) | scattered across gates + `SKILL.md`; ADR 0003 mentions but doesn't define | YES — "publication-grade" claims hinge on it |
| C8 | Percentile bootstrap (not BCa) for CI matrix | `ci_matrix_gate.py:244-274` inline comment; `W16_B5` notes "documented design choice" | MEDIUM — already commented in code, but ADR would let reviewers find it |
| C9 | MLGG Python gates vs Claude Skill prompts split | `SKILL.md` long-form; `CLAUDE.md` modality boundary | YES — defines product surface; currently only Chinese long-form prose |
| C10 | BGE-large-en-v1.5 model choice + query/passage prefix | `ARCHITECTURE.md` mentions; no rationale for *this* model vs alternatives | LOW — choice is conventional; low controversy |
| C11 | `MMR_COSINE_FLOOR = 0.88` | `ARCHITECTURE.md` line 58; `RAG_WAVE_1_TO_8_RETRO` W8 | LOW — one-line tuning, already in ARCHITECTURE |
| C12 | Cache invariant ("hash written after data" crash-safety) | `E4_cache_perf.md`; `W18_D5_cache_invalidation_audit` | LOW — diagnostic already authoritative |

## 3. Top 5 ADRs to write first (ranked by ROI)

ROI = durability × controversy × tribal-knowledge risk. The bar is: a new contributor in 6 months will independently re-derive (or worse, *re-litigate*) the decision without it.

### ADR 0005 — Hybrid 4-Signal Retrieval Architecture (C1 + C2 merged)
**What it covers**: Why 4 signals (dense + BM25 + tag + severity) + MMR rerank, not 1 or 2 or 6. Why `WEIGHT_DENSE=0.1` (not 0.5, not 0.0). Anchored on W11-I1 ablation evidence (`ablation_signal_drop.py` 403 LOC) + W18-D1 post-P0 re-ablation confirming the demotion still wins. Codifies "tag_overlap is mostly dead but kept as cheap dilutor guard" finding. Records the open tension that `mean_tag_p@5` is the same biased metric used to tune.
**Suggested #**: 0005. **Why first**: single highest-traffic subsystem; rationale currently fragmented across 4 docs; numeric weight is the kind of thing a future "let's clean this up" wave will revert without evidence in front of them.

### ADR 0006 — MLGG Seven Canonical Unchallengeable Rules
**What it covers**: Why exactly S01/P01/F01/F02/M01/E01/E02 are *unchallengeable* (cannot be downgraded by any reviewer, any context) when 26 other gates are configurable. Maps each to its TRIPOD+AI / PROBAST+AI clause. Defines the criteria for adding/removing a rule from this set (currently informal — `CLAUDE.md` just lists them).
**Suggested #**: 0006. **Why second**: these 7 are the *brand* of MLGG; the boundary between "unchallengeable" and "configurable" is the most consequential single design call in the repo, and right now it's a 7-row table with no justification.

### ADR 0007 — Disease KB Fail-Closed Triple
**What it covers**: Why `disease_kb` requires reviewer AND last_reviewed AND status-in-APPROVED (W11-F2, commit `04ad7d7`), not OR / not source-only. Records the W9-B1 vs W11-F2 history (B1 shipped fail-closed, F2 closed the OR-bypass). Documents the W17-C2 spoof-resistance verification.
**Suggested #**: 0007. **Why third**: security boundary; W11-F2 was a near-miss bypass; future "let's relax this for tests" pressure is predictable. ADR is the right shield.

### ADR 0008 — `workflow` vs `audit` Mode Split (and `--strict` tier semantics) [C6 + C7]
**What it covers**: Top-level CLI dichotomy. `workflow` = own-evidence path (requires MLGG-shaped `evidence/*.json`), `audit` = foreign-project scoring (code patterns + file structure, no noisy-fail on missing evidence). When `--strict` is required for "publication-grade" claims. Currently 3 lines in `SKILL.md` (Chinese); the entire UX hinges on a user picking the right one.
**Suggested #**: 0008. **Why fourth**: every user hits this on first use; misuse produces noisy failures that erode trust.

### ADR 0009 — Report Envelope v2.0.0 as Single Source of Truth
**What it covers**: `build_report_envelope` centralization in `_gate_framework.py:185`. Versioning policy (when to bump 2.x → 3.0, what additive vs breaking means). Why all 33 gates share one envelope rather than each defining its own. Anchored on W15-A2 schema audit.
**Suggested #**: 0009. **Why fifth**: cross-cutting contract; the next person to add a gate field will silently break consumers without a written contract.

## 4. Honorable mentions (write after the top 5)

- **C8** (percentile bootstrap not BCa): rationale exists inline; promote to ADR only if a reviewer asks.
- **C9** (Python gates vs Skill prompts split): partly covered by `SKILL.md`, but English-language ADR would help non-Chinese contributors.
- **C10/C11/C12**: low controversy; current docs are sufficient.

## 5. Verdict: **YELLOW**

- 4 ADRs exist; 3 of them are process, only 1.5 are product.
- The five highest-ROI product decisions (hybrid retrieval, canonical rules, KB triple, mode split, report envelope) are **all** undocumented as ADRs. Each lives in wave-retro narrative or inline code comments — durable but not discoverable, and not in a format that survives a future "let's simplify" refactor with the rationale attached.
- Not RED because the rationales *do* exist somewhere durable (retros, diagnostics, `ARCHITECTURE.md`). The risk is discoverability + format, not loss.

## 6. Wave-20+ recommendation

Write ADRs 0005, 0006, 0007 in the next wave (these 3 cover the highest-controversy, highest-traffic surfaces). Defer 0008 + 0009 to wave N+2. Each ADR should be ~150-300 lines and explicitly cite the wave + commit + diagnostic that produced the rationale, so it is *summarization* of existing material rather than fresh design — that bounds the effort.

Suggested order of authoring (smallest blast radius last):
1. ADR 0007 (disease KB triple) — narrowest scope, clearest single-commit anchor (`04ad7d7`)
2. ADR 0005 (hybrid 4-signal + weights) — largest doc gain
3. ADR 0006 (7 canonical rules) — most political; do third so 0005/0007 set the ADR-quality bar

## 7. Methodology + caveats

- Inspected: `docs/adr/000{1-4}.md`, `docs/ARCHITECTURE.md`, `docs/RAG_WAVE_1_TO_8_RETRO.md`, `docs/RAG_WAVE_9_TO_12_RETRO.md`, `docs/PROCESS_DEBT.md`, `CLAUDE.md`, `SKILL.md`, 50 diagnostics under `docs/diagnostics/`, recent 150 commits.
- Did NOT inspect: every gate source file (would have produced more candidates but at the cost of scope creep — the top-5 list is already large enough to action).
- A "candidate" was promoted to "ADR-shaped" only if the decision was both durable (will outlive 5+ waves) and load-bearing (changing it would break a contract or invalidate published results).
- This audit is itself the kind of artifact an ADR would replace: it lists decisions but does not bind them. Wave-N+ should write the ADRs, not extend this audit.
