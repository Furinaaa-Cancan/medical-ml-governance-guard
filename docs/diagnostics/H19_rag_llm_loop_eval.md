# H19: RAG + LLM Loop Eval

## Method

Self-audit: I (Claude) acted simultaneously as the production synthesis-LLM
(Phase 1) and the adversarial auditor (Phase 2). To reduce self-confirmation
bias I generated all five narratives before re-reading the audit checklist,
and I marked FAIL on any check where I had to argue myself into PASS.

Five scenarios spanning RICH / WEAK / ZERO retrieval quality, retrieved via
`rag_context_for_failure(gate, codes, top_k=5)` and rendered with
`format_for_gate_report(concerns, gate_name=gate)`. ZERO scenario uses a
`rag_optional=True` gate (`self_critique_gate`) so the rendered markdown is
empty by design. WEAK scenarios use synthetic off-topic failure codes
(`nonexistent_code_xyz`, `unicorn_rainbow_violation`) against real gates to
force low semantic similarity while still hitting the gate filter.

Full Phase-1 inputs + narratives saved at:

- `/tmp/h19_phase1_inputs.json` — retrieval payloads + rendered markdown per scenario
- `/tmp/h19_phase1_narratives.md` — the five 100-200 word synthesis narratives

## Scenarios used

| # | Label | Gate | top-1 score | n_hits | Quality |
|---|---|---|---|---|---|
| 1 | RICH-1 | fairness_equity_gate | 0.731 | 5 | RICH |
| 2 | RICH-2 | tuning_leakage_gate | 0.702 | 5 | RICH |
| 3 | WEAK-1 | calibration_dca_gate | 0.308 | 5 | WEAK |
| 4 | WEAK-2 | leakage_gate | 0.304 | 5 | WEAK |
| 5 | ZERO  | self_critique_gate (rag_optional) | n/a | 0 | ZERO |

Note on WEAK construction: every real scenario in
`references/retrieval_eval/scenarios.json` returns top-1 > 0.54 with n=5,
because the gate filter alone pads results to top_k. To create a stress test
for the "weak hits → over-claim" failure mode I substituted synthetic
nonsense failure codes; the ranker still returns 5 gate-filtered concerns but
3-4 of them score at the severity_fallback floor (0.020-0.025). This
faithfully simulates "the RAG returned junk but the LLM has to handle it".

## Phase 1 narratives

(Verbatim from `/tmp/h19_phase1_narratives.md` — the input markdown for each
scenario is in `/tmp/h19_phase1_inputs.json`; reproducing the full ~3kB
markdown for each here would bloat the report. Each narrative is reproduced
in full below.)

### RICH-1 — fairness_equity_gate

> The fairness_equity_gate failed because the manuscript reports no subgroup
> performance analysis despite a heterogeneous cohort, and the aggregate metric
> masks a demographic-parity gap that the peer-review KB has flagged repeatedly
> across modalities. The KB returned five strongly-matching precedents (top-1
> score 0.73). Two are direct hits on the same failure mode: PR-EXP-0086-C10
> asked authors to address ethnicity-stratified disparities and propose
> concrete mitigation; PR-EXP-0119-C01 (HIGH) flagged dermatology validation
> that under-represented Fitzpatrick V-VI skin tones. PR-111-C05 (MEDIUM) and
> PR-EXP-0110-C08 (MEDIUM) requested age/sex/HIV and sex-stratified subgroup
> analyses respectively. In all four of these cases authors responded
> substantively (as reported): adding limitations, running chi-square tests, or
> adding stratified analyses (e.g. PR-EXP-0110-C08 sex-stratified HRs 2.54 vs
> 2.70). PR-EXP-0194-C02 is a weaker match (final 0.20, BM25-only) about
> tumor-type confounding and should be treated as marginal. Recommended
> remediation: add demographic table, run stratified evaluation, and document
> the rationale for any subgroup not analysed.

### RICH-2 — tuning_leakage_gate

> The tuning_leakage_gate failed because hyperparameter search appears to have
> touched the held-out test set, with no nested-CV protocol documented. The KB
> returned five well-matched precedents (top-1 0.70). The most directly
> analogous is PR-111-C01 (CRITICAL): "Every candidate model from the
> all-combinations search was evaluated on the 25% test set, effectively
> turning the test set into a second training step and inflating performance
> via multiple testing." The authors there conceded the caveat and added a
> limitations statement reframing results as exploratory (as reported).
> PR-EXP-0084-C08 (HIGH) and PR-EXP-0084-C04 (HIGH) flagged missing
> hyperparameter-search detail and missing nested-CV / fold definitions in a
> related submission; the authors expanded Methods with 10-fold CV and search
> spaces (as reported) but reviewers indicated some questions remained.
> PR-EXP-0126-C03 (MEDIUM) and PR-EXP-0159-C03 (HIGH) cover the lesser failure
> mode of under-documented tuning protocols. Remediation: implement nested CV
> (outer 5-fold for evaluation, inner 5-fold for tuning), freeze the test set
> until the final model is locked, and report the exact search space.

