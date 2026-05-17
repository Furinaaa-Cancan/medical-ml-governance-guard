# MLGG-Bench v1.0

> 📌 **Newer PATCHes available.** Use [v1.0.2](../MLGG-Bench-v1.0.2/) for any new evaluation.
> - [v1.0.1](../MLGG-Bench-v1.0.1/): 59 indist CP-label refinements → `cp_hit@5` 0.794 → 0.821 (+0.027)
> - [v1.0.2](../MLGG-Bench-v1.0.2/): + 32 OOD CP-label refinements → `cp_hit@5` 0.821 → **0.856** (+0.035), total +0.062
>
> v1.0 is preserved for reproducibility of the original release numbers.
>
> 📌 **v1.1 work-in-progress** lives at [`v1.1_proposed/`](./v1.1_proposed/) — 30 TRIPOD+AI / PROBAST+AI / STRATOS KB meta-entries (verified to lift `ood_03` hit@5 by +0.20), plus a compound-query decompose prototype that returned a documented NEGATIVE result. Both pending clinical-methodologist review per project disease-KB provenance policy.
>
> 📌 **Architectural context.** This is one of two complementary benchmarks; see [`docs/adr/0007_two_benchmark_architecture.md`](../../../docs/adr/0007_two_benchmark_architecture.md) and [`docs/BENCHMARK_OVERVIEW.md`](../../../docs/BENCHMARK_OVERVIEW.md) for how MLGG-Bench (component) and NCPR-Bench (system) divide signal.

A standard benchmark for evaluating the MLGG peer-review concern retrieval RAG.

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Release date | 2026-05-17 |
| Total scenarios | 305 across 12 slices |
| KB SHA256 (first 16) | `729bd3c59ae0d972` |
| RAG under test | hybrid (BGE-small + BM25 + tag-overlap + severity), `WEIGHT_DENSE=0.10 / WEIGHT_BM25=0.45 / WEIGHT_TAG_OVERLAP=0.30 / WEIGHT_SEVERITY=0.15` |
| Eval harness | `scripts/rag/evals/run_eval.py` (commit `7fc1ca5` added `mean_cp_hit_at_k`) |

## Quick start

```bash
# Default — eval on dev split (held-out test untouched)
bash references/retrieval_eval/MLGG-Bench-v1.0/runner.sh

# Eval on a single slice
python3 scripts/rag/evals/run_eval.py \
  --scenarios references/retrieval_eval/MLGG-Bench-v1.0/all_scenarios.json \
  --top-k 5

# Eval on the held-out test split (release-only)
SPLITS="test" bash references/retrieval_eval/MLGG-Bench-v1.0/runner.sh
```

## Headline numbers (RAG hybrid, top-k=5, full 305)

| Metric | Value |
|---|---|
| `mean_hit_at_k` (primary) | **0.858** |
| `mean_cp_hit_at_k` (CP-level recall) | **0.794** (n_cp_evaluable=252) |
| `mean_tag_precision_at_k` | 0.448 |
| `coverage_rate` | 0.921 |

## Slices

| Slice | n | Purpose | hit@5 |
|---|---|---|---|
| `baseline_30` | 30 | Original hand-crafted regression — pre-existing `references/retrieval_eval/scenarios.json` | 1.000 |
| `indist_155` | 155 | KB-derived paraphrases (10 agents, post-CP-relabel v2) | 0.935 |
| `ood_01_retraction_watch` | 10 | Real retracted/critiqued ML medical papers (Epic Sepsis, Zech, DeGrave, Wong, Maguolo, etc.) | 0.800 |
| `ood_02_openreview` | 10 | NeurIPS / ICLR / ML4H public reviews (verified via OpenReview API v2) | 0.600 |
| `ood_03_tripod_probast` | 10 | TRIPOD+AI 2024 / PROBAST+AI 2025 / STRATOS meta-methodology critiques | **0.300** ⚠ |
| `ood_04_open_peer` | 10 | F1000Research + eLife published reviewer reports | 0.900 |
| `bench_01_fairness` | 10 | True fairness/equity/subgroup concerns | 1.000 |
| `bench_02_longtail` | 25 | Long-tail CPs (CP-025..CP-049, all 25 covered) | 0.840 |
| `bench_03_compound` | 10 | Multi-CP compound queries (2 CPs bundled) | **0.200** ⚠ |
| `bench_04_negatives` | 10 | Out-of-MLGG-scope (omics / imaging / NLP / survival) — should NOT match | n/a (see `false_strong_hit_rate=0.00`) |
| `bench_05_distractors` | 10 | Methodology-flavored but non-methodology intent | n/a (see `false_strong_hit_rate=0.10`) |
| `bench_07_adversarial_extended` | 15 | 5 attack vectors (lex / domain / length / mixed / codeswitch) | 0.733 |

