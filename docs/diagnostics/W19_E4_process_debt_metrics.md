# W19-E4 — PROCESS_DEBT.md PD-01~04 Quantitative Metrics

**Date**: 2026-05-17  **Wave**: 19 strict-review (FINAL)  **Mode**: READ-ONLY
**Inputs**: `docs/PROCESS_DEBT.md`, `git stash list`, `git log --all` (1390 commits), `docs/diagnostics/W{10..18}_*.md`, `docs/RAG_WAVE_9_TO_12_RETRO.md`.
**Raw metrics**: `/tmp/W19_E4_metrics.json`.

## PD-01: stash-as-concurrency-primitive

| Window | Stash count | Net change |
|---|---|---|
| Pre-W13-C0 peak | 8 | — |
| After W13-C0 cleanup | 1 (7 dropped, 1 preserved) | -7 |
| Current (post-W14) | **6** | **+5 in ~1 day** |

Five new stashes created **after** ADR 0002 landed: `W13-P0`, `W14-R0` (x2), `W14-F2`, `W14-F3`. ADR 0004 (worktrees-default) landed at `f191481` but no agent has yet operated in a worktree per stash messages. **Verdict: RED**.

## PD-02: sibling-fix-forward churn

| Label | Count |
|---|---|
| `fix(ci):` | 13 |
| `fix(tests):` | 7 |
| `fix(hook):` | 1 |
| `drift fix` | 2 |
| Explicit "unbreaker" tag | 4 |
| **Combined unique** | **21** |

Pre-W13-C0: 21 unbreaker commits / 1348 = **1.56 /100 commits**.
Post-W13-C0: 5 unbreaker commits / 41 = **12.20 /100 commits** (caveat: small denominator).
Rate is **~8x worse** post-fix; absolute count is flat because total commit volume dropped. **Verdict: RED** (rate trend) / YELLOW (absolute trend).

## PD-03: virtual-wave inflation

| Wave | Reported | Committed | Virtual % |
|---|---:|---:|---:|
| W10 | 10 | 1 | **90 %** (canonical) |
| W11 | 10 | 8 | 20 % |
| W12-W14 | n/a | 7-9 | ~0 % |
| W15-W18 | 5 | 5 | **0 %** |

Mandatory `docs/diagnostics/W<NN>_*` artifact per audit (introduced de-facto W15) closed this PD. **Verdict: GREEN**.

## PD-04: ghost regression / re-find

| Re-find | Origin | Δ |
|---|---|---|
| W17-C4 scenarios overlap | W9-C1 | 2/27 → 2/26 — **unchanged 8 waves later** |
| W17-C5 eval-set staleness | W14-F1 | 1 case → 27/48 (56 %) RED |

W17 strict-review re-find rate: **2/5 audits = 40 %**. No closing PR was filed for W9-C1 (scenarios.json codes still synthetic). **Verdict: RED**.

## Trend — are W13/W14 process-fix waves working?

| PD | Pre-fix | Post-fix | Trend |
|---|---|---|---|
| PD-01 | 8 peak | 6 (and rising) | RED |
| PD-02 | 1.56/100 | 12.20/100 | RED |
| PD-03 | 90 % (W10) | 0 % (W15+) | GREEN |
| PD-04 | named W11-S1 | 2 re-finds in W17 | RED |

Process-control fixes (ADR 0002, 0004) **have not measurably reduced PD-01/PD-02**; artifact-mandate fix **has eliminated PD-03**.

## Verdict: **RED** (3/4 PDs trending flat-or-up despite documented mitigations)

## Wave-N+ recommendation: hardest intervention needed on PD-02

PD-01 is correctable by mechanical worktree enforcement (ADR 0004 already authored — just needs adoption hook). PD-04 is a re-dispatch discipline problem (W17-C4/C5 should have produced fix-wave inputs, not been re-audited). **PD-02 is structural**: `.githooks/pre-push` runs tree-wide ruff against any sibling's red. The PD-02 entry already proposes `--changed-only` scoping; W19-N+ should land that hook patch, otherwise every concurrent-session wave will keep paying the unbreaker tax that consumed ~10 % of the project's recent commit budget.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
