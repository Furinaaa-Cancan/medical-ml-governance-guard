# W19-E1 — CI Workflow Audit: Claims vs Reality

**Scope.** `.github/workflows/*.yml` ↔ `.githooks/pre-push` ↔ `.pre-commit-config.yaml` ↔ README CN/EN "CI/CD" section. READ-ONLY.

## Inventory

| Workflow | Trigger | Matrix | Timeout | Jobs | Steps | `continue-on-error` |
|---|---|---|---|---|---|---|
| ci-unit | push(main, claude/**) / PR / dispatch | 3.10 / 3.11 / 3.12 | 20 m | 1 | 4 | 0 |
| ci-security | push(main, claude/**) / PR / dispatch | 3.10 / 3.11 / 3.12 | 10 m | 1 | 9 | 0 |
| ci-full | cron `0 3 * * *` / dispatch | 3.11 | 360 m | 1 | 7 | **2** |
| ci-extended | cron `0 4 * * 0` / dispatch | 3.11 | 480 m | 1 | 5 | **1 (sole substantive step)** |
| ci-overnight | cron `0 22 * * *` / dispatch | 3.10 / 3.11 / 3.12 | 360 m | 1 | 4 | 0 |

Totals: **5 workflows / 5 jobs / ~29 steps / 3 silent-skip steps**. Required-vs-soft mix is healthy on the push-path workflows (ci-unit + ci-security: 0 `continue-on-error`); soft steps cluster in cron workflows where third-party data is the excuse.

## README claim vs reality

| README claim | Reality | Verdict |
|---|---|---|
| ci-security timeout = **30 min** (CN line 1845 / EN line 1519) | `timeout-minutes: 10` | **LIE** (over-stated by 3×) |
| ci-extended tree comment = **"扩展测试 (30-45 min)" / "(30-45 min)"** (tree line 1630 / 1311) | `timeout-minutes: 480` (8 h) | **LIE** (under-stated by 10×) |
| ci-overnight tree = **"权威基准 + 压力测试" / "Authority benchmarks + stress tests"** (line 1632 / 1313) | `pytest -m "slow"` only — no benchmark suite is invoked | **MISLEADING** (it's the slow-test sweep, not authority benchmarks) |
| README CN/EN CI/CD table lists **4 pipelines** | 5 workflows exist | **OMISSION** (ci-overnight absent from the table) |
| "Same rule set as CI" for pre-commit (CN 1701 / EN 1375) | pre-commit has 4 hooks (docs-consistency, ukb-codebook, stderr-routing, kb-hygiene) with **no CI mirror**. `--no-verify` permanently bypasses these | **PARTIAL** (CI is a strict subset, not the same set) |

## Hook ↔ CI drift

| Check | pre-commit | pre-push | CI |
|---|---|---|---|
| ruff `scripts/` | yes | yes | yes (ci-unit) |
| `check_readme_stats.py` | yes (always_run) | yes | **no** |
| mlgg-lint self-check | yes | no | yes (ci-unit) |
| `check_docs_consistency.py` | yes | no | **no** |
| `kb_hygiene_check.py` | yes (KB files) | no | yes (ci-full only — nightly) |
| `verify_ukb_codebook.py` | yes | no | **no** |
| `lint_stderr_routing.py` | yes (always_run) | no | **no** |
| RAG smoke import | no | yes | no |
| pytest smoke slice (5 files, W14 `6be18e4`) | no | yes | (full superset in ci-unit) |
| ci-security 5 pytest files | no | **no** | yes |
| `--cov-fail-under=40` | no | no | yes (ci-unit only) |

**Net.** `--no-verify` on push permanently bypasses 4 checks (docs-consistency, ukb-codebook, stderr-routing, readme-stats) — none is mirrored server-side. Per-commit drift is silent.

## Silent-skip top 5

1. **ci-extended "Extended benchmark suite"** — `continue-on-error: true` on the *only* substantive step. The workflow burns 480 m of GH Actions budget every Sunday and cannot fail. Comment justifies it (UCI / Diabetes-130 raw data not committed); README does not warn readers.
2. **ci-full "Release benchmark suite"** — same shape, same justification, same invisibility to README readers.
3. **ci-full "Full onboarding (guided demo)"** — `continue-on-error: true` because 33 gates predictably fail on 150-row synthetic demo data. Effectively a crash-only canary.
4. **ci-unit `--ignore=tests/test_onboarding_smoke.py`, `--ignore=tests/test_play_smoke.py`** — silently dropped from PR signal. ci-overnight does *not* add the same ignores, so these run nightly only; PR can ship a broken smoke and merge.
5. **pre-commit-only checks bypassed by `--no-verify`** (see drift table) — never re-validated by CI. The "PRs fail before merge" claim (README CN line 89, EN line 85) holds only for `check_readme_stats.py` (covered by pre-push) and `docs-consistency` is *not* enforced at all server-side.

## Coverage threshold history

| Date | `--cov-fail-under` | Source |
|---|---|---|
| pre-2026-05-13 | **45** | W13-A0 task reference + ci-unit.yml comment |
| 2026-05-13 | **40** | ci-unit.yml:58-61 comment ("corpus-expansion wave 11a6f9a … f7e4dbf dragged overall to ~43%") |
| 2026-05-17 (today) | **40** | unchanged |

No ratchet-up mechanism. No issue/TODO tracking the raise. ci-overnight + ci-security do **not** measure coverage, so the only gate on regression is a single line in ci-unit. Threshold dropped to keep CI green; the gap has not narrowed in 4 days.

## Verdict: **YELLOW**

Gates that fire are still deterministic and the push-path workflows (ci-unit + ci-security) are clean. The drift is in (a) README reporting honesty — wrong timeouts, missing ci-overnight, "authority benchmarks" that aren't, (b) coverage threshold ratcheted *down* with no plan to restore, (c) three cron `continue-on-error` steps that ensure two of the five workflows cannot fail. Not RED because the matrix that runs catches what it claims to catch; YELLOW because the surface area presented to readers / contributors overstates coverage.

## Wave-N+ fix candidates

1. **README CN/EN CI/CD table fix.** Correct ci-security `30 m → 10 m`; add ci-overnight row; remove "(30-45 min)" tree comments for ci-extended (real 480 m); change ci-overnight description from "Authority benchmarks + stress tests" to "Slow-marked pytest sweep across py 3.10/3.11/3.12".
2. **Coverage ratchet.** Pin `--cov-fail-under` in a single file; assert monotone-non-decreasing across commits; require a paired ratchet-up commit when a wave closes a gap. Cheap, prevents the 45 → 40 drift from repeating.
3. **Adopt H17 ci-drift gate** into ci-security as a server-side mirror of pre-commit `always_run` hooks (docs-consistency, stderr-routing, ukb-codebook, readme-stats). Closes the `--no-verify` bypass loophole.
4. **ci-extended decision.** Either wire `examples/download_real_data.py` into a `Prepare benchmark data` step (slow, flaky on upstream outages) or downgrade ci-extended to `workflow_dispatch` only and stop burning 480 m / week on a no-op.
5. **Smoke file inclusion.** Either remove `--ignore=test_onboarding_smoke.py` + `--ignore=test_play_smoke.py` from ci-unit (smoke should be the *first* PR signal), or split smoke into a fast required job so PRs see status.
6. **Pre-push smoke widening.** Add the 5 ci-security pytest files to the pre-push smoke list — all <30 s, security is the most-pushed surface, cheap insurance against landing red on the most-watched workflow.
