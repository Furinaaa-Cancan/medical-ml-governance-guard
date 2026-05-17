# NCPR-Hybrid v1 Spec — true 3-layer integration benchmark

**Status**: Proposed (2026-05-17, user-framed priority)
**Supersedes**: nothing
**Tracking**: `docs/BENCHMARK_OVERVIEW.md`, ADR 0007 Amendment 1, user memory
  `project_hybrid_benchmark_priority.md`

## 1. Why this exists

The MLGG product is **3 layers**:
- **Hard**: 33 fail-closed `scripts/gates/*.py` + 30 `mlgg-lint` AST rules
- **Soft**: RAG over 154-paper / 817-concern peer-review KB
- **Glue**: Claude `/mlgg` reads user intent, orchestrates, synthesizes

**The product claim**: combining all 3 catches what an NC reviewer would flag.

**The measurement gap**: 5 existing benchmarks each test **one layer in isolation**:

| Existing benchmark | What it tests | Layer |
|---|---|---|
| MLGG-Bench v1.0.1 (305 scenarios) | RAG retrieval accuracy | Soft only |
| W24 (20 real NC papers) | RAG + algorithmic matcher | Soft + scoring only |
| support2-benchmark-leaky | gate detects intentional bugs | Hard (gate) only |
| experiments/paper/redteam r1-r4 (40 scripts) | mlgg-lint catches code-level bugs | Hard (lint) only |
| scenarios.json (30 retrieval tests) | RAG retrieval | Soft only |

**No benchmark tests the 3 layers running together against a real
reviewer's verdict.** This spec defines that benchmark.

## 2. Definition (per paper)

For a held-out paper P satisfying entry criteria (§3), the pipeline is:

```
INPUT: P.code_repo, P.methods_text, P.data (if available)
       P.reviewer_concerns (from KB, ground truth)

LAYER 1 — Hard / lint:
  flags_lint = mlgg-lint check P.code_repo
  → set of (rule_id, file:line, code_excerpt, severity) — algorithmic AST

LAYER 2 — Hard / gates:
  for each applicable gate in scripts/gates/*.py:
    if gate's required inputs are present (data / config / split / model):
      flags_gate ∪= gate(P.code_repo, P.data, P.config)
      → set of (gate_name, failure_code, evidence_text, severity)
    else:
      record as "gate skipped (inputs unavailable)"

LAYER 3 — Soft / RAG:
  query = P.methods_text or P.key_methodology_issues
  rag_results = rag_query(query, top_k=20)
  flags_rag = synthesize_flags_from_rag(rag_results)
  → set of (concern_id, paper_id, severity, evidence_text)

COMBINE:
  flags_combined = flags_lint ∪ flags_gate ∪ flags_rag
                   (provenance preserved per flag: which layer emitted it)

MATCH:
  match_all(flags_combined, P.reviewer_concerns)
  → matched / missed / over-flagged sets, with per-layer attribution

SCORE:
  weighted_f1, per_severity_recall, category_coverage,
  per_source_recall (lint / gate / RAG / hybrid)
```

## 3. Entry criteria (paper P qualifies for the benchmark if)

1. ≥3 reviewer_concerns in KB (statistical signal)
2. ≥1 CRITICAL or HIGH severity concern (system stress test)
3. `code_repo` field populated AND repo is publicly downloadable
4. Code is in a language `mlgg-lint` supports (Python; R/MATLAB out of v1)
5. NOT already in any existing eval set (`scenarios.json`,
   `labeled_precision_at_5.json`, `rag-eval-set.yaml`, MLGG-Bench)
6. Publication year ≤ 2025 (KB stability assumption)
7. (Optional) data publicly downloadable — boosts gate coverage but not
   required (papers without data still get lint + RAG layers)

## 4. Per-source attribution (the killer metric)

For each reviewer concern, record which layer caught it:

| Caught by | Meaning |
|---|---|
| `lint_only` | Code pattern was the only signal; RAG / gate missed |
| `gate_only` | Runtime gate fail; lint and RAG didn't see it |
| `rag_only` | Reviewer-concern semantic match; no code/runtime evidence |
| `lint + gate` | Both hard layers agreed |
| `lint + rag` | Code pattern + KB precedent |
| `gate + rag` | Runtime fail + KB precedent |
| `all_three` | Strongest signal |
| `none` | Reviewer raised concern; MLGG missed entirely |

**This breakdown answers**: Is the hybrid actually additive, or is one
layer doing all the work? If `rag_only ≫ gate_only + lint_only`, the
hard layers are decoration. If `none` is large, MLGG has real blind
spots regardless of layer combination.

