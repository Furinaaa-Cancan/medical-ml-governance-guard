# W16-B3 — MLGG-F01/F02 Lineage Red-Team

Wave 16 strict-review of `scripts/gates/feature_lineage_gate.py` against the
unnegotiable rules **F01 (label not as feature)** and **F02 (no future
information)**. Five synthetic scenarios in `/tmp/W16_B3_scenarios/`.
Cross-checked against `tests/test_red_team.py::TestFeatureLineageCaseBypass`:
no duplication (that suite only covers `HbA1c` case folding).

## Scenarios designed: 5

| # | Scenario              | Attack vector                                            | Expected fail code                          |
|---|-----------------------|----------------------------------------------------------|---------------------------------------------|
|S1 | LABEL_AS_FEATURE      | `target` / `TARGET` / `tar_get` columns alongside `y`    | `lineage_definition_leakage` (+ proxy)      |
|S2 | DEFINITION_LEAK       | `hb_a1c` + `fasting_glucose_mg_dl` predicting `diabetes` | `lineage_definition_leakage` (+ proxy)      |
|S3 | POST_INDEX_DATETIME   | `outcome_date`, `death_date` predicting `death`          | `lineage_definition_leakage` (+ proxy)      |
|S4 | IMMORTAL_TIME         | `received_drug_X`, `started_on_warfarin` (Suissa 2008)   | `lineage_proxy_leakage`                     |
|S5 | DOCTOR_PROGNOSIS      | SUPPORT2-style `surv2m`, `prg6m` predicting `death_6mo`  | `lineage_definition_leakage` (+ proxy)      |

## Per-scenario result

| # | feature_lineage_gate exit | Failure codes fired                                                                                     | Caught |
|---|---------------------------|---------------------------------------------------------------------------------------------------------|--------|
|S1 | 2 | `lineage_key_normalization_collision`, `lineage_definition_leakage`, `lineage_proxy_leakage`            | ✓      |
|S2 | 2 | `lineage_definition_leakage` (HbA1c), `lineage_proxy_leakage` (glucose, hba1c)                          | ✓      |
|S3 | 2 | `lineage_definition_leakage` (death_date, outcome_date), `lineage_proxy_leakage`                        | ✓      |
|S4 | 2 | `lineage_proxy_leakage` on `^received_`, `^started_on_`, `^prescribed_` patterns                        | ✓      |
|S5 | 2 | `lineage_definition_leakage` (surv2m, prg6m), `lineage_proxy_leakage` on `^surv\d+m$` / `^prg\d+m$`     | ✓      |

## Verdict: PASS (5/5)

`feature_lineage_gate.py` fail-closes on every attack with the expected
canonical code. Norm-collapse (`re.sub(r"[^a-z0-9]+", "", lower())`) handled
case + separator variation in S1 (`tar_get` matches `TARGET`) and S2
(`hb_a1c` matches `HbA1c`) without bypass.

## Cross-gate observations (`leakage_gate.py`, advisory only)

| # | leakage_gate exit | Notes                                                                  |
|---|-------------------|------------------------------------------------------------------------|
|S1 | 2 (strict)        | `suspicious_feature_names` warning on `target`/`TARGET`                |
|S2 | 0                 | **Defense-in-depth gap**: no built-in pattern for `glucose`/`hba1c`    |
|S3 | 2                 | `suspicious_feature_names` on `outcome_date`/`death_date`              |
|S4 | 2                 | `immortal_time_bias_pattern` hard failure (dedicated path)             |
|S5 | 0                 | **Defense-in-depth gap**: `surv2m`/`prg6m` not in built-in regex       |

These are not lineage-gate misses — the lineage gate caught them. They are
opportunities to harden `leakage_gate.py` for projects that omit a
definition spec.

## Wave-N+ fix candidates (ranked by severity)

1. **LOW** — `leakage_gate.py` forbidden_feature_regex lacks
   `surv\d+m|prg\d+m|dnr|dnrday` (SUPPORT2 prognosis aliases) and
   `glucose|hba1c|fasting_glucose` (T2DM definition labs). Add to the
   default regex so projects without a definition spec still trigger.
2. **LOW** — `lineage_key_normalization_collision` in S1 (`target`,
   `TARGET`, `tar_get` all normalize to `target`) is correctly raised, but
   the message could suggest "consider whether these are the same column."
3. **INFO** — Doc note: `--time-col` requires explicit value (not bareword);
   S3 driver bug showed argparse exit 2 can be mistaken for gate fail.

## Artifacts

- Fixtures + reports: `/tmp/W16_B3_scenarios/{S1..S5}_*/{train.csv,test.csv,def.json,lineage.json,lineage_report.json,leakage_report.json}`
- Generator: `/tmp/W16_B3_scenarios/gen.py`