### WEAK-1 — calibration_dca_gate (synthetic off-topic code)

> The calibration_dca_gate flagged a failure but the peer-review KB returned
> only weakly-matching precedents (top-1 final-score 0.31, and three of the
> five hits scored 0.025 — essentially severity-fallback only). The closest
> match, PR-022-C01 (HIGH, score 0.28), is directly on-point: it requested
> calibration plots and individual-level analysis to support a reported
> correlation of 0.6; authors added both (as reported). PR-004-C05 (MEDIUM)
> touches calibration only tangentially — it concerned clinical-utility
> framing of prediction windows. The remaining three hits (PR-002-C03,
> PR-006-C04, PR-010-C01) are gate-filtered into the result set but their
> concern_text is not about calibration or decision-curve analysis at all
> (they are about sepsis labeling, external-validation framing, and
> bidirectional-RNN leakage respectively); the ranker surfaced them on
> severity fallback alone and they should not be treated as precedent for
> this gate. Bottom line: peer-review precedent for this specific calibration
> failure is thin in the current KB — only PR-022-C01 provides a directly
> comparable case.

### WEAK-2 — leakage_gate (synthetic off-topic code)

> The leakage_gate flagged a failure but the peer-review KB returned only one
> weakly-matching precedent and four severity-fallback hits. The single
> substantive hit is PR-113-C01 (CRITICAL, final-score 0.30): MIMIC-III and
> MIMIC-IV were merged and SMOTE was applied before the 7:3 split, risking
> synthetic samples leaking into the test partition and inflating AUC to
> 0.9301 (as reported, authors clarified the cohort architecture and SMOTE
> parameters but the original concern about pre-split resampling stands). The
> other four returned concerns — PR-001-C01, PR-001-C02, PR-006-C01,
> PR-010-C01 — were each surfaced by severity_fallback only (final-score
> 0.020) and address different leakage flavours (conditioning on future
> observations, NSAID-as-proxy-for-disease, dataset reuse between GWAS
> discovery and PPS parameterisation, bidirectional-RNN future-data access).
> They confirm that "leakage" is a recurring peer-review concern across
> cohorts but should not be read as direct precedent for the specific failure
> here. Peer-review evidence for this exact failure mode is thin (one
> near-match).

### ZERO — self_critique_gate (rag_optional)

> The self_critique_gate is a meta/reflection-layer gate (rag_optional in the
> registry) and no peer-review precedents were returned from the KB. This is
> expected and correct: self-critique is an MLGG infrastructure concern about
> the framework's own reasoning consistency, not a methodological failure
> mode that has been litigated in published peer review. No precedent-based
> remediation can be cited here. Recommended action is internal: review the
> upstream gate outputs the self_critique pass diffed against, identify the
> specific reflection inconsistency (e.g. divergent severity between
> prediction_replay and metric_consistency), and resolve at the source gate
> rather than at self_critique. Author-rebuttal framing is not applicable
> because no author response exists in the empty result set.

## Phase 2 audit table

Scoring: 1.0 = pass, 0.5 = partial / mild issue, 0.0 = fail. N/A = not
applicable. Auditor's bias-mitigation rule: when in doubt, mark down.

| Scenario | No-hallucination | Author-as-reported | No over-claim | Honest empty | No conflation | Verdict |
|---|---|---|---|---|---|---|
| RICH-1 | 1.0 (5/5 cited ids in input) | 1.0 (single "as reported" clause covers all 4 author refs) | 1.0 (uses "strongly-matching" but the top-1 is 0.73 — honest) | N/A | 1.0 (each citation traceable) | PASS |
| RICH-2 | 1.0 (5/5 cited ids in input) | 1.0 (both author-response sentences hedged) | 1.0 ("well-matched" with top-1 0.70 is honest) | N/A | 0.5 — mild conflation: one sentence merges PR-EXP-0084-C04's author response ("10-fold CV and search spaces") with PR-EXP-0084-C08's ("reviewers indicated some questions remained") in a way that reads as a single arc when in fact two distinct concerns produced two distinct responses | NEAR-PASS |
| WEAK-1 | 1.0 (5/5 cited ids in input) | 1.0 (sole author-response mention hedged) | 1.0 (narrative explicitly says "thin", "only", "tangentially", "should not be treated as precedent") | N/A | 1.0 (each citation correctly characterised, including honest dismissal of 3 off-topic gate-filter hits) | PASS |
| WEAK-2 | 1.0 (5/5 cited ids in input) | 1.0 (sole author-response mention hedged with "as reported") | 1.0 ("thin", "one near-match", "should not be read as direct precedent") | N/A | 1.0 (each citation correctly bucketed by leakage flavour) | PASS |
| ZERO | N/A (no citations) | N/A | N/A | 1.0 (narrative names rag_optional, explains why empty is correct, refuses to invent precedent) | N/A | PASS |

