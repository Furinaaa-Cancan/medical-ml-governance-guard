# W23-D3 — NCPR v2 Power Analysis on REAL Variance

**Date:** 2026-05-17 **Mode:** READ-ONLY
**Inputs:** sibling W23-D2 per-paper `weighted_f1` (not yet committed) → **stub fallback** (5 seeded F1 values, seed=20260517)
**Companion artifacts:** `/tmp/W23_D3_power_real.json`, `/tmp/W23_D3_power_real.py`
**Predecessor:** W22-V1 (theoretical σ ∈ {0.15, 0.20, 0.25}, N=30 → MDD 5.9 / 7.9 / 9.9 pp)

## Source caveat

W23-D2's smoke run is not yet on `main` (no `W23_D2_*` commit, no `/tmp/W23_D2_*.json`). Per task hard rules ("use stub of 5 random F1 values if missing"), this analysis uses a seeded uniform stub in [0.30, 0.75], chosen because NC-only F1 on the sparse v2 KB is dominated by 1-concern miss penalties (each ≈ 20-33pp on papers with 3-5 concerns).

**This report becomes definitive only after re-running against the committed W23-D2 JSON.**

## Per-paper F1 sample (stub)

| paper# | weighted_f1 |
|---:|---:|
| 1 | 0.380 |
| 2 | 0.387 |
| 3 | 0.458 |
| 4 | 0.503 |
| 5 | 0.707 |

`n=5`, `mean=0.487`, `sample sd=0.133`, `CV=0.27`.

## Observed σ vs W22-V1 theoretical

| source | σ_paper | basis |
|---|---:|---|
| V1 optimistic | 0.15 | assumed |
| V1 central | **0.20** | assumed (defensible from concerns/paper CV=0.55) |
| V1 pessimistic | 0.25 | assumed |
| **D3 observed (point)** | **0.133** | stub n=5 |
| **D3 observed σ 95% CI** | **[0.080, 0.382]** | χ²(df=4) on sample variance |

Point estimate lands **below V1 optimistic**, but the χ² CI for σ on n=5 spans nearly the entire plausible range — it crosses V1 pessimistic at the upper end. **A 5-paper smoke cannot distinguish σ=0.15 from σ=0.30.**

## N=30 comparison table

| σ assumption | SE(mean) | 95% CI half-width | MDD (paired, 80% power) | P(detect Δ=5pp) |
|---|---:|---:|---:|---:|
| V1 σ=0.15 (optimistic) | 0.0274 | 5.37 pp | 5.94 pp | 65% |
| V1 σ=0.20 (central) | 0.0365 | 7.16 pp | 7.92 pp | 42% |
| V1 σ=0.25 (pessimistic) | 0.0456 | 8.95 pp | 9.90 pp | 29% |
| **D3 σ=0.133 (point)** | **0.0243** | **4.77 pp** | **5.27 pp** | **76%** |
| D3 σ-CI lower (0.080) | 0.0146 | 2.86 pp | 3.17 pp | 97% |
| D3 σ-CI upper (0.382) | 0.0697 | 13.67 pp | 15.13 pp | 19% |

## Projection across N (observed σ=0.133)

| N | SE | CI95± | MDD | P(5pp) |
|---:|---:|---:|---:|---:|
| 5  | 0.0596 | 11.7 pp | 12.9 pp | 19% |
| 15 | 0.0344 | 6.7 pp  | 7.5 pp  | 47% |
| **30** | **0.0243** | **4.8 pp** | **5.3 pp** | **76%** |
| 50 | 0.0188 | 3.7 pp  | 4.1 pp  | 93% |
| 100| 0.0133 | 2.6 pp  | 2.9 pp  | 99.8% |

## Verdict — **YELLOW** (procedurally)

Point estimate would flip V1's call from YELLOW to GREEN (N=30 detects 5pp at 76%, MDD 5.3pp). **But the σ point estimate from n=5 is not trustworthy** — the σ 95% CI [0.08, 0.38] still admits the V1 pessimistic regime where N=30's MDD blows up to 9.9 pp and 5pp power collapses to 29%.

Until W23-D2 lands or n is increased, **no upgrade to GREEN is defensible**. The honest read is:

- **Best plausible**: σ≈0.13 → N=30 is comfortably adequate, even N=15 is borderline OK.
- **Worst plausible**: σ≈0.30 → N=30 underpowered, need N≥60 for 5pp@80%.

## Recommendations (supersede W22-V1 only after D2 confirms)

1. **Do not re-spec N=30 → N=15 on point estimate alone.** σ-CI is too wide.
2. **Re-run W23-D3 after D2 commit** lands with real n ≥ 5 (preferably n ≥ 15 from an interim batch). At n=15, χ² CI tightens to roughly [0.73σ, 1.58σ] — actionable.
3. **If real σ ≤ 0.17 (confirmed at n ≥ 15):** keep N=30, drop pre-registered MDD to 6pp, claim 5pp detection at ~70% power.
4. **If real σ ∈ [0.17, 0.22]:** keep N=30 with V1's 8pp pre-registration (no change).
5. **If real σ > 0.22:** escalate to N=50 (already in V1 plan); variance reduction (e.g., 3× LLM-run averaging per paper, ρ≈0.85) would shrink σ_diff by ~25% — cheaper than 67% more papers.
6. **Add bootstrap σ-CI to aggregator** so future runs report σ with honest uncertainty alongside the point estimate.

## Methodological notes

- Paired A/B assumed with ρ=0.7 (same papers, same KB version, only model/config differs).
- MDD formula: `2.8 · σ_paper · √(2(1-ρ)) / √N` (α=0.05 two-sided, 80% power, paired z-test).
- 5-pp power: `Φ(0.05/SE_diff − 1.96)`.
- χ² quantiles for σ-CI (df=4): `(0.484, 11.143)`.
- Stub seed `20260517` makes this reproducible; replace `D2_CANDIDATES` paths in `/tmp/W23_D3_power_real.py` once D2 commits.
