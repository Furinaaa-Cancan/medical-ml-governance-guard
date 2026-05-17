# W14 RAG Audit — Sub-Agent Report Index

**Date**: 2026-05-17
**Scope**: `scripts/rag/` production RAG + KBs + eval + reporting + gates
**Method**: 10 parallel audit agents (A–J); cross-validated where overlapping
**Reviewer role**: per `CLAUDE.md` — Nature Methods / JAMA-level

## Canonical record

**This INDEX is intentionally minimal — a file map only.** The canonical
audit narrative (findings, retractions, commit SHAs, owner-decision items,
self-review of the audit itself) lives in `CHANGELOG.md`'s
**`[Unreleased]` → `2026-05-17 session — W14 RAG audit`** block.

Two-source-of-truth was R5 of the W14 self-review (commit `e9a5d2b` and
prior). INDEX previously duplicated the CHANGELOG mapping; it is now
de-duplicated to point at CHANGELOG instead. **Update CHANGELOG, not this
file**, for any new audit findings or resolution updates.

## Sub-agent reports (file map)

| Agent | Focus | Report |
|---|---|---|
| A | Dense-only ablation on production hybrid | [audit_agent_A_ablation.md](audit_agent_A_ablation.md) |
| B | L27 preprocessing-leak retrieval reproduction | [audit_agent_B_leak_repro.md](audit_agent_B_leak_repro.md) |
| C | KB gate-tag completeness draft (M5+m4) | [audit_agent_C_kb_tags.md](audit_agent_C_kb_tags.md) |
| D | `entries[:20]` sort-before-truncate fix | [audit_agent_D_sort_fix.md](audit_agent_D_sort_fix.md) |
| E | M1 "human-labeled" description correction | [audit_agent_E_desc.md](audit_agent_E_desc.md) |
| F | `bm25.py:271` `[:5]` truncation forensics | [audit_agent_F_bm25_trunc.md](audit_agent_F_bm25_trunc.md) |
| G | Hybrid fusion-weight grid search | [audit_agent_G_hybrid_grid.md](audit_agent_G_hybrid_grid.md) |
| H | `peer-review-kb.json` schema validation (335 entries) | [audit_agent_H_schema.md](audit_agent_H_schema.md) |
| I | Zero-support gates deep-dive | [audit_agent_I_zero_support.md](audit_agent_I_zero_support.md) |
| J | Synthesis prep — current-state inventory | [audit_agent_J_current_state.md](audit_agent_J_current_state.md) |

## Provenance

All 10 reports produced by parallel Claude Opus 4.7 (1M context) sub-agents
on 2026-05-17 between 12:22 and 12:36 local time. Reports are pinned
snapshots; cite this directory rather than re-deriving when referencing
specific agent findings.
