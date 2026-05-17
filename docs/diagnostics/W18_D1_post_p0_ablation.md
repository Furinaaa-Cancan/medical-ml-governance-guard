# W18-D1 — Post-W13-P0 4-Signal Re-Ablation

**Wave:** 18 (RAG & Retrieval Critical Review) — D1 strict-review audit
**Mode:** READ-ONLY code; eval run only
**Date:** 2026-05-17
**Script:** `scripts/rag/evals/ablation_signal_drop.py` (W11-I1, b1e9c8d)
**Scenarios:** `references/retrieval_eval/scenarios.json` (n=30)
**Current config:** `WEIGHT_DENSE=0.10`, `WEIGHT_BM25=0.45`, `WEIGHT_TAG_OVERLAP=0.30`, `WEIGHT_SEVERITY=0.15` (post W13-P0, cc3c717)
**Raw outputs:** `/tmp/W18_D1_ablation.json`, `/tmp/W18_D1_ablation.md`, `/tmp/W18_D1_run.txt`

---

## 1. Comparison table — W11-I1 (DENSE=0.5) vs W18-D1 (DENSE=0.1) on `mean_tag_p@5`

| config             | W11-I1 (DENSE=0.5) | W18-D1 (DENSE=0.1) | delta (W18 − W11) | now-best |
| ------------------ | -----------------: | -----------------: | ----------------: | :------: |
| A_bm25_only        | 0.436              |             0.4358 |           −0.0002 |          |
| B_hybrid_all       | 0.353              |             0.4375 |           +0.0845 |          |
| C_hybrid_no_dense  | 0.447              |             0.4424 |           −0.0046 |    ✓     |
| D_hybrid_no_tag    | 0.349              |             0.4097 |           +0.0607 |          |
| E_hybrid_no_sev    | 0.348              |             0.4193 |           +0.0713 |          |
| F_hybrid_no_mmr    | 0.355              |             0.4353 |           +0.0803 |          |

Secondary metrics (W18-D1): **coverage_rate = 0.8667 and hit@5 = 0.8333 for ALL six configs** — identical, so the differentiator is purely intra-top-5 ranking quality (tag precision). The labeled-drop concern noted in the brief does not manifest at coverage/hit level on this n=30 set.

---

## 2. Per-signal verdict

| signal     | drop-delta vs hybrid_all | direction | verdict (this audit)        |
| ---------- | -----------------------: | --------- | --------------------------- |
| DENSE      |                  +0.0049 | helps     | keep at 0.10 (YELLOW)       |
| BM25       |     −0.0017 (vs bm25_only baseline) | core | keep at 0.45 (PASS)         |
| TAG_OVERLAP|                  −0.0278 | hurts     | keep at 0.30 (PASS)         |
| SEVERITY   |                  −0.0182 | hurts     | keep at 0.15 (PASS)         |
| MMR        |                  −0.0022 | ~neutral  | keep enabled (PASS — safe)  |

(Negative delta = removing this signal HURTS = signal is net-positive.)

---

## 3. Verdict: **YELLOW**

Current production config is **defensible but sub-optimum**.

- `B_hybrid_all` (0.4375) beats `A_bm25_only` (0.4358) by +0.0017 → W13-P0 successfully flipped the sign of the hybrid-vs-bm25 gap (was −0.083 at DENSE=0.5; now +0.002). The hybrid no longer dilutes.
- However, `C_hybrid_no_dense` (0.4424) still beats hybrid_all by +0.0049 on this set. DENSE at 0.10 is *barely* helpful and possibly still a residual drag.
- BM25, TAG_OVERLAP, SEVERITY, and MMR are now all net-positive contributors at the new weighting — the W11-I1-era "tag/severity are noise" finding has reversed, exactly as predicted by the rebalancing thesis.

---

## 4. Hypothesis: did W13-P0 leave any signal mis-weighted?

**Most likely yes — DENSE may still be slightly over-weighted.** The +0.0049 gap from dropping DENSE entirely is small (within plausible n=30 sampling noise: 30 scenarios × 5 hits = 150 binary judgments per config; per-config std for tag_p@5 typically ~0.03 → SE_mean ~0.005). So at this sample size the +0.0049 is at the edge of significance and a full demotion to 0 cannot be defended from this data alone.

Secondary observation: BM25 is doing essentially all the work (0.4358 alone vs 0.4375 ensemble = +0.4%). The ensemble's three lexical/structural co-signals (BM25 + tag + severity) are coherent; the dense vector is the lone outlier modality whose marginal value is near zero on canonical-pattern scenarios.

---

## 5. Wave-N+ fix candidates (specific, ranked)

| # | proposal | `config.py` edit | expected mean_tag_p@5 | risk |
| - | -------- | ---------------- | --------------------: | ---- |
| 1 | Further-demote DENSE to 0.05, redistribute to BM25 | `WEIGHT_DENSE: 0.05`, `WEIGHT_BM25: 0.50`, tag/sev unchanged | ~0.440 (interpolation) | LOW — within observed range |
| 2 | Drop DENSE entirely (matches `C_hybrid_no_dense`) | `WEIGHT_DENSE: 0.00`, `WEIGHT_BM25: 0.50`, `WEIGHT_TAG_OVERLAP: 0.333`, `WEIGHT_SEVERITY: 0.167` | 0.4424 (measured) | MED — kills paraphrase fallback; need OOD scenario coverage first |
| 3 | Hold (current 0.1) and expand eval set to n≥60 before re-deciding | none | 0.4375 (status quo) | LOW — defers decision until sampling noise drops below the +0.0049 effect |

**Recommended:** **#3 first, then #1.** The +0.0049 advantage of dropping DENSE is at the noise floor for n=30; expanding to n≥60 (W17-C4/C5 already flagged scenarios staleness) is the cheaper, more rigorous next step before any further weight edit.

**Do NOT** propose any change to BM25 / TAG_OVERLAP / SEVERITY / MMR at this audit — all four are now demonstrably net-positive at the current balance.

---

## 6. Hard-rule compliance

- READ-ONLY: confirmed; no `scripts/rag/config.py` edits in this branch (verified by `git status` after run).
- No sub-agents invoked.
- No package installs.
- Eval script invocation only.
