# ADR 0003 — Wiring remaining unused analysis tools into gates

- Status: Accepted (subgroup_dca wired; generate_model_card and temporal_drift_analysis deferred)
- Date: 2026-05-17
- Author: W13-T0
- Related: W12-B5 (analysis-tool inventory audit), W13-T0 (this ADR + subgroup_dca wiring)

## 1. Context

W12-B5 audited `scripts/core/_gate_utils.py` and adjacent analysis modules
and found **21 analysis tools** of which **11 were "library-only"** — they
had public APIs and unit tests under `tests/test_analysis_tools.py` but no
gate (or any other CLI entrypoint) actually invoked them. Library-only
tools fail silently: pipelines never trigger them, so any methodological
defect they would catch slips through to the artefacts the publication
gate signs off on.

W13-T0 closed the most pressing gap by wiring `subgroup_dca` into
`fairness_equity_gate.py` as an opt-in / strict-auto check (commit
recorded by the wave). This ADR records the **two remaining critical
gaps** so future waves don't lose them — both touch surfaces large
enough to warrant their own task rather than being smuggled into a
broader change.

### W13-T0 — closed gap (`subgroup_dca`)

- Surface: new `--subgroup-dca` flag on `fairness_equity_gate.py`
  (auto-enabled when `--strict`).
- Inputs: `--prediction-trace <csv>` with `y_true`, `y_score`, and a
  user-named subgroup column (`--subgroup-dca-column`).
- New failure code: `fairness_subgroup_dca_negative` — any subgroup
  whose best net benefit on the 0.05–0.20 threshold band is < 0.
- Tests: `tests/test_fairness_subgroup_dca.py` (6 tests).

The two open gaps below follow the same general shape (existing tool +
new CLI wiring + 1 failure code + tests) but each implies a non-trivial
contract change.

## 2. Open Gap 1 — `generate_model_card` → `publication_gate`

### Problem

`generate_model_card` produces a TRIPOD+AI-aligned model-card payload
summarising intended use, training cohort, performance, fairness, and
limitations. The function is unit-tested but no gate emits it. The
`publication_gate` (W11-F2 area) is the natural home: it is the
fail-closed checkpoint that fronts every publication-grade artefact
release. Today the publication gate validates that *other* artefacts are
complete but never produces a model card, so every published model
ships without the standardised summary the gate is meant to enforce.

### Effort estimate

~1 day for an experienced contributor:

- 30 min: read `generate_model_card` signature and pull the inputs the
  publication_gate already has on hand (eval report, fairness report,
  validation cohort manifest).
- 1–2 h: add `--model-card-output <path>` arg to publication_gate, call
  the tool, validate the resulting JSON against `model_card.json`
  schema (which needs to be authored — see below).
- 1–2 h: author `references/schemas/model_card.json` (or
  `model_card.schema.json`) so the output is contract-checked and the
  downstream consumers know what to expect.
- 1 h: add tests covering (a) happy path emits a valid card, (b)
  missing eval/fairness input is a clean failure with remediation,
  (c) malformed card payload fails with a typed code
  (`publication_model_card_invalid` or similar).
- 30 min: register remediation, update SKILL.md / ARCHITECTURE.md if
  they enumerate publication-gate side-effects.

### Why deferred

- **Hard rule:** W13-T0 must not modify `publication_gate.py` (W11-F2
  area). The whole point of carving this out is that a parallel wave
  owns that file.
- **Schema authoring:** introducing `model_card.json` is a contract
  consumers will depend on — it deserves its own design review rather
  than being smuggled into a fairness wave.

### Recommendation

Spin a dedicated W14 (or later) task: `feat(publication): emit model
card via generate_model_card`. Block on the W11-F2 publication-gate
refactor landing first so the new code doesn't immediately rebase-rot.

## 3. Open Gap 2 — `temporal_drift_analysis`

### Problem

