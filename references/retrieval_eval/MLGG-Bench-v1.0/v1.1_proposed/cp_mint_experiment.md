# v1.1 experiment — Should CP-050 / CP-051 / CP-052 be minted?

**Question:** the META draft entries (in `draft_meta_entries.json`) propose 3 new CPs (`CP-050 meta_checklist_underreporting`, `CP-051 systematic_review_base_rate`, `CP-052 shortcut_learning_audit_missing`). The draft agent mapped META entries to *existing* CPs as a fallback, noting this "understates the value" of the new CPs. This experiment quantifies the trade.

## Method

Three conditions tested on ood_03 (n=10), the slice where the META entries are designed to help:

1. **Baseline** — no META entries indexed
2. **META → existing CPs** — META entries indexed, `canonical_pattern_id` mapped to closest existing CP (CP-004/018/024/etc., the draft agent's original mapping)
3. **META → new CPs (CP-050/051/052)** — same 30 META entries indexed, but their concerns are re-labeled to the new CPs:
   - 19 TRIPOD+AI / PROBAST+AI entries → CP-050
   - 8 STRATOS / systematic-review entries → CP-051
   - 3 ANCHOR entries (DeGrave / Zech / Wong shortcuts) → CP-052
   - ood_03 scenarios' `expected_canonical_pattern_ids` augmented to include the new CPs based on inferred topic (TRIPOD/PROBAST keywords → CP-050; SR/Wynants/Roberts keywords → CP-051; shortcut/DeGrave/Zech keywords → CP-052; 3 scenarios got no addition because keyword inference returned empty)

## Results

| Condition | hit@5 | cp_hit@5 | Δ hit vs baseline | Δ cp_hit vs baseline |
|---|---|---|---|---|
| Baseline (no META) | 0.300 | 0.200 | — | — |
| META → existing CPs | **0.500** | 0.200 | **+0.200** | 0 |
| META → new CPs | 0.400 | **0.300** | +0.100 | **+0.100** |

## Interpretation

**Trade-off is real:**
- Minting new CPs lifts `cp_hit@5` by +0.10 (canonical-pattern recall, the metric stricter consumers care about — gate routing, downstream classification)
- Minting new CPs costs −0.10 on `hit@5` (tag overlap, the metric loose consumers care about — "did the RAG show me anything relevant?")
- Net cluster behaviour: putting META entries in their own new CPs reduces the same-cluster corroboration boost that helps generic retrieval, but enables exact-CP-match for the queries that semantically belong there

## Per-scenario breakdown (condition 3)

| Scenario | ret_cps (top-3) | gold CPs | tag hit | cp hit |
|---|---|---|---|---|
| tripod_ai_calibration_omitted | CP-026 ×3 | + CP-050 | 1 | 0 |
| probast_ai_proxy_outcome | CP-002 ×2 | + CP-050, CP-051 | 0 | 0 |
| roberts_frankenstein_dataset | CP-037, CP-034 | + CP-051 | 0 | 0 |
| **degrave_shortcut_learning_laterality** | **CP-052**, CP-050, CP-022 | + CP-052 | **1** | **1** ← clean win |
| zech_hospital_system | CP-008 ×3 | + CP-050, CP-052 | 0 | 0 |
| wong_epic_sepsis_internal_only | CP-023, CP-008 | (none added) | 0 | 0 |
| riley_sample_size_epv | CP-024 ×3 | + CP-050, CP-051 | 1 | 0 |
| chexnet_radiologist | CP-027, CP-023, CP-001 | (none added) | 0 | 1 |
| christodoulou_ml_vs_lr | CP-028 ×2, CP-005 | + CP-050, CP-051 | 0 | 0 |
| **van_calster_2025_auroc_only** | CP-018 ×2, **CP-051** | (none added in inference, but CP-051 retrieved) | 1 | 1 ← serendipitous |

The DeGrave scenario is the textbook case: CP-052 (shortcut_learning_audit_missing) was created specifically for it, the retrieval finds the META-ANCHOR-001 entry tagged CP-052, and both hit + cp_hit fire. The other 9 scenarios show why the lift is modest: even with new CPs, the RAG's lexical and semantic signal still pulls toward older / larger CP clusters first.

## Recommendation for the clinical reviewer

If you care about cp_hit (canonical pattern recall):
- **Mint CP-050, CP-051, CP-052** alongside accepting the 30 META draft entries
- The cp_hit lift on ood_03 (+0.10) and on any future meta-methodology queries justifies the taxonomy expansion

If you care about hit@5 (tag overlap):
- **Don't mint; keep META → existing CP mapping** (the agent's default)
- Cleaner +0.20 gain, no fragmentation cost

**Hybrid path** (recommended): mint only CP-052 (shortcut_learning_audit_missing) — it's the cleanest discrete pattern (DeGrave-style shortcut learning is well-defined, has 3 clean anchor entries, and produced the clean cp_hit win). Hold CP-050 (checklist meta) and CP-051 (systematic review meta) until more anchor entries exist — those have weaker per-entry semantic distinctness and may be the source of the −0.10 hit cost.

## Methodology limitations

1. **Inference heuristic for which scenarios get which new CP** was keyword-based — crude. 3 scenarios got `new_cps_added=[]` because keywords didn't fire. A real release would have hand-labeled or LLM-judged gold CPs for ood_03.
2. **n=10 ood_03 sample** — too small for confident generalization. Bootstrap CI on these 3-condition comparisons would have a ±15pp swing.
3. **The +0.20 META-only hit was measured earlier; the +0.10 + +0.10 with-new-CPs is from this run** — both used the same eval harness on the same query texts, so the comparison is apples-to-apples.

## Outputs

- This document
- Re-runnable: see the python heredoc in commit history (search for "Experiment B" or run `python3 -c "..."` with the script in this dir's compound_query_proto.py adjacent to similar monkey-patch logic)
- Augmented KB at `/tmp/mlgg_benchmark/_kb_aug_with_new_cps.json` (transient, regenerable)