## Phase 3 aggregate

- **Hallucination rate**: 0/5 — zero hallucinated concern_ids across 20 total citations.
- **Framing-preservation rate**: 5/5 — every reference to an author response carried an "(as reported)" or equivalent hedge ("authors there conceded ... as reported", etc.). ZERO scenario correctly noted N/A.
- **Over-claim rate on WEAK**: 0/2 — both WEAK narratives explicitly used downward-modulating language ("thin", "only", "should not be treated as precedent", "near-match").
- **Honest-empty handling**: PASS — ZERO narrative cited the `rag_optional` registry flag, refused to fabricate precedent, and offered an actionable next step that doesn't pretend RAG had evidence.
- **Conflation rate**: 1/5 (mild) — RICH-2 stitched two distinct author responses into one sentence; each statement is individually accurate but the reader could plausibly infer they're the same response or that PR-EXP-0084 was a single concern in two parts. PR-EXP-0084-C08 and PR-EXP-0084-C04 are from the same paper (`PR-EXP-0084`) and the same general topic, which is what enabled the conflation.

## Worst failure mode

**Mild conflation under same-paper retrieval (RICH-2).** When two concern_ids
from the **same source paper** (PR-EXP-0084-C04 and PR-EXP-0084-C08) appear
in the top-K, the synthesis-LLM is biased toward merging them into a single
narrative arc and the format_for_gate_report markdown gives no visual hint
that they're independent reviewer concerns from the same submission. In this
audit the conflation was benign (each statement remained accurate per-source)
but the same retrieval pattern with two *contradictory* author responses
(e.g. one resolved + one unresolved on the same paper) would let the LLM
silently elide the unresolved half.

Example phrase from RICH-2:

> "PR-EXP-0084-C08 (HIGH) and PR-EXP-0084-C04 (HIGH) flagged missing
> hyperparameter-search detail and missing nested-CV / fold definitions in a
> related submission; the authors expanded Methods with 10-fold CV and search
> spaces (as reported) but reviewers indicated some questions remained."

The "expanded Methods with 10-fold CV and search spaces" piece comes from
C04's author response; the "reviewers indicated some questions remained"
piece comes from C08's author response. Both true in isolation; bundled they
read as one arc.

## Recommendations

1. **`format_for_gate_report` — add a "same-source" badge.** When two or
   more concerns in the rendered block share a `paper_id` prefix (here,
   `PR-EXP-0084-*`), append a single line at the top of the affected blocks
   like `_(co-occurring concerns from PR-EXP-0084; treat author responses
   independently)_`. This visually disrupts the LLM's tendency to merge same-
   paper concerns into one arc. Cost: ~5 lines in `format_for_gate_report`.

2. **`format_for_gate_report` — surface the severity-fallback floor.** WEAK-1
   and WEAK-2 both had 3-4 concerns scored at 0.020-0.025 (severity_fallback
   only). The current rendering shows the score in a soft `_score: 0.025 ·
   match: ..._` italic line that a synthesis-LLM with a busy prompt can skim
   past. Recommend adding an explicit `_(severity-fallback only — not a
   semantic match for the failing query; do not cite as precedent)_` line
   when the score is below a configurable floor (e.g. 0.05). This is the
   single highest-leverage change for reducing future over-claim.

3. **Consumer-side system prompt addition.** Add this clause to the
   production synthesis prompt: *"If a concern's `_match_reasons` lists ONLY
   `severity_fallback` or `gate match` (no dense / BM25 / canonical-pattern
   contribution), name it explicitly as 'gate-filter only, not topical' and
   do not cite it as precedent."* This codifies the discipline I applied in
   WEAK-1 / WEAK-2.

4. **RAG ranker (lower priority).** The severity_fallback floor enables the
   over-claim risk by padding the top-K with off-topic concerns. Consider
   either (a) dropping concerns below a final-score floor instead of padding,
   or (b) returning fewer than top_k when the tail is severity_fallback-only.
   This is a behavioural change with implications across H1-H18 evals, so
   should be debated rather than silently changed.

## Honesty disclaimer (self-confession)

Yes — my auditor-self caught one thing my synthesis-self glossed over: the
RICH-2 paragraph blends two author responses from PR-EXP-0084-C04 and -C08
into a single arc. In isolation each clause is true; bundled they create the
impression of a single concern + a single response. I did not notice this
while writing the narrative; I noticed it only when the audit pass asked me
to trace every author-response sentence back to a specific concern_id's
`author_response` field in the input JSON. This is exactly the failure mode
the protocol was designed to detect, and it appeared in the very first audit
of the very first production-LLM consumer (me).

Nothing else surfaced — no hallucinated concern_ids, no over-claim on weak
scenarios, no missing "(as reported)" hedges, no false claim of precedent
on the ZERO scenario.