`temporal_drift_analysis` detects distribution / performance drift over
calendar time (PSI per feature, ΔAUROC across time windows, p-values for
the null of "no drift"). It has no home gate. MLGG's scope so far has
been **pre-deployment** retrospective-cohort governance; post-deployment
monitoring is intentionally out-of-scope. But temporal drift in the
retrospective cohort itself (e.g., a 10-year EHR pull where the model
performs poorly on the most recent 2 years) is a real pre-deployment
concern that no existing gate catches.

### Two options

#### Option A — new `deployment_monitor_gate.py`

- **Heavy.** Implies committing to a post-deployment monitoring scope
  MLGG doesn't otherwise cover. Drags in additional tools
  (concept-drift detectors, alerting thresholds, time-window CI
  configuration), policy decisions (how often is the gate re-run?
  who consumes the failures?), and docs (a whole new chapter in
  SKILL.md / ARCHITECTURE.md).
- **Risk:** half-built deployment-monitoring surface invites users to
  assume MLGG covers production drift, which it then doesn't. False
  reassurance is worse than the current explicit gap.

#### Option B — opt-in `--temporal-drift` flag on `model_audit_gate.py`

- **Lighter.** Fits the existing surface: `model_audit_gate` already
  consumes the prediction trace and metadata about training/eval
  windows. Adding `--temporal-drift` as an opt-in flag (default OFF,
  same pattern as W13-T0's `--subgroup-dca`) wires the tool without
  expanding MLGG's scope claim.
- **Failure code:** `model_audit_temporal_drift_detected` —
  fails when ΔAUROC across the earliest vs latest time window
  exceeds a configurable threshold (default 0.05).
- Inputs: prediction trace + `--time-column <colname>` + optional
  `--n-windows <int>` (default 3).
- ~0.5–1 day total.

### Recommendation

**Option B.** It matches the W13-T0 design pattern (opt-in, strict-auto,
piggybacks an existing gate), avoids scope creep, and unblocks the
temporal-drift signal for retrospective cohorts that span many years
without committing to post-deployment monitoring as a product surface.

### Why deferred from W13-T0

Even Option B touches `model_audit_gate.py` — a busy file with its own
in-flight refactors — and adds a new mandatory column convention
(`time_column` in the prediction trace) that should be coordinated with
whatever wave owns the trace schema. Doing it inline in W13-T0 would
either (a) bloat this wave well past its scope or (b) merge-conflict
with parallel work.

## 4. Decision

| Tool | Decision | Wave |
| --- | --- | --- |
| `subgroup_dca` | **Wired** into `fairness_equity_gate` | W13-T0 (this wave) |
| `generate_model_card` | **Defer** to dedicated wave; wire into `publication_gate` after W11-F2 lands | W14+ |
| `temporal_drift_analysis` | **Defer** to dedicated wave; **prefer Option B** (opt-in flag on `model_audit_gate`) | W14+ |

The other 8 of the 11 library-only tools surfaced by W12-B5 are
lower-priority and are tracked in the W12-B5 inventory directly; they
are not duplicated here to avoid this ADR drifting into a generic
backlog dump.

## 5. Consequences

- Future maintainers see, in one place, *why* `generate_model_card` and
  `temporal_drift_analysis` look dormant — they are queued, not dead.
- The W13-T0 wiring sets the canonical opt-in / strict-auto pattern
  (`--<tool> [+ inputs]` opt-in, auto-on under `--strict`, warn-not-fail
  when inputs are missing outside strict). Future tool wirings should
  match this pattern unless they have a documented reason not to.
- This ADR closes W12-B5's open question "what do we do with the
  library-only tools?" with a concrete plan for the three highest-value
  gaps.

## 6. References

- W12-B5 inventory audit (analysis-tool catalogue)
- `scripts/core/_gate_utils.py::subgroup_dca` (Vickers AJ, Elkin EB.
  *Med Decis Making* 2006;26:565–574)
- `scripts/core/_gate_utils.py::generate_model_card` (TRIPOD+AI 2024)
- `scripts/core/_gate_utils.py::temporal_drift_analysis`
- ADR 0001 — `_mmr_breakdown` consumer (pattern: library-only finding
  → directed wiring task)