## Files

```
MLGG-Bench-v1.0/
├── README.md              ← this file
├── all_scenarios.json     ← canonical 305-scenario artifact (entry point for harness)
├── SPEC.md                ← full benchmark specification (756 lines)
├── DIAGNOSIS.md           ← 3 documented failure modes + v1.1 work items
├── baseline_table.{md,json}  ← bm25_only vs hybrid × k=5/k=10 (12 runs)
├── split_spec.md          ← stratified 70/15/15 design + absorption rule
├── runner.sh              ← end-to-end reproducibility script (echoes git SHA, KB SHA, model)
└── splits/
    ├── train.json (225)   ← for future RAG hyperparam tuning
    ├── dev.json (40)      ← default eval target
    └── test.json (40)     ← held-out — touch only at release
```

## Versioning policy

- **MAJOR** (`2.0.0`) — scenarios removed or fundamentally rewritten; KB schema change.
- **MINOR** (`1.1.0`) — slices added (e.g., applying v1.1 work items in DIAGNOSIS.md will trigger 1.1.0).
- **PATCH** (`1.0.1`) — metadata fixes, typo corrections, CP relabel deltas that don't shift any reported metric by >0.01.

## Known limitations (read SPEC.md §8 for full list)

1. **All in-distribution + bench scenarios derive from the same KB** — cp_hit measures internal recall, not generalisation. The 4 OOD slices are the real-world generalisation test.
2. **bench_06 IRR audit found 25/155 (16%) CP label revisions needed** — applied in CP-Relabel v2. The remaining 130 unchanged scenarios were only confirmed via `source_concern_id`'s native CP, not independently re-audited.
3. **`mean_tag_precision_at_k` falls when k grows** (precision-at-k denominator scales with k) — this is metric semantics, not a regression.
4. **dev/test per-slice sizes for the 10-sample slices are n=1** — pool slices before reporting per-stratum significance; bootstrap CI recommended.
5. **Two known RAG failure modes shipped with v1.0** (see DIAGNOSIS.md): compound 2-CP queries (hit@5=0.20) and TRIPOD+AI meta-methodology critiques (cp_hit@5=0.20).

## Citation

```bibtex
@misc{mlgg-bench-v1,
  title = {MLGG-Bench: A Benchmark for Peer-Review Concern Retrieval in Medical ML Governance},
  author = {{ML Governance Guard Project}},
  year = {2026},
  version = {1.0.0},
  url = {https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/tree/main/references/retrieval_eval/MLGG-Bench-v1.0}
}
```

## Provenance

This benchmark was constructed via a 24-agent parallel generation pipeline:
- 10 in-distribution slice agents (`indist_155`)
- 4 OOD collector agents (Retraction Watch / OpenReview / TRIPOD+AI / open-peer)
- 10 benchmark-construction agents (fairness / long-tail / compound / negatives / distractors / IRR / adversarial-extended / SPEC / baselines / split)
- 1 CP-Relabel agent (second-pass label QA on indist_155, 25 CP labels corrected)

Total compute: ~14 agent-hours over a 6-hour window.

`baseline_30` (the slice file `references/retrieval_eval/scenarios.json`) predates this benchmark and is preserved unchanged as the smoke-regression slice.
