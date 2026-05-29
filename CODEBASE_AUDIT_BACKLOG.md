# ML-Leakage-Guard — Systemic Debt Audit Backlog

**Scope:** read-only hunt for 5 defect classes (dead-as-live, docs/code mismatch, measures-wrong-thing, latent correctness bug, stale/drift) across the whole repo, seeded by the RAG investigation pattern. 16 hunters + 3 verifiers; this backlog keeps only CONFIRMED/PARTIAL findings, deduplicated. **0 refuted.** Severities are the verifiers' corrected values.

## Systemic themes
1. **Fail-open / fail-by-crash on certifying & security paths** — controls documented as fail-closed silently PASS (or crash to a generic exit) on missing/malformed evidence. Most dangerous cluster.
2. **Dead-code-documented-as-live** (the gate_rag_bridge pattern) — 8+ instances of framework/factory/security helpers with zero prod callers but advertised/tested/mandated as live.
3. **Measures/reports-the-wrong-thing** — evals/benchmarks/tests validate a non-shipping path or artifact.
4. **Non-raising test helper = silent green** — `assert_true` copy-pasted into 3 smoke files never raises; ~110 tests pass regardless of assertions yet count toward CI green.
5. **Pervasive stale counts / drift** (the 375→817 pattern) — lint 28-vs-30, subcommands 28/29-vs-30, NHANES 58K, LOC figures, flat `scripts/mlgg.py` path drift.

---

## MUST-FIX

### Security & certification (fail-open / fail-by-crash)
- **scripts/gates/security_audit_gate.py:89-97,143-152,180-189,353** — fail-OPEN control documented (line 3) as fail-closed. `_security` ImportError, empty/wrong `--model-dir`, or missing `.manifest.json` each degrade to a non-failing WARNING; `should_fail = bool(failures) or (args.strict and bool(warnings))` and the orchestrator never passes `--strict`, so exit 0 PASS with signature/integrity/dependency checks disabled. **Fix:** make the three integrity checks unconditionally fail on ImportError (or require explicit `--skip-security`); treat zero-models-found as a failure; promote missing manifest to a failure for publication-grade runs.
- **scripts/core/_security.py:362** — `bytes.fromhex(sig_payload.get("signature",""))` is OUTSIDE the try (only the JSON load is guarded). An adversarial-but-parseable `.sig` with a non-hex signature raises uncaught ValueError, escapes `security_audit_gate.py:100` main() → exit 1 + traceback. Fail-open-by-crash. **Fix:** wrap fromhex+HMAC compare, return `{verified:False, reason:"signature_field_malformed"}`.
- **scripts/gates/publication_gate.py:736-743** — `_tier_passed` does `if r is None and g not in files: continue`, treating absent optional component reports as satisfied. `L1_GATES` includes split_protocol/definition/lineage/tuning/imbalance/missingness/covariate_shift (all argparse `default=""`), so a partial-evidence run earns an L1 "core leakage audit" tier with leakage detectors never run. (`self_critique_gate.py:221` has identical `if report is None: return`.) **Fix:** make a missing tier-member gate fail the tier; drop the `g not in files` escape.
- **scripts/gates/publication_gate.py:714-743 vs scripts/reporting/generate_compliance_certificate.py:273-283** — two authoritative tier evaluators disagree precisely on fail-open vs fail-closed; same evidence dir → publication_gate `L1` but certificate `BELOW_L1`. **Fix:** make publication_gate fail-closed by sharing the certificate's require-all-present tier sets as single source of truth.
- **scripts/reporting/generate_compliance_certificate.py:181-190** — `_get_signing_key` fails OPEN: a set-but-invalid-hex `MLGG_SIGNING_KEY` raises ValueError that is silently `pass`ed → guessable `mlgg-v1-{hostname}-{user}` derived key; no length validation (1-byte valid-hex key accepted). Used for sign AND verify. **Fix:** raise/exit on ValueError, require 32-byte key, only derive when env var wholly unset (with stderr warning).

### Correctness
- **scripts/training/train_select_evaluate.py:3818-3837** — `choose_model_one_se` docstring says n_folds<2 (production valid-selection path) makes "all candidates eligible, simplest wins", but code makes only the best/exact-tie eligible; parsimony silently disarmed while docs claim it ran. (Verifier downgraded to SHOULD-FIX pending re-run; docstring/behavior inversion confirmed.) **Fix:** correct docstring or set threshold to -inf in the branch; add an n_folds=1 test.
- **scripts/orchestration/triage.py:38-48 + run_dag_pipeline.py:893-923** — enabling `--triage` (advertised as safer) turns a clean no-test skip into a hard crash: split_protocol_gate is MANDATORY (never skipped), legacy auto-skip disabled under triage, gate invoked without required `--test` → exit 2. **Fix:** special-case split_protocol_gate in triage's no-test rule, or drop the `and not _triage_active` guard.

