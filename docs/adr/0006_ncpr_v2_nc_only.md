# ADR 0006 — NCPR-Bench v2: NC-Only Data-Driven Relaxation

- Status: Accepted
- Date: 2026-05-17
- Author: W23-B2
- Related: ADR 0005 (`docs/adr/0005_ncpr_benchmark_design.md`, v1 design), W22-T3 (v1 spec), W22-U3 (KB audit), W22-X7 (`HoldoutBuilderError(journal_cap_infeasible)`), W23-A5 (extra-candidate ingest scoping)

## 1. Context

ADR 0005's v1 design (W22-T1 spec, W22-T3 sub-spec) assumed a 6-journal held-out corpus: Nature Communications (NC), Nature Methods (NM), npj Digital Medicine (npjDM), JAMA, *The Lancet Digital Health* (LDH), and PLOS Digital Health. Per-journal cap = 5, total N = 30. The cap exists to prevent any single venue dominating the score.

Two independent W22 signals invalidate the assumption:

- **W22-U3 KB audit.** Inventory of `references/papers/` revealed the curated KB contains **150 NC papers + 4 CM papers**; the four other journal folders (`nm/`, `npjdm/`, `jama/`, `ldh/`) exist as empty templates from W19 scaffolding but were never populated with annotated reviewer concerns. The 6-journal assumption was scaffolding, not data.
- **W22-X7 holdout builder.** The first end-to-end run of the v1 corpus selector raised `HoldoutBuilderError(journal_cap_infeasible)` — it could not satisfy `min_per_journal=3` for NM/npjDM/JAMA/LDH because the candidate pool for those venues is empty. v1 is **structurally unrunnable** today, not merely slow.

Two paths forward:

- **Path A — ingest NM/npjDM/JAMA/LDH papers to satisfy v1.** W23-A5's scoping note estimates days of curator effort (paper selection, reviewer-concern extraction, S/P/F/M/E tagging, calibration); the work is real but not blocked on design.
- **Path B — relax v2 to NC-only, ship now.** Immediate execution against the 150-paper NC pool; the trade is a narrower generalization claim.

## 2. Decision

**NCPR-Bench v2 is NC-only.** Stratify the 30-paper holdout by **severity (Major / Minor / Question) × category (S/P/F/M/E)** instead of by journal. Honest scope statement in the report header: *"NCPR v2 evaluates MLGG on NC-style papers — the journal MLGG was primarily curated against. Cross-journal generalization is a v3 question."*

This keeps the spec's core machinery from ADR 0005 §2 intact (semantic-match scoring, no-LLM-judge rule, `--exclude-papers` KB flag, ≥3-run determinism budget, severity-weighted F1) and only replaces the journal-stratification axis with a severity × category axis that the actual data supports.

### Why not Path A

Time-to-value. The benchmark's first job is to give MLGG development a defensible version-comparison number; that signal is more useful **now**, even on a narrower corpus, than it is **in two weeks** on a multi-journal corpus. The multi-journal claim becomes ADR 0007 / NCPR v3 when W23-A5's ingest brings the other venues above the curated-N floor. Sequencing v2-then-v3 also lets v3 inherit v2's calibration constants instead of co-developing them under deadline.

## 3. Consequences

### Positive

- **Immediate execution.** Group D agents (W23-D1 through D5, harness + baseline run) unblock today; estimated wall-clock 5–10 min per agent against the existing 150-paper pool.
- **Tighter signal on home turf.** NC papers were the curation source for MLGG's reviewer-concern taxonomy; reviewer-concern ground-truth quality is highest where curator attention was densest. Noise floor in the semantic matcher is correspondingly lowest.
- **v1 machinery preserved.** Scoring math, KB exclusion flag, determinism budget, and CI-gate path from ADR 0005 §§2,4 all carry over unchanged — only the stratification axis moves.

### Negative

- **No cross-journal generalization claim.** v2 cannot defend "MLGG works on JAMA-style or NM-style papers"; that claim must wait for v3. README and `references/benchmark/README.md` must reflect this scope.
- **Partial auto-correlation in the score.** NC is MLGG's home turf — the KB was built largely from NC reviewer patterns. v2's headline number is closer to an **upper bound** of MLGG's capability than to an unbiased generalization estimate. Reporting must say so.

### Mitigation

- Report header and `references/benchmark/v2_report.md` schema both carry the explicit string "NC home-turf benchmark" alongside every headline number.
- v3 cross-journal expansion is openly queued in the W23-A5 backlog; ADR 0006 is **not** a permanent narrowing, it is a sequencing decision.
- The severity × category stratification, while data-driven, is also independently useful: it surfaces per-axis weaknesses (e.g., "MLGG recalls 0.9 on S but 0.6 on F") that journal-stratification would have masked. v3 should retain this axis additively.

## 4. Reversal criteria

ADR 0006 is reversed (i.e., NCPR returns to a multi-journal design as v3) when W23-A5's extra-candidate ingest brings **NM and npjDM each to ≥10 curated papers with reviewer-concern annotations**. At that point the journal-cap arithmetic from ADR 0005 §2 becomes feasible (per-journal floor of 3 is satisfiable with a held-out 5 + 5 from those two venues alone, plus the existing NC pool) and v3 can re-stratify on severity × category × journal. JAMA and LDH are nice-to-have but not gating; the reversal threshold is set at the two journals closest to MLGG's stated scope (digital health methods).

## 5. Self-challenge

The strongest argument against v2-NC-only is the **auto-correlation objection**: NC-only inflates MLGG's apparent score because the KB was built largely from NC reviewer style — the system is being graded on the same distribution it was trained against, so v2's number is closer to a train-set metric than a generalization metric. This objection is correct in direction and worth printing on the report.

The counterargument is **upper-bound utility**. Even on home turf, the NCPR baseline tells us the **ceiling** of what MLGG can credibly claim today: if v2's severity-weighted F1 on home-turf NC papers is only 0.55, no cross-journal v3 will magically push it to 0.85, and we have an honest signal to prioritize gate-orchestration work before expanding the corpus. If v2's F1 is 0.85 on home turf, we have a defensible reason to invest the curator time on Path A — because the ceiling is high enough that the multi-journal floor is plausibly worth chasing. Either way, v2 is decision-useful in a way that "wait two weeks for v1" is not.

## 6. References

- ADR 0005 (`docs/adr/0005_ncpr_benchmark_design.md`) — v1 design this ADR relaxes.
- W22-T3 v1 spec (`references/benchmark/ncpr_v1_spec.md`) — journal-stratification design that W22-U3 + W22-X7 invalidated.
- W22-U3 KB audit (wave notes) — 150 NC + 4 CM, other folders empty.
- W22-X7 holdout builder failure (`HoldoutBuilderError(journal_cap_infeasible)`) — structural infeasibility evidence.
- W23-A5 extra-candidate ingest scoping (wave notes) — Path A effort estimate and v3 reversal criteria source.
- `references/retrieval_eval/METRIC_CONTRACT.md` — no-LLM-judge rule, unchanged for v2.
- CLAUDE.md §"不可协商规则" — S/P/F/M/E ladder, the new stratification axis.
