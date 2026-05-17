# W22-V1 — NCPR Benchmark Power Analysis (N=30 holdout)

**Date:** 2026-05-17 **Mode:** READ-ONLY
**Inputs:** `peer-review-kb.json`, sibling `W22_U2_concern_stats.md`
**Companion JSON:** `/tmp/W22_V1_power_analysis.json`

## Inputs

154 curated papers; concerns/paper mean **5.31**, σ **2.92**, CV 0.55. Severity (817): CRITICAL 41 (5%), HIGH 304, MEDIUM 412, LOW 60. Top-5 papers hold 8.8% — no dominance.

## Assumptions

Per-paper weighted F1 ∈ [0,1]; σ_paper modelled 0.15/0.20/0.25 (central **0.20**, defensible given CV 0.55 on bounded metric). A/B compared **paired** on same 30 papers; ρ=0.7 → σ_diff = 0.632·σ_paper. MDD = 2.8·σ_diff/√N at α=0.05, 80% power. Power(Δ=5pp) = Φ((0.05/SE_diff) − 1.96).

## Headline (σ=0.20, ρ=0.7)

| N | 95% CI ± | MDD (paired) | P(detect 5pp) |
|---:|---:|---:|---:|
| 15  | 10.1pp | 11.2pp | 24% |
| **30**  | **7.2pp** | **7.9pp** | **42%** |
| 50  | 5.5pp  | 6.1pp  | 63% |
| 100 | 3.9pp  | 4.3pp  | 90% |

σ=0.15 optimistic: N=30 MDD 5.9pp, 65% power. σ=0.25 pessimistic: 9.9pp, 29%.

## Per-category / per-severity power at N=30

5-way even split → 6/cat → MDD **17.7pp**. By severity: CRITICAL ~1.5 papers (insufficient), LOW ~2.2 (MDD 29pp), HIGH ~11 (13pp), MEDIUM ~15 (11pp).

## Verdict — **YELLOW**

N=30 supports aggregate F1 deltas ≥~8pp only. **Underpowered for Δ=5pp (42%)** and **any per-category claim**. CRITICAL power is structurally unavailable — KB has only 41 CRITICAL concerns total.

## Recommendation

1. **Keep N=30 for v1 aggregate scorecard**; pre-register 8pp as smallest reportable delta. No per-category F1 claims.
2. **Scale to N=50 for v1.1**: drops MDD to 6.1pp, crosses Δ=5pp = 63% power. Linear cost, threshold-crossing value.
3. **Stratify on severity, not category** (oversample CRITICAL/HIGH per W22-U2). Category-level claims need N≈125 — defer.
4. **Always pair A/B** on same 30 papers; unpaired loses ~40% effective N.
5. **Bootstrap CIs** in aggregator since σ_paper is estimated.