### Measures / reports the wrong thing
- **scripts/reporting/evidence_digest.py:73-85,89** — reads metrics from top level but producer nests under `evaluation_report['metrics']` (train_select_evaluate.py:7644); wrong key names `brier_score`/`f_beta` vs real `brier`/`f2_beta`; reads `summary.selected_model_name` but gate writes `selected_model_id`. So `## Key Metrics` and `## Model` render empty on every real run; unit tests pass only against fabricated fixtures. **Fix:** read nested dict + correct keys + `selected_model_id`; fix fixtures.
- **scripts/reporting/generate_audit_report.py:8,186-189,290-292,923** — claims "TRIPOD+AI 2024 (27 items)" and banner "| TRIPOD+AI items | 27 |", but `TRIPOD_REQUIRED_ITEMS` is 17 and coverage divides by 17 → can read 100% under a 27-item banner. Publication-grade false claim. **Fix:** report 17-of-27 or expand to 27.
- **scripts/rag/evals/harness.py:35-42,87-90 + run_eval.py:94** — assert hybrid IS the production gate-failure path, but the gate ships BM25-only (`_gate_framework.py:274,280,293`); sibling `gate_path_eval.py:11-24` explicitly contradicts. **Fix:** rescope claims to the offline rag_query/llm-audit path; cross-link gate_path_eval.py.
- **references/retrieval_eval/gate_path_precision_at_5_v1.json:1055-1058** — ships discredited pre-fix numbers (0.272 / -0.367 / 11) that METRIC_CONTRACT.md:115 labels "inflated"; current code re-runs to 0.244/-0.394/0. **Fix:** regenerate the artifact.
- **scripts/diagnostics/validate_gate_code_alignment.py:26-78** — `validate_*`-named tool whose `main()` has no return/exit, always exits 0 despite finding 75 unreachable + 19 untested codes; wired into no CI. Fail-open validator. **Fix:** return 2 on eval_only codes and `raise SystemExit(main())`, or rename to `report_*`.
- **scripts/rag/evals/run_ncpr_benchmark.py:58,387,38** — `DEFAULT_HOLDOUT` points to a non-existent file; quickstart AND `--max-papers 0` smoke mode crash with uncaught FileNotFoundError before max_papers is consulted. **Fix:** guard the read with graceful exit-2 or ship the fixture.

### Dead-code-as-live / false guidance
- **scripts/diagnostics/gate_applicability.py:7-10** — "Used by:" lists run_dag_pipeline.py and mlgg.py (both grep 0); only generate_audit_report.py imports it, and only when `prediction_type != 'binary'` — never exercised in the binary-only product. **Fix:** delete the false caller bullets.
- **references/operations/error-knowledge-base.json:1049** — ERR-065 mandates "use add_common_arguments() ... or subclass GateBase"; the fn is dead and `GateBase` does not exist. **Fix:** rewrite to the real build_report_envelope/print_gate_summary contract.
- **docs/ARCHITECTURE.md:46,61,107-114,228** — narrates the deleted gate_rag_bridge hedge layer (`_is_weak_match`/`_is_low_confidence`/`format_for_gate_report`, none defined in scripts/) as live; module is a 51-LOC shim. **Fix:** point at scripts/rag/_enrich.py; note removals.

### False benchmark / pervasive count drift
- **ARCHITECTURE.md:149 + README.md:1384,1628** — SUPPORT2 published 0.892/0.635/0.745 matches NONE of the committed evidence (0.789/0.610/0.955); isolated false benchmark headline. **Fix:** use evidence values or regenerate.
- **plugin README.md:3 + README_EN.md (7 lines) + SKILL.md:24,157 + ARCHITECTURE.md:19,68 + docs/reference/LINT_RULES.md:1,5** — "28 rules (R001-R028)" vs registered 30 (R001-R030); README badge says 30 (self-contradiction); stat-checker guards only the badge; LINT_RULES omits R030. **Fix:** global 28→30, document R029/R030, fix the `#r001-r027` anchor, extend the checker to prose.
- **scripts/orchestration/mlgg.py:815-828 + docs/PRODUCTS.md:45 + ARCHITECTURE.md:72 + README_EN.md:1198 + SKILL.md:23,48,129 + README.md:1677** — subcommand count stated 28/29/28+/21, all wrong/inconsistent; actual `len(COMMANDS)=30`, review group=8. **Fix:** reconcile to one canonical count + add a test asserting doc number == len(COMMANDS).

