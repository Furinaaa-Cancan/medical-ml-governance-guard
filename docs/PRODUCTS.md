# MLGG — Two Product Lines

**Status**: Active naming convention as of W28-S0 (2026-05-17). Single-repo, single-CLI today; namespace split tracked as a follow-up in W28-S1/S2 (gated on user sign-off).

This file exists because MLGG is **two products under one CLI** with materially different success criteria, ground-truth sources, and metric systems. Conflating them produces the "33 gates audit any paper" framing that W25 + Amendment 2 had to retract.

## At a glance

| | **Governance line (Mode A)** | **Review line (Mode B/C)** |
|---|---|---|
| **What it does** | Acts as a guard on **your own** ML training pipeline; emits publication-grade compliance evidence | Audits **someone else's** code or paper; flags methodological gaps |
| **Inputs** | `configs/request.json` + your training data + your code → produces `evidence/*.json` artifacts | External repo path and/or paper PDF/text |
| **Layers used** | L1 lint + **L2 33 gate** + L3 RAG | L1 lint + L3 RAG (L2 = 0/264 on external repos per W25, structurally absent) |
| **CLI surface** | `mlgg workflow`, `mlgg strict`, `mlgg train`, `mlgg onboarding`, 14 others (see `COMMAND_GROUPS["governance"]`) | `mlgg audit`, `mlgg audit-report`, `mlgg audit-metrics`, `mlgg batch-review`, `mlgg export-review-prompt`, `mlgg lint`, `mlgg rag` |
| **Skill routing** | `/mlgg` (workflow / training intent) | `/mlgg` (audit / review intent), or `mlgg rag` directly |
| **Headline benchmark** | MLGG-Bench v1.0.2 (cp_hit@5 = 0.821 on 305 synthetic scenarios), authority E2E suites | W25 hybrid 8-paper external (macro hybrid recall 0.81 — informational, not citable), W27 N=1 external (planned, blocked on Quanjel critique) |
| **Headline metric** | TRIPOD+AI / PROBAST+AI compliance pass-rate, gate DAG green | Severity-weighted F1 against externally pre-registered reviewer concerns |
| **Ground-truth source** | Pipeline contract (you wrote the config; gates verify) | Real reviewer concerns (KB) + critique-derived claims (W27+) |
| **Citable today?** | ✅ MLGG-Bench numbers | 🟡 None yet (all priors self-graded; W27 N=1 is the first non-circular run) |
| **Refusal mode** | Refuses omics/imaging/text via R028 (R-rule) — narrow modality scope | Refuses if no code or no methods text — needs at least one signal |

## Why split

Three independent forces:

1. **Different success criteria.** Governance is binary (gates pass or fail). Review is graded (recall against critique, precision against over-flag).
2. **Different ground-truth sources.** Governance GT is the spec the user wrote themselves; review GT is what an external reviewer/critic would say. The W25-Amendment-2 finding (L2 = 0/264 on external repos) is structural, not a bug — L2 needs evidence the external repo never emits.
3. **Different drift risks.** Governance drifts when the gate code drifts away from the spec. Review drifts when the team relabels eval YAMLs to match what RAG happens to return (the label-drift anti-pattern flagged in W15-W19 retros and W27 deferral note).

Mixing them in one README produced the "33 gates audit external papers" overclaim that took W25 + Amendment 2 + Mode A/B/C routing to walk back.

## What W28-S0 changes (this commit)

Logical-only grouping; no CLI contract change, no file moves:

- `scripts/orchestration/mlgg.py` adds `COMMAND_GROUPS` + `COMMAND_GROUP_DESCRIPTIONS` constants. `mlgg --help` renders by group.
- `SKILL.md` Quick Dispatch reorganized under `[governance] / [review] / [benchmark] / [ops]` headers matching the constants.
- `tests/test_mlgg_command_groups.py` enforces every COMMANDS entry is placed in exactly one group; any future-added subcommand fails CI until grouped.
- This file (`docs/PRODUCTS.md`) — single source of truth for the two-line framing.

Every existing `mlgg <subcommand>` invocation continues to work byte-identically. Imports, dispatch, scripts — all unchanged.

## W28-S1 (landed — user-approved 2026-05-17)

- New console-script `mlgg-review` in `pyproject.toml` as a thin shim that whitelists the 7 review commands. `mlgg` still ships all 28 (full back-compat).
- Implemented as `scripts.orchestration.mlgg.review_cli_main()` — argv-gating only, delegates to the same `main()` that `mlgg` calls. No dispatch duplication.
- `mlgg-review <governance-cmd>` exits 2 with a clear pointer back to `mlgg`. `mlgg-review --help` lists only review commands.
- Tests: `tests/test_mlgg_review_shim.py` covers every allow-listed review command (parametrized) and the rejection / help / no-arg paths (15 cases).
- User-visible: after `pip install -e .`, `mlgg-review audit X` works byte-identical to `mlgg audit X`. Governance commands give a focused error rather than a wall of irrelevant options.

## What W28-S2 might change (later, larger scope)

- Physical move: 7 review-line scripts and the `scripts/rag/` subtree into a separate Python package `plugin/mlgg_review/`.
- Two pip distributions: `ml-governance-guard` and `mlgg-review`. Both depend on `mlgg-lint`.
- Rationale: lets a review-only deployment skip ~40K LOC of gate code; lets the W27 N=1 + future external-paper work iterate without churning the governance test surface.
- Blocked by: scope, and W28-S1 needs to land first.

## Cross-refs

- `SKILL.md` §Audit Routing — Mode A/B/C
- `README.md` 三层结构 适用范围 (CN), `README_EN.md` Three layers > Scope (EN)
- `references/benchmark/hybrid_v1_spec.md` §Amendment 2
- `docs/diagnostics/W25_hybrid_aggregate.md`
- `docs/diagnostics/W27_external_n1_plan.md`
- `docs/diagnostics/W27_user_action_deferral.md`
- `scripts/orchestration/mlgg.py` `COMMAND_GROUPS`
