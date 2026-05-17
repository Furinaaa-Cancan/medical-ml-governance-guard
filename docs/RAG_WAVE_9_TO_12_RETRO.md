# RAG Layer: Wave 9-12 Retrospective (2026-05-17)

**Status**: frozen retrospective snapshot. Do not edit chronology after
Wave 12 closeout.
**Authority**: W13-D0, continuing from `RAG_WAVE_1_TO_8_RETRO.md` (W9-D1).
**Scope**: the four waves that followed Wave 8's closeout — W9
foundation expansion, W10 read-only audit, W11 fix wave, W12 doc
restructure — through the eve of W13's dense-weight rebalance.
**Audience**: future-you trying to understand *why* the RAG layer's
`dense_weight` was demoted in W13-P0, *why* the disease KB now
fail-closes on a 3-field AND, and *why* the docs grew a
`docs/reference/` directory of 5 long-form references.

## TL;DR

- **Headline finding (W11-I1)**: 7 waves (W1-W7) of RAG optimization
  may have been against the wrong target. The dense signal at
  `WEIGHT_DENSE=0.5` is a *dilutor* — removing it beats production
  hybrid by +0.094 `mean_tag_p@5` (0.447 vs 0.353) and beats
  `bm25_only` by +0.011 (0.447 vs 0.436). The fix-forward is W13-P0
  (commit `cc3c717`), which demoted `WEIGHT_DENSE` 0.5 → 0.1 and
  rebalanced. ADR-0001 is the related architectural decision for the
  `_mmr_breakdown` field; the dense-weight decision itself lives in
  W11-I1's ablation harness output + W13-P0's commit message.