### Tests measure nothing
- **tests/test_gate_smoke.py:122-127** — `assert_true` never raises; ~49 of 51 funcs pass regardless of assertions; run by ci-unit AND ci-overnight, counted green. **Fix:** make it raise.
- **tests/test_play_smoke.py:25-31** — same; 59 funcs / 195 assert_true calls; collected by ci-overnight full pytest. **Fix:** make it raise; run as real pytest module.

---

## SHOULD-FIX

### Dead / unwired framework & security helpers
- **scripts/core/_gate_framework.py:351,370** — add_common_arguments / add_input_file_argument: zero callers, advertised "shared by all gates"; W15_A5 audit (2026-05-17) already flagged, unactioned. Delete or wire.
- **scripts/core/_gate_framework.py:383,398** — sanitize_cli_args / validate_input_files: tested + in dev guide, zero prod callers; security-relevant false confidence. Wire or delete.
- **scripts/core/_security.py:657-684** — SecureModelLoader._ALLOWED_MODULES/_is_module_allowed: dead allowlist diverging from the live broader one (omits pandas/joblib). Delete.
- **scripts/core/_security.py:381-427** — safe_path startswith over-matches ('/etcetera' vs '/etc'); _FORBIDDEN_COMPONENTS dead. Compare path components. (capped: zero prod callers)
- **scripts/core/_security.py:387** — safe_path advertised + red-team-tested as the path-traversal sandbox, zero prod callers; gates use bare `Path().resolve()`. Wire or drop the claim.
- **scripts/codebooks/nhanes_codebook_lookup.py:932-973** — dead duplicate get_codebook factory, drifted from the live codebook_factory one. Delete.

### Docs/code mismatch & latent bugs
- **scripts/core/_gate_framework.py:352** — docstring lists removed `--timeout`; gate_timeout hint (line 157) references it. Drop both.
- **docs/reference/GATES.md:57-60** — finish()/to_float() misattributed to _gate_framework.py (real: per-gate + _gate_utils.py:416).
- **scripts/training/split_data.py:1105,997-1003,738** — grouped_temporal `temporal_order=true` is a tautology (fail → early return before report write). Persist measured boundary times.
- **scripts/training/split_data.py:27,736** — docstring overstates per-row temporal ordering vs patient-earliest-time enforcement.
- **scripts/codebooks/nhanes_codebook_lookup.py:5 + DATASETS.md:218** — "58K+ variables" vs 15.7K local / ~3.9K loaded.
- **scripts/gates/cohort_definition_gate.py:1786** — short tokens 'ckd'/'depression' fail the KB fuzzy matcher → silent [] for 2 advertised diseases. Map to canonical keys. (PARTIAL: matcher repro not re-run)
- **scripts/rag/retrieval/hybrid.py:35-39** — free-text effective-weight docstring quotes pre-W13 values (0.714/0.214/0.071 vs real 0.182/0.545/0.273).
- **scripts/rag/retrieval/hybrid.py:690** — comment "WEIGHT_BM25=0.3" vs config 0.45.
- **README.md:234** — "dense_weight=0.5 ... Wave 12 计划 demote" but W13-P0 already shipped 0.10 (and line 264 says so).
- **scripts/rag/evals/run_eval.py:130** — truthy-or drops a legitimate 0.0 _final_score, biasing mean upward.
- **scripts/reporting/report_health_check.py:27-29 (+evidence_digest.py:106-110)** — empty-registry ImportError → empty non-failing health report (fail-open).
- **scripts/gates/publication_gate.py:196-203** — validate_component_status skips the guard when failure_count is missing/None/non-int under a pass claim.
- **scripts/gates/request_contract_gate.py:922-930** — report self-attests `time_slices.skipped` to suppress the temporal completeness failure; require corroborating justification.
- **scripts/review/backfill_peer_review_gates.py:613** — hard-codes contract_version v1.2; live is v1.4; any future --apply silently downgrades. Make version bump monotonic + real run date. *(MUST-FIX in verifier; kept here adjacent to its sibling docstring item — treat as MUST-FIX.)*

