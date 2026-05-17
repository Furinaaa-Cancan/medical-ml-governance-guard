# ADR 0005 — NCPR-Bench v1: Held-Out Paper Benchmark for MLGG-as-AI-Reviewer

- Status: Accepted
- Date: 2026-05-17
- Author: W22-T2
- Related: W22-T1 (`references/benchmark/ncpr_v1_spec.md`, full spec), W18-D2 (frozen-id retrieval saturation), W17-C5 (labeled_precision_at_5 ceiling), W14-F1 (component-vs-pipeline gap surfaced), `references/retrieval_eval/METRIC_CONTRACT.md` (no-LLM-judge rule)

## 1. Context

Today MLGG's evaluation surface measures **retrieval components only**:

- `labeled_precision_at_5` over a frozen seed-query set (`references/retrieval_eval/`).
- MLGG-Bench v1.0 (305 scenarios, commit `f607116`) — also retrieval-scoped: given a query, did the right KB precedent surface in top-K.
- Per-gate unit tests — also component-scoped.

None of these answer the question that actually justifies the project: *given a held-out paper, does MLGG-as-a-whole flag the same concerns a Nature Methods / JAMA reviewer would raise?* Three waves of evidence say the retrieval-only evals are a depreciating asset:

| Wave | Signal | Implication |
|------|--------|-------------|
| **W18-D2** | `labeled_precision_at_5` plateaued at 0.92 over W15–W18; further retriever tuning moved the needle <0.01 | Frozen-id eval has saturated; further investment is rearranging deck chairs. |
| **W17-C5** | Manual spot-check found 3/10 papers where retrieval was perfect but the final MLGG report still missed a reviewer-grade concern (gate orchestration / report-synthesis gap) | Component-green ≠ system-green. The gap lives downstream of retrieval. |
| **W14-F1** | First explicit "we don't have a pipeline-level eval" finding; deferred for spec work | The gap was named 8 weeks ago and no integration test exists yet. |

Without a held-out pipeline eval we cannot (a) compare MLGG versions head-to-head with a defensible number, (b) calibrate a CI gate threshold, or (c) substantiate the "NC-grade reviewer" claim the project leans on in its own README. ADR 0002 / 0004 fixed *how we ship*; this ADR fixes *how we know shipping helped*.

## 2. Decision

**Build NCPR-Bench v1** — a held-out **paper-level** benchmark scoring MLGG-as-AI-reviewer against human reviewer concerns from the published peer-review record.

Core design (full spec: `references/benchmark/ncpr_v1_spec.md`, W22-T1):

