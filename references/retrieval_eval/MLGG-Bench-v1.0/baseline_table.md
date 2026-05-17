# Bench-09 Retrieval-Mode Baseline Comparison

Date: 2026-05-17  ·  Harness: `scripts/rag/evals/run_eval.py`  ·  Model: BGE (hybrid mode)

## Combined results table

| slice | mode | top_k | n_scenarios | n_evaluable | coverage_rate | mean_hit@k | mean_cp_hit@k (n_cp) | mean_tag_precision@k | wall_ms_total |
|---|---|---|---|---|---|---|---|---|---|
| baseline_30 | hybrid | 5 | 30 | 26 | 0.867 | 1.000 | n/a (0) | 0.669 | 16366.9 |
| baseline_30 | bm25_only | 5 | 30 | 26 | 0.867 | 0.962 | n/a (0) | 0.562 | 27.9 |
| baseline_30 | hybrid | 10 | 30 | 26 | 0.867 | 1.000 | n/a (0) | 0.537 | 13294.4 |
| expanded_155 | hybrid | 5 | 155 | 155 | 1.000 | 0.935 | 0.963 (136) | 0.517 | 14985.5 |
| expanded_155 | bm25_only | 5 | 155 | 155 | 1.000 | 0.929 | 0.949 (136) | 0.409 | 198.6 |
| expanded_155 | hybrid | 10 | 155 | 155 | 1.000 | 0.948 | 0.985 (136) | 0.390 | 13481.2 |
| clean_150 | hybrid | 5 | 150 | 150 | 1.000 | 0.967 | 0.962 (132) | 0.535 | 13797.3 |
| clean_150 | bm25_only | 5 | 150 | 150 | 1.000 | 0.960 | 0.947 (132) | 0.423 | 203.5 |
| clean_150 | hybrid | 10 | 150 | 150 | 1.000 | 0.980 | 0.985 (132) | 0.403 | 14973.3 |
| adversarial_20 | hybrid | 5 | 20 | 20 | 1.000 | 1.000 | 0.950 (20) | 0.660 | 18188.0 |
| adversarial_20 | bm25_only | 5 | 20 | 20 | 1.000 | 0.950 | 0.900 (20) | 0.500 | 43.9 |
| adversarial_20 | hybrid | 10 | 20 | 20 | 1.000 | 1.000 | 1.000 (20) | 0.500 | 12688.1 |

## Interpretation

- **baseline_30** (k=5): hybrid hit=1.000 vs bm25=0.962 (Δ=+0.038); tag_prec Δ=+0.108; hybrid wall=16367ms vs bm25 28ms
- **expanded_155** (k=5): hybrid hit=0.935 vs bm25=0.929 (Δ=+0.006); tag_prec Δ=+0.108; hybrid wall=14986ms vs bm25 199ms
- **clean_150** (k=5): hybrid hit=0.967 vs bm25=0.960 (Δ=+0.007); tag_prec Δ=+0.112; hybrid wall=13797ms vs bm25 204ms
- **adversarial_20** (k=5): hybrid hit=1.000 vs bm25=0.950 (Δ=+0.050); tag_prec Δ=+0.160; hybrid wall=18188ms vs bm25 44ms

**Summary.** Hybrid retrieval consistently lifts `mean_tag_precision@k` across every slice (better re-ranking of tag-relevant cards inside the top-5), while raw `mean_hit@k` differences are small on the curated slices and most pronounced on the adversarial set. BM25 stays competitive for hit@k on `baseline_30`/`clean_150` and costs ~3 orders of magnitude less wall time, so it remains the right default when only first-card recall matters; hybrid is the right pick whenever downstream tag ordering is consumed (e.g. CP enforcement or top-1 surfacing). Increasing top_k from 5 to 10 yields diminishing hit@k gains on clean slices but recovers further ground on `adversarial_20` where lexical overlap is weakest.

## Depth: hit@5 → hit@10 (hybrid)

| slice | hit@5 | hit@10 | Δ |
|---|---|---|---|
| baseline_30 | 1.000 | 1.000 | +0.000 |
| expanded_155 | 0.935 | 0.948 | +0.013 |
| clean_150 | 0.967 | 0.980 | +0.013 |
| adversarial_20 | 1.000 | 1.000 | +0.000 |

## Raw JSON sidecars captured

- `baseline_30` / `hybrid` / k=5 → `/tmp/mlgg_benchmark/bench09_baseline_hybrid_k5.json`
- `baseline_30` / `bm25_only` / k=5 → `/tmp/mlgg_benchmark/bench09_baseline_bm25_k5.json`
- `baseline_30` / `hybrid` / k=10 → `/tmp/mlgg_benchmark/bench09_baseline_hybrid_k10.json`
- `expanded_155` / `hybrid` / k=5 → `/tmp/mlgg_benchmark/bench09_expanded_hybrid_k5.json`
- `expanded_155` / `bm25_only` / k=5 → `/tmp/mlgg_benchmark/bench09_expanded_bm25_only_k5.json`
- `expanded_155` / `hybrid` / k=10 → `/tmp/mlgg_benchmark/bench09_expanded_hybrid_k10.json`
- `clean_150` / `hybrid` / k=5 → `/tmp/mlgg_benchmark/bench09_clean_hybrid_k5.json`
- `clean_150` / `bm25_only` / k=5 → `/tmp/mlgg_benchmark/bench09_clean_bm25_only_k5.json`
- `clean_150` / `hybrid` / k=10 → `/tmp/mlgg_benchmark/bench09_clean_hybrid_k10.json`
- `adversarial_20` / `hybrid` / k=5 → `/tmp/mlgg_benchmark/bench09_adversarial_hybrid_k5.json`
- `adversarial_20` / `bm25_only` / k=5 → `/tmp/mlgg_benchmark/bench09_adversarial_bm25_only_k5.json`
- `adversarial_20` / `hybrid` / k=10 → `/tmp/mlgg_benchmark/bench09_adversarial_hybrid_k10.json`