## 5. Pre-registered metrics

| Metric | What | Why |
|---|---|---|
| `macro_weighted_f1` | Severity-weighted F1 across N papers (CRITICAL×4, HIGH×2, MEDIUM×1, LOW×0.5) | Headline |
| `recall_by_layer` | recall on layer ∈ {lint, gate, RAG, hybrid} | Layer ablation |
| `recall_by_severity` | recall stratified by CRITICAL/HIGH/MED/LOW | High-stakes metric |
| `complementarity_score` | % concerns caught by ≥2 layers vs 1 layer | Hybrid value |
| `unique_lift` | extra concerns caught by hybrid vs best single layer | "Why hybrid?" |
| `precision_at_flag_count` | (TP_match) / (total flags emitted) | Over-flagging cost |
| `gate_coverage_rate` | % of paper's expected gates that actually ran | Data-availability honesty |

**Pre-registered**: thresholds and weights frozen before Phase 3 run.
Any change requires v2 spec + ADR.

## 6. Phased rollout

### Phase 1 — N=1 manual case study (1 hour, NOW)
- Hand-pick 1 NC paper with public GitHub link + ≥3 reviewer concerns
- Manual `git clone`
- Run all 3 layers, manually aggregate, write
  `docs/diagnostics/W25_hybrid_case1_<paper_id>.md`
- **Purpose**: prove the full pipeline runs end-to-end; surface
  integration friction; calibrate expectation

### Phase 2 — N=5 semi-auto mini (1 day)
- Write `scripts/ingest/find_paper_code.py` — DOI → OpenAlex/Crossref
  → GitHub link
- Write `scripts/ingest/clone_paper_code.py` — auto-clone to
  `references/case-studies/<journal>/<paper>/code/`
- Run on 5 papers; aggregate to
  `docs/diagnostics/W25_hybrid_mini5_aggregate.md`
- **Purpose**: validate that auto-ingest works at all; quantify
  per-layer recall on a small N

### Phase 3 — N=30 formal hybrid benchmark (1-2 weeks)
- Scale ingestion to 30 qualifying papers
- Run KB rebuild with `--exclude-papers` (W22-Y1) to truly hold out
  these 30 from RAG's KB
- Run hybrid pipeline; write
  `references/benchmark/hybrid_v1_results.json` + summary md
- Optional: ADR 0008 codifying hybrid as the production benchmark and
  demoting MLGG-Bench / W24 to component-level signals

## 7. Failure modes (planned for)

| Failure mode | Phase impact | Mitigation |
|---|---|---|
| Most papers ship "demo" code not full reproduction | Phase 2+ | Report `gate_coverage_rate` per paper; do not penalize papers where gates can't run |
| Data is rarely public | Phase 2+ | Same — gates needing data → `skipped (no_data)`, not failure |
| Reviewer concerns are paraphrased / summarized | All | Pre-register matcher's cosine threshold via diagnostic sweep (W23-B4 protocol) |
| Code in unsupported language (R/MATLAB) | Phase 1+ | Filter at entry criteria #4; queue as v2 work |
| Repo too large / private / 404 | Phase 2+ | Auto-skip in ingestion; log to `docs/diagnostics/W25_ingest_skipped.md` |
| LLM synthesis (`synthesize_flags_from_rag`) is non-deterministic | Phase 3 | Run 3× per paper, report mean ± std |

## 8. What this benchmark UNIQUELY answers

- "Is `mlgg-lint` (R001-R030) catching things RAG misses?" → `lint_only` count
- "Are 33 gates pulling weight beyond what lint can see?" → `gate_only` count
- "Is the RAG providing reviewer-grade depth beyond what code analysis finds?" → `rag_only` count
- "Is the 3-layer combination actually better than the best 1 layer?" → `unique_lift`
- "Where is MLGG blind regardless of layer?" → `none` distribution

No other current benchmark answers any of these.

## 9. Relationship to existing benchmarks

This benchmark **does not replace**:
- MLGG-Bench v1.0.1 (still the citable retrieval signal, fast CI)
- W24 (still the RAG+matcher case study on 20 NC papers)
- support2-leaky / red-team (still the intentional-fixture detection signals)

It **adds the missing measurement**: the 3-layer hybrid on real papers.

After Phase 3 ships, an ADR should clarify routing:
- per-commit CI: MLGG-Bench (fast)
- per-PR diagnostic: W24 + diagnostic ablations
- per-release / quarterly: NCPR-Hybrid (slow, integrative, defining)

