# G2: `prediction_replay_gate` vs `seed_stability_gate` — semantic boundary decision

## Question
Are these two gates redundant? Should we merge, split, or rename?

## Evidence

### Gate spec (from `scripts/core/_gate_registry.py`)

| Field | `prediction_replay_gate` (#386–399) | `seed_stability_gate` (#452–464) |
|---|---|---|
| Layer | `GateLayer.METRIC_VALIDATION` (6) | `GateLayer.METRIC_VALIDATION` (6) |
| Category | `performance` | `generalization` |
| Description | "Replay predictions from trace and verify metric consistency with evaluation report." | "Verify model stability across random seed variations." |
| `depends_on` | `request_contract_gate`, `split_protocol_gate` | `request_contract_gate`, `split_protocol_gate` |
| Required input | `evaluation_report_file` + `prediction_trace_file` (row-level CSV) + perf policy | `seed_sensitivity_report_file` + perf policy |
| Report output | `prediction_replay_report.json` | `seed_stability_report.json` |
| Aggregation flag | `--prediction-replay-report` | `--seed-stability-report` |

### What each gate ACTUALLY checks at runtime

**`prediction_replay_gate.py`** (537 lines): given a row-level `prediction_trace.csv` (`y_true`, `y_score`, `y_pred`, `selected_threshold`, per-row scope), it
- enforces required columns (`REQUIRED_TRACE_COLUMNS`)
- recomputes the 12-metric panel per split (`accuracy`, `precision`, `ppv`, `npv`, `sensitivity`, `specificity`, `f1`, `f2_beta`, `roc_auc`, `pr_auc`, `brier`, `mcc`)
- requires the recomputed values match `evaluation_report.split_metrics` within `metric_tolerance=1e-6`
- requires `y_pred == (y_score >= selected_threshold)` to be exactly true
- cross-checks row count against the evaluation fingerprint
- it is a **byte-level metric integrity / forensic-replay** check. ONE run, ONE trace.

**`seed_stability_gate.py`** (426 lines): given a `seed_sensitivity_report.json` listing per-seed test metrics,
- enforces `primary_metric == "pr_auc"`
- requires ≥5 seeds (strict) / ≥3 seeds (non-strict)
- forbids `selection_data` referencing test scope; constrains `threshold_selection_split` to `valid`/`cv_inner`/`nested_cv`
- recomputes `mean/std/min/max/range` from `per_seed_results` and verifies declared summary matches
- thresholds: `pr_auc_std ≤ 0.03`, `pr_auc_range ≤ 0.08`, plus `f2_beta` and `brier` bounds
- it is a **stochastic-variance** check. MANY runs, summary across seeds.

These are **operationally distinct** — different inputs, different statistics, different artifacts.

### KB tag distribution (current state, before any G1 patch lands)

| | Count |
|---|---|
| Only `prediction_replay_gate` | 1 |
| Only `seed_stability_gate` | 52 |
| Both | 0 |
| Reproducibility-themed concerns tagged with neither | 33 |

Topical breakdown of the 52 `seed_stability_gate`-only concerns (keyword scan of concern text):

| Actual topic | # concerns |
|---|---|
| Genuine seed-variance ("error bars over seeds", random init) | **1** (`PR-EXP-0200-C04`) |
| Code / data / script / sharing availability ("can't find the code") | **38** |
| Vague reproducibility / dataset-detail gaps | 13 |

### Divergence examples

**`seed_stability_gate`-only — genuine seed-variance (correct tag):**
- `PR-EXP-0200-C04` — "No error bars and confidence intervals... standard practice to train a network several times to determine the influence of the random seed used for training."

**`seed_stability_gate`-only — actually code/data availability (mis-tag):**
- `PR-003-C09` — "I did not find the file with code."
- `PR-003-C10` — "I may have missed something, but I didn't see a link to the code."
- `PR-005-C07` — "There is a general lack of details (data more than code) for the work to be reproduced."

**`prediction_replay_gate`-only:**
- `PR-113-C03` — "No prospective validation of SepsisFormer in real-time ICU settings..." (arguably mis-tagged — this is a prospective-validation concern, not a metric-replay concern).

**Both:** zero.

### Root cause of the mis-tagging

`scripts/review/backfill_peer_review_gates.py` line 39 and 265–266:

```python
"reproducibility": ["seed_stability_gate", "execution_attestation_gate"],
("reproducibility", ["seed_stability_gate", "execution_attestation_gate"]),
("irreproducible", ["execution_attestation_gate", "reporting_bias_gate"]),
```

Any concern mentioning "reproducibility" gets `seed_stability_gate`. That keyword maps the broad reviewer concept onto a gate that only checks one narrow sub-question (seed variance). F4 noticed the symptom; the cause is this heuristic.

### Upstream docs say...

- `README.md` / `README_EN.md` (lines 1069/1072 and 1062/1065): both gates listed side by side in the gate table. Replay = "row-level prediction trace metric replay (tolerance 1e-6)". Seed stability = "multi-seed variance (PR-AUC std ≤ 0.03, strict ≥ 5 seeds)". Descriptions are crisp and non-overlapping.
- `SKILL.md` / `CLAUDE.md`: no specific mention of either gate. They are treated as just two of the 33 fail-closed gates.
- `references/contracts/`: no gate-level contract files reference these names — contracts speak to artifacts (evaluation_report, seed_sensitivity_report), which are already disjoint.

## Analysis

### Are they actually different?

**Yes — unambiguously different.** They consume different artifacts, run different math, and fail on different evidence. Replay answers "does the reported metric match a forensic re-computation of one model's predictions?" Seed stability answers "does PR-AUC vary by more than 3% std across ≥5 retrainings?"

The "overlap" F4 observed is **not** in the gate semantics — it is **entirely in the KB labels**, produced by a too-broad keyword map in `backfill_peer_review_gates.py`. There is no design problem to fix in the registry; there is a label-quality problem in the KB and an under-served conceptual bucket ("code / data / artifact availability for re-execution").

### What is MISSING from the gate set?

The 38 mis-tagged concerns reveal a real gap: **"can this paper be re-executed at all?"** — code links, data access, dependency manifests, container image. MLGG has `execution_attestation_gate` for runtime attestation, but that gate verifies an *attestation artifact*, not the upstream availability question. The backfill author conflated "no reproducibility" (which means "no public code") with "seed instability" (which means "high variance across runs") because no clean target existed for the former.

## Recommendation

### **Option B — Keep both, sharpen boundary (with KB-tag remediation)**

The gates themselves are well-designed and non-redundant. Do NOT merge.

What needs to happen:

1. **Add clarifying docstring to each in `_gate_registry.py`** (file: `scripts/core/_gate_registry.py`):
   - `prediction_replay_gate`: append "Single-run, byte-level forensic recomputation; does NOT cover stochastic variance or code availability."
   - `seed_stability_gate`: append "Multi-run stochastic variance only; does NOT cover code/data availability or single-run forensic replay."

2. **Fix the keyword map in `scripts/review/backfill_peer_review_gates.py` (lines 39, 265–266)** — the root cause of the mis-tagging:
   - `"reproducibility"` → drop `seed_stability_gate`. Map only to `execution_attestation_gate` (and possibly a new tag, see below). Keep `seed_stability_gate` mapped from `"seed"`, `"random_state"`, `"random init"`, `"error bars over runs"`, `"multi-seed"`.

3. **Re-run G1's KB tag pass after fixing the map**, so the 51 mis-tags rebalance. Expected post-fix distribution: ~1 seed-only, ~30+ on `execution_attestation_gate` / a code-availability bucket, ~1 on replay.

4. **Add a per-gate KB exclusivity unit test** (e.g., in `tests/test_peer_review_kb.py`): assert that no concern carries both `prediction_replay_gate` AND `seed_stability_gate` unless the concern text explicitly mentions both row-level metric replay AND seed variance (effectively asserting the boundary stays clean).

5. **Optional (out of scope for this decision, flag to backlog)**: introduce a `code_availability_gate` or `artifact_availability_gate` for the 38 orphaned concerns. F4 / KB curation would own that, not this taxonomy decision.

### Why not A (merge) or C (rename + split)?

- **A (merge into `reproducibility_gate`)** would destroy two well-targeted, working gates and force a 537-line implementation to handle two unrelated input artifacts (CSV trace + per-seed JSON). The "redundancy" is a label-quality illusion, not a code-design problem. Migration cost (rename registry, edit 29 script references, update READMEs, regenerate KB tags, rewrite tests) buys nothing.
- **C (rename + split)** would also rename and ripple-change 29+ files for cosmetic clarity. The current names are reasonable; only the KB labels are misleading. Cheaper to fix the labels.

### Implementation hint for Option B

Files to touch (docs-only path):

- `scripts/core/_gate_registry.py` — 2 description-string edits (lines 389 and 455).
- `scripts/review/backfill_peer_review_gates.py` — 1 tuple deletion at line 39, 1 tuple deletion at line 265; optionally add a new `"code_availability"`/`"data_availability"` keyword group.
- `tests/` — add 1 new exclusivity test (~20 LOC).
- Re-run `scripts/review/backfill_peer_review_gates.py` (or whatever G1 is using) to refresh `references/case-studies/peer-review-kb.json`.

Total: 3 files modified, ~30 LOC. Zero gate behavior change. KB tag quality rises sharply.
