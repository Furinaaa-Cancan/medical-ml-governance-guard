# W19-E5 SKILL.md + agents/ Integration Audit

**Scope** READ-ONLY claim-vs-code crosswalk for `SKILL.md`, `agents/*.yaml`, and the Claude Code integration surface (`.claude/commands/mlgg.md`). Date 2026-05-17. Repo head `6aec1e1`.

## SKILL.md shape

- `wc -l SKILL.md` = **290 lines** (matches CLAUDE.md "currently 290 lines" claim, within the "≤500" budget).
- Sections (h2/h3) = **13** (Architecture, Entry Points, Quick Dispatch with 7 sub-tables, Peer Review Evidence, Clinical Semantic Review with 6 sub-sections, 12-dim scoring, error recovery, profiles, scope boundary, Research mode fixes, deliverables, phase refs).
- Cross-link health: every `references/protocols/*.md`, `references/case-studies/peer-review-kb*`, `references/methodology/*.json`, and `scripts/reporting/*.py` referenced in SKILL.md **resolves on disk** (verified `quick_summary.py`, `compare_runs.py`, `remediation_plan.py`, `explain_gate.py`, `export_latex.py`, `generate_compliance_certificate.py`, `peer_review_lookup.py`, `score_paper_metadata.py`, `gate-framework-developer-guide.md`).

## Claim-vs-code: `mlgg <subcommand>`

SKILL.md line 23 + 34 advertises **"28 子命令"**. Counting the Quick Dispatch tables (main 5 + pipeline 4 + interactive 2 + env 3 + single-gate 2 + audit 6 + benchmark 6) = **28 documented**.

`python3 scripts/orchestration/mlgg.py --help` exposes **31 subcommands** (including the registry switches `flow` / `validate` injected at line 477 and `rag` registered at line 304).

| Bucket | Count |
|---|---|
| Claimed in SKILL Quick Dispatch | 28 |
| Wired in `scripts/orchestration/mlgg.py` | 31 |
| Vapor (SKILL → no code) | **0** |
| Orphan (code → not in SKILL) | **3** |

### Orphan subcommands (code-only)

| Subcommand | Status | Note |
|---|---|---|
| `flow` | wired (mlgg.py L477,L655) | Mentioned in prose at SKILL line 34 ("`mlgg flow` 显示推荐顺序") but absent from Quick Dispatch tables; users scanning the table miss the meta-helper. |
| `rag` | wired (mlgg.py L304 → `scripts/rag/query.py`) | **Material gap.** SKILL line 132 references RAG ("BM25 inactive in free-text mode; see README") yet never points to the `mlgg rag` query CLI. Discoverability deficit given Wave 18 D1–D5 RAG investment. |
| `validate` | wired (mlgg.py L477,L630) | Validates `configs/` against schema (errors with `[ERROR] No configs/ directory found` when absent). Zero SKILL coverage. |

### Vapor docs: none

Every Quick Dispatch entry resolves to a real subparser in `mlgg.py --help`.

## `agents/*.yaml` audit

- `agents/extractor.yaml`, `agents/reviewer.yaml`, `agents/README.md` only.
- **Model freshness**: both yamls pin `anthropic.model: claude-sonnet-4-5`, `google: gemini-2.0-flash`, `openai: gpt-4o`. Comments correctly note the undated alias strategy. `claude-sonnet-4-5` is a valid alias as of 2026-01 cutoff; no stale `claude-3-opus-20240229`-style snapshots. **OK**.
- **Code-path references**: `agents/README.md` references `mlgg lint`, `audit_external_project.py`, `generate_audit_report.py`, `scripts/reporting/export_review_prompt.py`, `.claude/commands/mlgg.md`. All five exist on disk.
- **Realistic inputs**: extractor → "Paper text (Methods section, 2000–5000 words)"; reviewer → "metadata.json (~80 fields)". Both align with `scripts/review/extract_paper_metadata.py` + `score_paper_metadata.py` actual contracts.
- **Stale references**: none detected. `claude-opus` model names do **not** appear in either yaml (avoiding the lifecycle risk called out in the comments).

## `.claude/commands/mlgg.md`

- 230 lines; named entry per SKILL line 10 ("/mlgg → 加载 `.claude/commands/mlgg.md` … ~200 行"). Real count 230 — close enough to "~200" to not be misleading.

## Docs-map gap (W11/W13/W14 cross-refs)

SKILL.md contains **0** references to `docs/diagnostics/W11_*`, `W13_*`, `W14_*`, or any wave-prefixed audit. README.md/README_EN.md contain ~10 such cross-refs (W11-I1, W11-F2, W11-M1, W13-P0, W13-G1/G2 ADRs, W14-D2 via ARCHITECTURE.md). Asymmetry: a Claude Code agent reading **only** SKILL.md sees a frozen view that misses Wave-11+ RAG architecture decisions, the `dense_weight=0.10` regression invariants, and the disease-KB pending-review caveat. The SKILL only nods at "BM25 inactive in free-text mode; see README" (line 132).

## Verdict: **YELLOW**

No vapor docs, all script-level references resolve, agent yamls are fresh. But three real gaps:
1. `rag` subcommand is the surfaced result of five Wave-18 audits yet invisible to SKILL-only readers.
2. `validate` and `flow` are functional helpers absent from Quick Dispatch.
3. Zero W11+ diagnostic cross-refs in SKILL — Claude Code agents who skip README miss the RAG/disease-KB caveats that the project has spent waves establishing.

These are documentation-completeness gaps, not safety failures, so YELLOW not RED.

## Wave-N+ recommendation (single highest-leverage fix)

**Add a "RAG & Knowledge Bases" sub-section to SKILL.md Quick Dispatch (~10 lines)** that:
- Lists `mlgg rag` with the canonical invocation (`mlgg rag "<query>" --gate <name> --top-k 5`) and the W18-D1..D5 caveat (dense demoted to 0.10 per W13-P0; BM25-dominant).
- Lists `mlgg validate` and promotes `mlgg flow` from inline prose into the table.
- Adds a one-line pointer "see `docs/diagnostics/W11_*` / `W18_*` for RAG provenance" so the SKILL stops being a frozen snapshot of pre-Wave-11 state.

Rationale per user memory `project_skill_ux_roadmap`: SKILL UX is on the user's mind, and the `rag` orphan is the single discovery gap that wastes the most prior-wave engineering investment.