- **Corpus**: 30 papers held out from KB ingestion, drawn from venues that publish reviewer reports (Nature family transparent peer review, eLife, F1000, PLOS).
- **Ground truth**: each paper's reviewer concerns extracted and normalized into the MLGG category taxonomy (S/P/F/M/E ladder from CLAUDE.md §"不可协商规则").
- **Scoring**: semantic-match-based **recall** (did MLGG flag each reviewer concern?) and **precision** (were MLGG's flags reviewer-grade?), composed as **severity-weighted F1** plus **category coverage** (a Major Concern miss costs more than a Minor Concern miss; see spec §4 for weights).
- **No LLM judge in the scoring loop** — semantic matching uses a frozen sentence-transformer + curated synonym table, per `METRIC_CONTRACT.md`.
- **KB exclusion**: MLGG runs the eval with `--exclude-papers <held-out-doi-list>` so the system cannot retrieve the held-out paper's own analysis as its precedent. This requires a new KB flag (tracked as a T4 prereq).
- **Run-time budget**: ~1–2 min per paper × 30 papers ≈ 30–60 min wall-clock per benchmark run. Acceptable for nightly / pre-release, not for per-commit.

### Why now

Three independent waves converged on the same gap (§1). Each additional week of retrieval-only iteration adds version-comparison debt: we cannot defend "v0.3 is better than v0.2" without it. The spec (T1) is already written, so the marginal cost of adopting now is the harness build (T3–T5), not the design work.

## 3. Alternatives considered

**Alt A — Extend `labeled_precision_at_5` to more queries.** Cheapest: just add labels. Rejected because §1's W17-C5 evidence shows the gap is **downstream of retrieval**. Adding query labels cannot measure gate orchestration, report synthesis, or severity calibration. Same depreciating-asset problem at higher N.

**Alt B — LLM-judge eval (Opus rates MLGG flags vs reviewer concerns).** Tempting: a strong judge could score nuanced semantic overlap that frozen embeddings miss. **Rejected per `METRIC_CONTRACT.md` no-LLM-judge rule** — circularity (the judge and the system-under-test are siblings from the same lab; benchmark gaming by prompt drift is undetectable from inside the loop) and reproducibility erosion (model updates silently change the score). The semantic-match noise floor in NCPR is a known cost we accept in exchange for a number that means the same thing in 2027 as it does today.

**Alt C — Replay historical CI runs against past papers.** No held-out signal: any paper MLGG was developed against is already in the KB. Replaying tells us about regression, not about generalization. Useful as a separate regression harness, not as the pipeline eval.

**Alt D — Skip pipeline eval; keep iterating retrieval and ship on vibes.** The status quo, named for what it is. Rejected because §1 shows three waves of accumulated evidence that the retrieval number no longer predicts user-visible quality, and because version-comparison debt is compounding.

## 4. Consequences

### Positive

- **Real system-level measurement.** First number that maps to the user's actual question ("would MLGG catch what a reviewer catches?"). Enables defensible version comparison.
- **NC-grade claim becomes falsifiable.** "MLGG operates as a Nature Methods–grade reviewer" goes from rhetoric to a measured recall / precision pair on held-out papers from Nature-family venues.
- **CI gate calibration target.** Once a baseline lands, the harness can be wired into nightly CI with a regression threshold (e.g., severity-weighted F1 must not drop >5% between commits).
- **Downstream gap visibility.** Pipeline-level failures will be attributable to a stage (retrieval / orchestration / synthesis) and direct future work to the actual bottleneck rather than the easiest one to instrument.

### Negative

- **Cost per run.** ~30–60 min vs seconds for retrieval eval. Not per-commit; nightly or pre-release. Mitigation: keep retrieval evals as the per-commit fast gate.
- **KB plumbing prereq.** Requires `--exclude-papers` support in the KB loader (T4 dependency). Until that lands, the benchmark is unrunnable; reviewers should not approve T3–T5 merges until T4 is in flight.
- **Semantic-match noise floor.** The frozen-embedding matcher will sometimes miss valid paraphrases and sometimes false-match on lexical overlap. Spec §4 budgets a calibration step (manual review of 50 match decisions to estimate the per-comparison error rate); the score's confidence interval must include this.
- **Pipeline non-determinism.** MLGG's report synthesis is non-zero-temperature in places; same paper run twice will not produce identical flag sets. Spec §5 mandates ≥3 runs per paper and reports mean ± stdev; this widens CIs but is honest.
- **N=30 small-sample power.** A 5% F1 delta between two MLGG versions may not be statistically distinguishable. Acknowledged in §5; we accept this for v1 and budget a v2 expansion to N=100 once the harness exists and the per-paper cost drops.

### Migration

- Existing retrieval evals (`references/retrieval_eval/`, MLGG-Bench v1.0) **remain** as component tests. NCPR is **additive**, not a replacement. Two-tier eval surface: fast component evals per-commit, slow integration eval nightly.
- `METRIC_CONTRACT.md` gains an NCPR section (T3 deliverable) extending the no-LLM-judge rule to the new harness.
- `agents/reviewer.yaml` is **not** the system under test — that prompt-only reviewer scores papers in isolation. NCPR scores the full MLGG pipeline (gates + KB + synthesis). The two are orthogonal and both retained.

## 5. Implementation phases

| Phase | Deliverable | Owner | Status |
|-------|-------------|-------|--------|
| **T1** | Spec: `references/benchmark/ncpr_v1_spec.md` | W22-T1 | Done (referenced by this ADR) |
| **T2** | This ADR | W22-T2 | This commit |
| **T3** | Sub-spec: scoring + matcher details, `METRIC_CONTRACT.md` extension | W22-T3 | Pending |
| **T4** | Sub-spec: KB `--exclude-papers` flag + corpus selection rubric | W22-T4 | Pending (blocking T6) |
| **T5** | Sub-spec: harness CLI + report schema | W22-T5 | Pending |
| **T6** | Harness implementation (Tier 3 agents — code) | TBD | Blocked on T3–T5 |
| **T7** | Baseline run on current `main`, publish report | TBD | Blocked on T6 |
| **T8** | CI gate calibration (nightly job + regression threshold) | TBD | Blocked on T7 |

## 6. Self-challenge

The strongest argument against NCPR-Bench v1 is **statistical**: at N=30 with a noisy semantic matcher and non-deterministic pipeline, the score's confidence interval may be wide enough that two MLGG versions a reasonable person would call "clearly better" and "clearly worse" produce overlapping intervals — making the benchmark expensive theatre that fails to discriminate. This is the honest risk; the spec (T1 §5) addresses it with mandatory CI reporting and a v2 N=100 expansion path, but if the W22 baseline run shows the CI is wider than the typical inter-version delta, the benchmark has failed its own test and we should downgrade it from CI gate to advisory-only until N grows.

## 7. References

- W22-T1 spec: `references/benchmark/ncpr_v1_spec.md` (full design, scoring math, corpus rubric).
- `references/retrieval_eval/METRIC_CONTRACT.md` — no-LLM-judge rule cited in §3 Alt B.
- ADR 0001 (`docs/adr/0001_mmr_breakdown_consumer.md`) — retrieval-side decision predating this pipeline-side one.
- ADR 0002, 0004 — operational protocols (shipping discipline); this ADR is the measurement counterpart.
- CLAUDE.md §"不可协商规则" — S/P/F/M/E ladder used as the NCPR category taxonomy.
- W18-D2 retrieval-saturation finding (wave notes).
- W17-C5 spot-check (wave notes) — original "component-green ≠ system-green" evidence.
- W14-F1 — first naming of the pipeline-eval gap.