### Drift / stale framing
- **scripts/review/backfill_peer_review_gates.py:3-5** — "272 of 375 / 72% empty" vs live 817 / 0 empty.
- **scripts/orchestration/run_endurance_test.py:51-72** — 5/6 config constants dead; advertised sweeps not wired. (PARTIAL: enumeration off by one)
- **scripts/orchestration/run_endurance_test.py:3-23,644-651** — phase labels misrepresent the matrix (3×10, 2×12, 3×3, test counts).
- **plugin/mlgg_lint/ast_utils.py:146-152** — name-only taint → leakage false negatives on generically-named splits (R002/R003/R005). (PARTIAL: code path confirmed, R002 repro not re-run)
- **plugin/mlgg_lint/rules/r030_nan_bypass.py:144** — gate-scope-only rule counted in user-facing "30 rules"; can never fire for external code. Disclose or make configurable.
- **scripts/diagnostics/mlgg_web.py:5-14** + **cross-cut flat-path drift** — scripts/mlgg.py / mlgg_web.py / evidence_digest.py / peer_review_lookup.py cited at flat paths post-reorg; copy-paste fails. Repo-wide sweep.
- **scripts/rag/evals/run_ncpr_benchmark.py:26-43 + ncpr_ablation.py:39-99** — ~140 LOC dead stub fallbacks framed as active "wave-22 parallelism". Delete or relabel.
- **docs/diagnostics/W19_E3_adr_gap_audit.md:34** — "BGE-large" + false ARCHITECTURE.md citation; real model bge-small.
- **SKILL.md:285** — "23 sklearn families + 4 backends" double-counts (23 is the total incl. the 4 backends).
- **ARCHITECTURE.md:15,22,13,14** — stale repo-layout file counts (diagnostics 10 vs 33; tests 123/4760 vs ~199-281/5134). (PARTIAL)
- **README.md:1526 / README_EN.md:1243** — gate_rag_bridge "204 LOC" vs actual 51-LOC shim.
- **tests/test_onboarding_smoke.py:28-33** — same non-raising assert_true; collected as no-ops by ci-overnight.
- **tests/test_rag_eval_set.py:132-163** — xfail(strict=False) rot: recovery XPASSes silently, future regression invisible.
- **references/case-studies/rag-eval-set.yaml:69 + check_kb_no_dangling.py** — PR-040-C01 dangling (guard exits 2) but guard wired into no CI. Fix id + add hook.

---

## NIT
- docs/reference/GATES.md:52 / scripts/gates/__init__.py — exit-code contract says "1 = input error" but io_error returns exit 2 (fail-closed-safe).
- scripts/training/schema_preflight.py:420,443 — finish() narrows the project-wide strict contract (omits `args.strict and warnings`).
- scripts/codebooks/codebook_factory.py:33-39 — 4 dead `_DATASET_KEY_TO_CYCLE` entries unreachable via `_DS_KEY_MAP`.
- scripts/review/add_robustness_permutation_gates.py:43-44 — deprecated substring matcher in a completed one-shot.
- scripts/review/peer_review_lookup.py:87-104 — 4/33 gates have 0 KB concerns; `--gate X` indistinguishable from a typo.
- scripts/review/peer_review_lookup.py:4-9 / scripts/reporting/evidence_digest.py:10-12 — stale flat-path docstring examples.
- scripts/rag/index/cache.py:118-121 — docstring overstates joint atomicity of the two-file write (safe downstream).
- scripts/rag/index/cache.py:25 — kb_sha256 exported with a no-reinvention docstring but builder.py:280 reinvents it inline.
- scripts/orchestration/triage.py:339 — triage_report public but test-only.
- plugin/mlgg_lint/ast_utils.py:135-152 — record_split docstring claims positional logic it doesn't use.
- plugin/mlgg_lint/rules/r028_omics_feature_prefix.py:48 — visit_List only; misses tuple/set feature lists.
- plugin/build/lib/mlgg_lint/ — stale 27-rule build artifact (untracked/gitignored, regenerable).
- SKILL.md:105 / mlgg.py:828 — "7 review commands" vs 8 (off-by-one).
- references/retrieval_eval/METRIC_CONTRACT.md:14 vs :105 — 0.494 vs 0.639 coexisting for mean_labeled_P@5 (footnote reconciles).
- scripts/diagnostics/check_readme_stats.py:507,524-525 — stale "105 curated" comments (code computes 154 dynamically).
- scripts/core/_security.py:259-283 / .mlgg_model_key — key-gen TOCTOU window + on-disk 0o700 vs intended 0o600 (gitignored, untracked).
- README_EN.md:1180 vs ARCHITECTURE.md:10 — gates dir "(34)" vs "(33 files)" parenthetical drift.
- tests/test_retrieval_eval_harness.py:140-150 — skipif + non-strict-xfail = permanently inert spec.

---

## Verified-clean (do NOT re-flag)
finite_float/to_float NaN/inf guards hold everywhere; 33-gate registry matches docs; 9-layer enum complete; gate_rag_bridge already remediated to a documented 51-LOC shim; dense.py/hybrid_rank live via the offline rag_query path; USE_DENSE_CORROBORATION is an intentional A/B branch; KB ground truth 335 papers/817 concerns/0 empty/v1.4 consistent; no eval/exec/shell=True in prod; .mlgg_model_key gitignored & untracked; fit-scope/leakage in training is clean (per-fold pipelines, train-only encoders); execution_attestation signature verification fails closed; CKD/NHANES/RHC/Sepsis benchmark AUCs match evidence.