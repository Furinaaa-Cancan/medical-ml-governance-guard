# W27 External N=1 Plan — Yan 2020 (NMI COVID) + Quanjel 2021 Critique

**Status**: Planning. Awaits USER ACTION (supply Quanjel critique PDF/DOI) before execution.
**Wave**: W27 — transition from "improve answer keys" to "improve the system" with externally-pre-registered ground truth.
**Cross-refs**: `docs/diagnostics/W25_hybrid_phase1_case1_yan2020_covid.md` (commit `db1d7e0`), `docs/diagnostics/W25_hybrid_aggregate.md` (commit `91cba4c`), `references/benchmark/hybrid_v1_spec.md` §Amendment 2.

---

## 1. Why this matters (the circularity we're escaping)

Every MLGG benchmark to date — MLGG-Bench v1.0.x (305 synthetic), W24 (20 NC KB papers), W25 hybrid (8 external papers) — has a circularity bias:

| Benchmark | Where ground truth came from | Circularity |
|---|---|---|
| MLGG-Bench | Hand-labeled by the same team writing the lint/gate rules | Pattern recognition tests pattern recognition |
| W24 (20 NC papers) | KB reviewer concerns the RAG also retrieves from | RAG grades itself |
| W25 (8 external) | `metadata.json` written by the team after eyeballing the paper | "We flagged what we knew to flag" |

**N=1 with an externally-pre-registered critique** breaks this. The Quanjel et al. 2021 (and Barish et al. 2021) external validation of Yan 2020 collapsed the reported AUROC=0.96 to ≈0.48 and published a methodological critique we did not author. If MLGG's hybrid output overlaps with Quanjel's critique on a paper neither we nor MLGG-Bench's labelers had seen the critique for, that's the first non-circular signal we've ever produced.

## 2. Design (single-paper, frozen-protocol)

### Inputs

- **Target paper**: Yan L, Zhang HT, Goncalves J, *et al.* "An interpretable mortality prediction model for COVID-19 patients." *Nature Machine Intelligence* 2020;2:283–288. DOI `10.1038/s42256-020-0180-7`.
- **Target code**: https://github.com/HAIRLAB/Pre_Surv_COVID_19 (already cloned `/tmp/W25_phase1_yan2020` per W25-Phase1-Case1).
- **External critique** (USER ACTION 5 — supply file):
  - Primary: Quanjel MJR et al. "Replication of a mortality prediction model in Dutch patients with COVID-19" (2021). Likely venue *Nature Machine Intelligence* matters-arising or a follow-up letter. **Need PDF/DOI from user.**
  - Secondary (cross-check): Barish M et al. 2021 external validation in NY cohort. **Need DOI.**

### Pre-registration (write BEFORE running MLGG again)

Extract a frozen ground-truth list from the critique **before** consulting MLGG output. Each item is a critique claim, attributed to the critique's section + line number. Example schema (`docs/diagnostics/W27_yan2020_pregistered_gt.json`, to be written):

```json
{
  "source": "Quanjel 2021 DOI:...",
  "extracted_by": "user_or_human_review",
  "extraction_date": "YYYY-MM-DD",
  "claims": [
    {"id": "Q-01", "claim": "no calibration curve reported", "section": "Methods §2.3"},
    {"id": "Q-02", "claim": "no 95% CI on AUROC", "section": "Results"},
    {"id": "Q-03", "claim": "feature pruning 73→3 likely overfit at n=485", "section": "Discussion"},
    ...
  ]
}
```

**Hard rule**: the GT JSON is frozen and committed BEFORE step 3 runs. Any MLGG-side discovery that maps to a Quanjel claim not in this JSON is suspicious (post-hoc rationalization) and excluded from precision/recall.

### Run protocol (Mode B per SKILL.md Audit Routing)

```bash
# L1 lint
python3 -m mlgg_lint check /tmp/W25_phase1_yan2020/ \
  --format json > /tmp/yan2020_l1.json

# L3 RAG — with W27 knobs ON
python3 -c "
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
methods = open('/tmp/yan2020_methods.txt').read()
flags = synthesize_flags_from_rag(methods, adaptive=True, dedup_by_code=True)
import json; print(json.dumps(flags, indent=2))
" > /tmp/yan2020_l3.json

# Match against pre-registered GT (manual, not via ncpr_matcher because GT is
# claim-level not concern-level)
```

### Metrics

- **Recall vs Quanjel GT**: of N pre-registered claims, how many appear in MLGG output (lint flag OR RAG flag whose evidence_text references the same methodological gap)?
- **Precision**: of M total MLGG flags, how many map to a Quanjel claim?
- **Non-Quanjel hits**: flags that don't match any Quanjel claim — these are NOT counted as FP automatically. Triage manually: real-but-Quanjel-missed (good) vs over-flag (bad).

### Success criterion (pre-registered)

- **Headline result**: "MLGG hybrid recovered K/N of Quanjel's pre-registered critique claims on a paper outside the MLGG-Bench KB."
- **Publishable threshold**: K/N ≥ 0.5 with no fabricated claims. <0.5 is informative (tells us what RAG misses on a known-bad paper).
- **Not a measurement target — explicitly informational only.** N=1 cannot validate "MLGG works"; it can only refute "MLGG is purely retrieval-from-team-labels."

## 3. What this N=1 cannot claim

- Generalization (N=1).
- Precision on clean papers (single-paper, all-bad target).
- That hybrid > single-layer (this is one paper; spec §1 Yan case already showed hybrid recall ≥ RAG-only because L1 added 0 unique catches here per W25 case 1).

## 4. Sequencing

1. **USER ACTION 5** (blocked on user): supply Quanjel 2021 critique PDF or DOI (and ideally Barish 2021).
2. Pre-register GT JSON (human read of the critique, NOT automated extraction — automation risks aligning GT with what we expect MLGG to find).
3. Run MLGG Mode B with W27-R1 (`dedup_by_code=True`) and W26-R1 (`adaptive=True`).
4. Compute metrics, document in `W27_external_n1_yan2020_quanjel.md`.
5. Commit + write up. **Do not modify the GT JSON after step 3.**

## 5. Why this is not "just another W25 case"

W25 case 1 (Yan 2020) used metadata.json the same team wrote → 100% hybrid recall is meaningless. This run uses critique-derived GT we did not author → recall against this GT is the first **non-self-graded** signal MLGG has ever produced.

---

**Blockers**: USER ACTION 5 only. The harness (W26-R1 + W27-R1 + W27-R2 + Mode B routing in SKILL.md) is ready.
