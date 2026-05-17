# W23-D5 — NCPR-Bench v2 Report (PROVISIONAL)

**2026-05-17.** PROVISIONAL: D2 baseline + D4 retrieval-vs-pipeline DATA PENDING. Fixes methodology + reporting frame, not a headline. Re-issue after D2 commits with matcher wired.

## TL;DR

MLGG NCPR v2 weighted F1 = **TBD** on 30 NC-only papers; smoke n=5 returned 0.000 (`matcher=="unknown"`), no defensible headline yet.

## Methodology (B1 spec, ADR-0006)

NC-only N=30, KB snapshot `729bd3c5`. PDF methods extracted at run time (A2). Severity × category stratification replaces journal stratification. Severity-weighted F1 headline; per-severity recall, category coverage, tail-severity recall co-reported. Matcher operating point not yet frozen (B4 three-phase sweep awaits C1 mini-set labels).

## Headline + percentiles

D2 smoke n=5: mean=median=p25=p75=0.000; integration-incomplete, not capability bound. D3 used a seeded stub (mean 0.487, σ=0.133), not a real measurement.

## Failure mode top 5 (D2 smoke)

1. Matcher unintegrated — zero matches by construction.
2. HIGH over-flag: 77 extra vs 5 missed.
3. CRITICAL over-flag: 18 extra, 0 matched.
4. MEDIUM under-detection: 18 missed.
5. Cold/warm wall asymmetry: 0.04 s – 13.1 s per paper.

## Retrieval-only vs full (D4)

DATA PENDING. No commit, no `/tmp/W23_D4_*`.

## Power (D3, stub n=5)

σ point 0.133; χ² 95% CI [0.080, 0.382]. N=30 MDD ≈ 5.3 pp (point), ≤15 pp (CI upper). **YELLOW** — no GREEN until D2 confirms σ on ≥15 real F1.

## D1 stratification (kb_sha `729bd3c5`)

51 eligible → 30 selected. **Two B3 floor violations**: CRITICAL papers 7 vs ≥8; `leakage` category 0 vs ≥4. Surface or relax via ADR, never silently.

## Caveats

- LLM synthesiser non-deterministic; per-run σ not quantified.
- BGE-small-en-v1.5 general-purpose, not biomedical (B4 §9).
- KB auto-correlation: NC home-turf inflates score (ADR-0006 §5).
- B3 floors unmet by D1 dry-run.

## NOT claimed

- Cross-journal generalisation (NM/npjDM/JAMA/LDH/BMJ 0-PDF).
- Per-category F1 (W22-V1: per-cat MDD ≥17.7 pp at N=30).
- CRITICAL recall (KB CRITICAL n=41; in-holdout CRIT=7).
- Retrieval-vs-pipeline attribution (D4 pending).
- Citable headline (waiting on D2 real run).

## Pre-registration

Any v3 change (matcher, KB, multi-journal, severity rubric) requires a new ADR. Companion: `/tmp/W23_D5_summary.json`.