## 10. Open questions (resolve before Phase 3)

1. Hybrid scoring: weighted sum vs. union? (Default: union with provenance)
2. If a concern is caught by ALL 3 layers, is that counted once or weighted higher?
3. How to handle "matched at wrong severity" — does it count as TP, partial-TP, or FN?
4. Should Phase 3 release a public leaderboard format, or stay internal?

## 10b. Amendment 2 — L2 reclassified as pipeline contract (2026-05-17)

**Status**: Accepted (2026-05-17, W25 Phase 1+2 evidence)

### Trigger

W25 ran the hybrid pipeline against 8 out-of-distribution external papers
(Yan, Purushotham, Che, BEHRT, Johnson, Harutyunyan, Kaji, Moor). In every
single case study L2 reported **0 of 33** gates fired. Aggregate over the
8 papers: **L2 = 0/264 gate-paper pairs**. This is not noise — it is a
universal structural finding. Root cause: gates in `scripts/gates/*.py`
require MLGG-instrumented training evidence JSONs (split manifests, fit
provenance, calibration artifacts, ...) that external repositories do not
emit by definition; external code at most ships a `train.py` script, not
the runtime evidence trail the gates consume.

### Decision

1. L2 is **renamed** from "Hard / gates" to
   **"L2 — pipeline contract gates (require MLGG-instrumented training run)"**.
2. The **external-audit hybrid is L1 + L3 only** (lint + RAG). L2 is not
   part of the external-audit pipeline.
3. Spec §4 "Per-source attribution" table — the rows
   `gate_only`, `lint + gate`, `gate + rag`, and `all_three` are **dropped
   for external-audit use** and retained **only for internal
   instrumented-run use** (where MLGG itself ran the training and the
   evidence JSONs exist).
4. Spec §5 metrics — `gate_coverage_rate` is **N/A for external audits**
   and is defined only for instrumented runs.

### What this changes operationally

- The product claim "33 gates audit any paper" is **incorrect** for external
  use.
- Correct claim: **"33 gates audit MLGG-instrumented training pipelines;
  for external paper audits, MLGG uses L1 lint + L3 RAG hybrid."**
- All public docs need this footnote: `docs/BENCHMARK_OVERVIEW.md` (1-line
  cross-reference added in this commit), and ADR 0007 Amendment 1 should
  cross-reference Amendment 2 in its next revision.

### Alternatives considered + rejected

- **Alt A — Build a metadata → evidence-JSON adapter** so gates can run on
  external repos. **Rejected for v1 scope**: requires ingesting training
  data and re-running training pipelines from external repos, which is
  weeks of work per paper and not feasible at benchmark cadence.
- **Alt B — Make some gates "evidence-optional"** (run on code only).
  **Rejected**: each gate's verdict logic depends on its required evidence
  file; an "optional" mode is a degraded gate that emits noise, not
  signal.

### Consequences

- **Positive**: spec honesty restored; marketing materials can be honest
  about what MLGG measures on external papers.
- **Negative**: must rewrite "MLGG is a 33-gate AI reviewer" claims wherever
  they appear in public docs / READMEs / pitch material.
- **Path forward**: L2 contribution to external audits comes via a
  metadata → evidence-JSON adapter (separate workstream, not v1).

### Reversal criteria

If a metadata → evidence-JSON adapter is built and demonstrates **≥10%
gate coverage on external repos** (i.e. ≥3 of 33 gates firing on a
representative external paper), Amendment 2 can be revised and L2 can
re-enter the external-audit hybrid.

### Provenance for Amendment 2

- W25 aggregate: `docs/diagnostics/W25_hybrid_aggregate.md`
  (commit `91cba4c`)
- 8 case study reports: `docs/diagnostics/W25_hybrid_phase*_case*.md`

## 11. Provenance

User-framed as the missing test on 2026-05-17 in conversation:
"我们用了 RAG+Claude 各项指标如何" → "305 跟 20 是什么区别" → "对于真实
的有问题的文章和代码我们测试结果如何" → finally
"33 个门控的硬指标 + NC 同行评审 RAG 结合然后对真实文章去找问题…
这个是我们真实要处理的".

The W24 case-study aggregate (`docs/diagnostics/W24_aggregate.md`,
commit `63d4a54`) demonstrated 53% recall on real reviewer concerns
using only the RAG layer. This spec extends that frame to include the
hard layers and measures the hybrid uplift that would justify the
product claim.