- **W10 was a deliberate audit wave** — 10 agents, READ-ONLY, no
  shipped code (except R0's ruff cleanup). Three independent agents
  converged on the same meta-finding: ~25% of the accumulated backlog
  was against phantom problems.
- **W11 was the smallest-Δ wave with the largest blast radius**.
  10 commits: 5 fixes (F1-F5) directly traceable to W10 findings, 2
  investigations (I1 ablation + I2 ADR), 1 maintenance pass (M1+M2),
  and 1 unbreaker (R0). I1's ablation harness alone reframes
  W1-W8's optimization story.
- **W12 was the first user-facing doc restructure since the README's
  birth**. ToC flattened from 25 items into 4 grouped sections;
  `docs/reference/` directory born with 5 authoritative references
  (GATES, LINT_RULES, DATASETS, MODEL_FAMILIES, ANALYSIS_TOOLS); a new
  "文档地图" table maps every markdown in the repo to its audience.
  B1 flagged the auto-gen drift problem (GATES.md hand-curated from
  `_gate_registry.py`) which is now a W13+ open question.

## Wave timeline

### Wave 9 (A1-D3): foundation expansion (~15 commits)

The largest wave since W2 by commit count. Three tracks landed in
parallel: an evals-quality track (A1+A2+C1+C2), a corroboration +
fail-closed track (B1+B2), and a developer-experience + lint track
(D1+D2+D3).

| Agent | Commit  | Shipped                                                                 |
|-------|---------|-------------------------------------------------------------------------|
| W9-A2 | `4d42306` | Extended labeled P@5 set from 20 → 36 queries.                          |
| W9-B1 | `041c663` | `publication_gate` fail-closes on unreviewed disease KB entries.        |
| W9-B2 | `d1f5467` | Within-CP dense corroboration + `_mmr_breakdown` audit dict.            |
| W9-B2 fu | `57c9047` | Ruff F401 in the new test file.                                       |
| W9-C1 | `9678f1e` | `validate_gate_code_alignment.py` cross-checks eval vs harvested codes. |
| W9-C2 | `d3a7e67` | `run_eval.py --diff` for per-scenario delta vs baseline.                |
| W9-D1 | `3238466` | Split Wave-1-to-8 narrative into `ARCHITECTURE.md` + the W1-W8 retro.   |
| W9-D2 | `2ad1b28` | `lint_kb_tags.py` WARN-only KB tag vocab lint (1770 singletons surfaced). |
| W9-D2 (style) | `61b2ed4` | Drop unused f-string prefix on 2 print statements.               |
| W9-D3 | `fb9aee5` | Contributor hook activation guide + `setup-dev.sh`.                     |
| W9-D2 docs | `262cee3` | Bump README diagnostics (29→31) + tests (154→156).                |
| W1 (W9 deep-int) | `a8d9abf` | Rename `post_wave5_baseline` → `post_wave7_baseline`.             |
| W9 race recovery | `f8ad6cd` | Restore `RAG_WAVE_1_TO_7_OVERVIEW.md` accidentally deleted in a8d9abf. |
| W9 sync | `e8f1af9` | Tests count 156→158 (parallel sessions added 1).                        |

**Notable**: W9-B2 self-flagged that `_mmr_breakdown` was a contract
without a consumer ("the breakdown is a contract; it needs a consumer
or it is just memory pressure with extra steps"). That flag matured
into W10-R1's dormancy finding and W11-I2's SHIP-via-`--explain` ADR.
W9-B2 also did the responsible thing on its own A/B: dense
corroboration tied on `hit@K` but lost 0.077 on `tag_p@K`, so it
shipped the framework but defaulted the flag to False — the
optimization-against-tag-proxy anti-pattern below is in the same
neighborhood but distinct.

### Wave 10 (R0-S1, T1-T4): audit wave — what was actually true? (READ-ONLY)

10 agents dispatched as a deliberate audit pause. Mandate: question
the premise of every pending backlog item. No code ships except
unavoidable CI unbreakers. Most output lived under `/tmp/W10*` and was
distilled into W11 fix-wave inputs.

| Agent  | Finding (one line)                                                                                          | Acted on by |
|--------|-------------------------------------------------------------------------------------------------------------|-------------|
| W10-R0 | `ruff` red on 3 stray f-prefix tokens; unblocking ship to keep ci-unit green (only W10 commit: `2603578`).  | self        |
| W10-R1 | `_mmr_breakdown` is write-only at HEAD; only readers are unit tests. Either SHIP a consumer or CUT.         | W11-I2      |
| W10-R2 | `classify_disease()` returns True if `source OR clinician_review_status` is approved — `OR` truthiness bypass. | W11-F2   |
| W10-R3 | `lint_kb_tags.py --baseline-mode` silently no-ops on missing file → false-green CI.                          | W11-F4      |
| W10-R4 | `run_eval.py --diff` silently exits 0 on missing baseline; `baseline_by_id` hard-subscripts `r["id"]`.       | W11-F5      |
| W10-T1 | Local nondeterminism of `run_eval.py` measured at **std=0** across N=10 reruns (macOS-CPU). Backlog item is phantom on a single machine. | ARCHITECTURE Q5 |
| W10-T2 | `--mode hybrid` is net-negative vs `--mode bm25_only`: mean_tag_p@5 0.353 vs 0.436 (−0.083) on `scenarios.json`. | W11-I1   |
| W10-T3 | (audit-only, rolled into T2's narrative)                                                                    | W11-I1      |
| W10-T4 | (audit-only, rolled into T2's narrative)                                                                    | W11-I1      |
| W10-S1 | "166 ruff red" alarm in W9 hand-off notes is a PHANTOM. `.githooks/pre-push` passes `tests/` explicitly, overriding `ruff.toml`'s exclude. Real count: 2. | W11-F1 |

The three colliding meta-findings — S1 phantom ruff, T2 hybrid net
negative, T1 std=0 — are the spine of the "optimizing wrong target"
meta-conclusion below.

### Wave 11 (F1-F5, I1-I2, M1-M2, R0): fix wave (10 commits)

Each W11 commit is traceable to a specific W10 finding. Wave 11 is
the cleanest one-to-one fix-wave in the project's history.

| Agent  | Commit    | Fix (one line)                                                                                                     | W10 source |
|--------|-----------|--------------------------------------------------------------------------------------------------------------------|------------|
| W11-F1 | `b553612` | Align pre-push ruff scope with CI; clear 2 F841 dead vars.                                                          | W10-S1     |
| W11-F2 | `04ad7d7` | `disease_kb` requires reviewer + last_reviewed + status (AND of 3 fields, no `OR` source-only bypass).              | W10-R2     |
| W11-F3 | `f7c1a31` | `_mmr_rerank` passthrough emits same `_mmr_score` / `_mmr_breakdown` schema + `blocker_id` non-None invariant.       | W10-R1 sibling |
| W11-F4 | `4ca2e4f` | `--baseline-mode` errors on missing file; ship initial baseline (1815 known-legacy violations).                     | W10-R3     |
| W11-F5 | `fcde7ee` | `run_eval.py --diff-required` flag; `scenario_id` alias; baseline aggregate echo.                                   | W10-R4     |
| W11-I1 | `b1e9c8d` | **Signal-ablation diagnostic** — 6 configs (bm25_only, hybrid_all, hybrid_no_{dense,bm25,tag,severity,mmr}). Localizes the dilutor: **dense at 0.5 is the cause**. hybrid_no_dense recovers to 0.447 vs hybrid_all 0.353. | W10-T2 |
| W11-I2 | `0de6235` | ADR-0001 + SHIP `_mmr_breakdown` via `mlgg rag --explain` flag.                                                     | W10-R1     |
| W11-M1 | `a74ff22` | W10 findings postscript + ARCHITECTURE Q5 + RAG_TROUBLESHOOTING §9 ("Hybrid scores worse than BM25 alone").         | W10-T1+T2  |
| W11-M2 | `e83d673` | Bump tests count 158→160 (drift catch from I1+F5 new tests).                                                        | drift sync |

W11-I1's ablation harness is the load-bearing artifact: it ships
`scripts/rag/evals/ablation_signal_drop.py` (403 LOC), monkey-patches
the config weights between runs, rebalances remaining weights to
sum=1.0 so absolute scores stay comparable, and triggers the
`lam >= 1.0` passthrough branch (which is exactly why W11-F3's
passthrough schema-parity fix landed at the same time — without F3,
I1's ablation crashed on the passthrough branch).

### Wave 12 (A1-A2, B1-B5): README restructure + docs/reference birth (7 commits)

Wave 12 was a doc-only wave. No code, no tests, no gates — but the
biggest user-facing change since the README's Wave-2026-05-13 honest
split (`c626881`).

| Agent  | Commit    | Shipped                                                                                                            |
|--------|-----------|--------------------------------------------------------------------------------------------------------------------|
| W12-A1 | `1b6d658` | README ToC flattened 25-item list → 4 grouped sections (概览 / 上手 / Reference / 设计+工程); 9-phase TL;DR table; W10/W11 fact updates; 文档地图 (11-row markdown-audience map). |
| W12-A2 | `5cc0c6a` | `README_EN.md` rewritten to ~500 lines, links out to `docs/reference/*.md` instead of duplicating; W10/W11 fact updates. |
| W12-B1 | `7f2ba2c` | `docs/reference/GATES.md` (387 lines) — 33 gates, sources of truth, full rule-to-gate mapping (C01-Q02), CLI contract. |
| W12-B2 | `9e6ca64` | `docs/reference/LINT_RULES.md` (387 lines) — 28 R001-R028 AST rules with bad/good code examples.                   |
| W12-B3 | `dc358bd` | `docs/reference/DATASETS.md` (227 lines) — 16 medical datasets + leakage traps + tier rollup.                       |
| W12-B4 | `0bf5bcd` | `docs/reference/MODEL_FAMILIES.md` (425 lines) — 23 families + calibration + leakage modes.                         |
| W12-B5 | `536b445` | `docs/reference/ANALYSIS_TOOLS.md` (392 lines) — 21 standalone scripts + 4 flagged follow-ups (subgroup_dca, model_card, drift, no-CLI). |

W12-B1's most useful finding (buried in the commit message) is that
GATES.md was hand-curated from `scripts/core/_gate_registry.py`, which
makes it the start of an *auto-gen-drift* problem: any future gate
addition has to be reflected in GATES.md by hand, and the README_EN
layer mismatch for `ci_matrix_gate` / `metric_consistency_gate` was
already discovered during B1's curation. The fix-forward (auto-gen
`GATES.md` from the registry with a `_gates_md_preamble.md` hand-edit
section) is a W13+ open question.

W12-A2's English README rewrite was the second-largest single
documentation diff in the project's history (−194/+56 lines net).
The compression came from delegating reference material to
`docs/reference/*.md` instead of inlining it in the README.

## Anti-patterns (new in W9-W12, supplements D1's 5)

### Anti-pattern 6: ghost configuration debt

W11-S1 found that the "166 ruff red" wall referenced in W9 hand-off
notes was 2 real violations + a configuration override. The
`.githooks/pre-push` hook passed `tests/` to ruff explicitly,
overriding `ruff.toml`'s `exclude = ["tests/"]` directive. Four W9
agents (independently) treated the wall as ground truth and adjusted
their dispatch around it; W11-F1 fixed it in 4 lines (`b553612`,
.githooks/pre-push diff). **Lesson**: when many agents independently
hit the same friction, suspect configuration before code. The
diagnostic cost of one agent reading the hook script is two orders of
magnitude cheaper than four agents working around a phantom wall.

### Anti-pattern 7: dormant audit fields

W9-B2 added `_mmr_breakdown` ("for future audit consumers"). W10-R1
confirmed it was write-only at HEAD — only readers were the unit
tests that asserted on its shape. The field was paid for (one dict
allocation per picked candidate × top_k) on every query and yielded
zero user-visible value. W11-I2 had to write ADR-0001 and SHIP via
`--explain` to give the field a real consumer; the alternative was
removing the field entirely. **Lesson**: don't add data structures
without a concrete consumer in the same PR. The "future audit
consumer" rationale is plausible only when paired with a named near-
term caller. If no caller is named, write the data to `stderr` behind
a flag or do not write it at all.

### Anti-pattern 8: provenance spoofing via `OR` truthiness

W10-R2 found that `classify_disease()` returned `True` if EITHER
`provenance.source` OR `clinician_review_status` was in
`APPROVED_STATUSES`. A one-line JSON edit (`"source": "approved"`)
bypassed the entire `publication_gate` fail-closed check that W9-B1
had shipped one day earlier (`041c663`). W11-F2 (`04ad7d7`) tightened
the contract to AND of three independent fields — non-empty
`reviewer`, non-empty `last_reviewed`, status in `APPROVED_STATUSES`.
**Lesson**: any "approved" determination must AND on multiple
independent provenance signals. A single field that an attacker (or
careless contributor) can set without binding to a named reviewer or
review date is not a provenance signal — it is a comment.

### Anti-pattern 9: optimization-against-tag-proxy

W11-I1's ablation finding is in tension with the optimization
narrative of W1-W7. The metric optimized across most of those waves
(`mean_tag_precision@5`) was *already* flagged by W9-A2 / W7-P4 as a
biased proxy that penalizes the MMR diversification we explicitly
want (cf. W1-W8 anti-pattern #3, "measurement-system mismatch").
W11-I1 ran the ablation on the same biased metric — and got the most
load-bearing finding in the wave from it. **Lesson**: when an
optimization metric is known-biased, the wins probably aren't real.
But also: when an *ablation against the same biased metric* shows
that a signal is *diluting* even by the proxy's own measure, that's
extra-credible evidence the signal is broken in the real world too.
The labeled `hit@K` set was expanded 20 → 36 in W9-A2 specifically to
escape this trap; the dense-weight demotion in W13-P0 needs
re-validation against `hit@K` on the expanded set before being called
final.

### #10 (relocated)

See PROCESS_DEBT.md PD-01. Cross-cutting project debt, not a RAG-layer pattern.

## Meta-conclusion: the "optimizing wrong target" pattern

Three independent W10 agents converged on the same diagnosis from
three different angles:

- **W10-S1**: "166 violations" was 2 violations + hook
  misconfiguration. The cost of accepting the alarm at face value was
  4 agent-waves of avoidance.
- **W10-T2 → W11-I1**: the hybrid ranker was a net-loss vs
  `bm25_only`; the `dense` signal at weight 0.5 was the dilutor.
  Seven waves of optimization had been against a metric that the
  signal-under-optimization was *eroding*.
- **W10-T1**: "baseline instability" was std=0 across N=10 reruns on
  macOS-CPU. The backlog item was a phantom on the only platform
  anyone was actually running on.

Pattern: roughly 25% of accumulated backlog items by mid-W9 were
against PHANTOM problems. The cost of NOT pausing to audit was
substantial — W1-W7 optimized `dense + bm25 + tag + severity` tuning
with all four weights nonzero, when the right action (revealed by
the W11-I1 ablation in 1 day of work) was to demote one weight
five-fold and rebalance the other three.

**Recommendation for future waves**: every 3-5 fix waves, run a
1-wave audit. Read-only. Question the premise of each pending
backlog item. Kill phantoms before they become decade-debt. W10's
10-agent dispatch shape (R-track for code audits, T-track for
metric/measurement audits, S-track for tooling/hook audits) is the
template to reuse.

## Process debt timeline (race incidents)

- **W9-C3 race-deletion** (`fb9aee5` restoration of `RAG_WAVE_1_TO_7_OVERVIEW.md`):
  sibling session deleted a file that another agent was about to
  commit. Recovery: `git checkout` from previous SHA. Confirms
  W1-W8 anti-pattern #5 ("`git commit -o` is not race-safe") is
  still alive at W9 dispatch densities.
- **W11-F2 / F3 / F4 / I2 stash incidents**: 4 stashes created in one
  wave (`w11-m1-temp-docs`, `W11-I2 stash`, `W11-I2 stash 2`,
  `W11-F4 stash unrelated pre-push hook change`) as agents tried to
  isolate their own changes from sibling-in-progress files. None
  dropped after the session.
- **W12 stash chaos** (less visible because all-doc): 0 net stashes
  added because B1-B5 each wrote in a fresh file under
  `docs/reference/`, eliminating cross-agent file contention by
  design. A2 had to merge against A1's README edits but did so with a
  clean `git pull --rebase` instead of a stash. This is the right
  pattern.
- **W13-C0 cleanup + ADR-0002**: in flight. Cleanup pass drops the
  accumulated 8 dead stashes; ADR-0002 will codify a race-proof
  commit protocol (stash → pop → drop; explicit file ownership in
  orchestrator dispatch; race-deletion repro requires `git reflog`).

## W13+ open questions

- **W13-P0 dense-weight rebalance** (commit `cc3c717`, in flight):
  shipped `WEIGHT_DENSE` 0.5 → 0.1 with W11-I1 ablation as
  justification. Needs re-validation against `hit@K` on the labeled
  36-query set (W9-A2's expanded baseline) before being called final.
  If `hit@K` shows regression (i.e. tag_p@5 went up because we lost
  paraphrase recall the labeled set captures), W13 may need to
  REVERT or partially-revert. Test
  `tests/test_rag_config.py::test_dense_weight_demoted_per_w11_i1`
  pins the demotion as a regression guard.
- **Auto-gen `GATES.md`** (W12-B1 flagged): hand-curated from
  `scripts/core/_gate_registry.py` today. Need an auto-gen script
  with a `_gates_md_preamble.md` hand-edit section so the registry is
  the single source of truth and the doc cannot drift. README_EN
  already exposed one mismatch (`ci_matrix_gate`,
  `metric_consistency_gate` layer) caught during B1's curation.
- **4 unused-tools follow-ups** (W12-B5):
  - `subgroup_dca` not wired into `fairness_equity_gate`
  - `generate_model_card` not wired into `publication_gate`
  - `temporal_drift_analysis` has no gate consumer
  - No CLI surface for any of the 21 ANALYSIS_TOOLS callables (the
    earlier "python3 scripts/analysis/<tool>.py --help" framing was
    aspirational and never shipped)
- **ADR-0002 race-proof commit protocol** (W13+): codify the stash
  → pop → drop cycle, the explicit file ownership in orchestrator
  dispatch, and the W9-C3 race-deletion repro recipe.
- **Disease KB clinical review** (W11-F2 enforces the gate; the data
  still needs review): all 11 entries are `status=pending` with no
  named reviewer and no per-disease guideline citation. The fail-
  closed gate now refuses publication-grade claims; the underlying
  KB needs clinical SME review before the gate can pass without the
  `--allow-unreviewed-disease-kb` override.

## Commit timeline (~30 entries, chronological, grouped by wave)

```
Wave 9 — A1-D3 + W1 deep-int (~15 commits, 2026-05-17 09:14-09:24)
  9678f1e  W9-C1: cross-validate eval scenarios vs harvested gate codes
  2ad1b28  feat(diagnostics): W9-D2 lint_kb_tags.py WARN-only KB tag vocab lint
  a8d9abf  refactor(evals): rename post_wave5_baseline -> post_wave7_baseline (W1 deep-int)
  fb9aee5  docs/infra: contributor hook activation guide + setup-dev.sh (W9-D3)
  262cee3  docs(readme): bump diagnostics (29->31) + tests (154->156) for W9-D2
  f8ad6cd  fix(docs): restore RAG_WAVE_1_TO_7_OVERVIEW.md (race-deletion recovery)
  61b2ed4  style(W9-D2): drop unused f-string prefix on 2 print statements
  d3a7e67  feat(evals): --diff flag for per-scenario delta vs baseline (W9-C2)
  4d42306  evals: extend labeled P@5 set 20 -> 36 queries (W9-A2)
  e8f1af9  docs(readme): bump tests count 156->158 (parallel sessions added 1)
  d1f5467  feat(rag): within-CP dense corroboration + _mmr_breakdown audit (W9-B2)
  041c663  feat(publication_gate): fail-closed on unreviewed disease KB (W9-B1)
  57c9047  fix(rag): ruff F401 in test_rag_corroboration (W9-B2 followup)
  3238466  docs(rag): preserve diagnoses + split overview (W9 D1 deep-int)

Wave 10 — R0 + R1-R4 + S1 + T1-T4 (READ-ONLY audit; 1 commit)
  2603578  fix(rag): drop 3 more unused f-string prefixes (W10-R0 ci-unit fix)
  (R1-R4, S1, T1-T4 outputs lived under /tmp/W10*; distilled into W11)

Wave 11 — F1-F5 + I1-I2 + M1-M2 (fix wave from W10 findings, 10 commits)
  b553612  fix(infra): align pre-push ruff scope with CI + clear 2 F841 dead vars (W11-F1)
  4ca2e4f  fix(lint): --baseline-mode errors on missing file + ship initial baseline (W11-F4)
  04ad7d7  fix(gate): disease_kb requires reviewer+last_reviewed+status (W11-F2)
  f7c1a31  fix(rag): _mmr_rerank passthrough branch + blocker_id invariant (W11-F3)
  b1e9c8d  feat(evals): signal-ablation diagnostic to find hybrid dilutor (W11-I1)
  fcde7ee  fix(evals): --diff-required + scenario_id alias + baseline aggregate echo (W11-F5)
  a74ff22  docs(rag): W10 findings postscript + ARCHITECTURE Q5 + stats refresh (W11-M1)
  e83d673  docs(readme): bump tests count 158 -> 160 (W11-M1)
  0de6235  decision(rag): _mmr_breakdown ADR + SHIP implementation (W11-I2)

Wave 12 — A1-A2 + B1-B5 (doc restructure, 7 commits)
  1b6d658  docs(readme): restructure ToC into 4 groups + doc map (W12-A1)
  7f2ba2c  docs(reference): add GATES.md (33 gates, sources of truth) (W12-B1)
  9e6ca64  docs(reference): add LINT_RULES.md (28 R001-R028 AST rules) (W12-B2)
  dc358bd  docs(reference): add DATASETS.md (16 medical datasets) (W12-B3)
  0bf5bcd  docs(reference): add MODEL_FAMILIES.md (23 families) (W12-B4)
  536b445  docs(reference): add ANALYSIS_TOOLS.md (21 standalone scripts) (W12-B5)
  5cc0c6a  docs(readme_en): link to docs/reference/*.md (W12-A2)

Wave 12 deep-int → Wave 13 prelude
  721e8e7  fix(diagnostics): add argparse to lint_stderr_routing for --help (CI unbreaker)
  8aba9dc  fix(diagnostics): add argparse to render_paper_figures for --help (CI unbreaker)
  cc3c717  feat(rag): demote WEIGHT_DENSE 0.5 -> 0.1 + rebalance per W11-I1 (W13-P0)
```

## Maintainer notes (pointers)

- **System architecture today**: `docs/ARCHITECTURE.md` Open Question
  #5 owns the live dense-weight story; this retro is the frozen
  narrative.
- **W11-I1 ablation harness**: `scripts/rag/evals/ablation_signal_drop.py`
  is the load-bearing artifact for any future signal-weight
  discussion. Re-run it before any further weight tuning.
- **ADR-0001** (`docs/adr/0001_mmr_breakdown_consumer.md`): the
  canonical example of a "SHIP vs CUT" decision document. Pattern is
  reusable for any future "dormant audit field" debate.
- **W12 docs/reference**: 5 long-form references that the README and
  README_EN now link to instead of duplicating. Treat them as the
  single source of truth for gate / lint-rule / dataset / model-family
  / analysis-tool questions; the registries
  (`scripts/core/_gate_registry.py`, `mlgg-lint rules`) are the
  data source — the markdown is curated.
- **Parallel-agent dispatch**: W12 demonstrated the right shape (each
  agent writes a fresh file in a non-contended subdirectory). W11
  demonstrated the wrong shape but recovered (4 stashes; ADR-0002 is
  the fix-forward).
- **Stash discipline**: at the start of any new wave, `git stash list`.
  If it has more than 2-3 entries, audit them with the W13-D0 / C0
  cleanup recipe before starting new work.

> **Continuation**: this retro covers W9-W12. Wave 13 is in flight at
> the time of writing; the W13 retrospective (when written) should
> link back here and resolve the open questions above.
