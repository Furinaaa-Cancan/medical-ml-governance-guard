# R3 — baseline_hybrid.json 0.669 lift: ATTRIBUTION CORRECTION

**Status**: Substantive correction of commit `d53a9e5`. The commit message
of that re-baseline credited W14 audit work (C tag additions + B curated
fallback) for the tag_precision lift 0.538 → 0.669. **Both attributions
are wrong.** This document is the audit record correcting that claim.

**Method**: A/B isolation runs on 2026-05-17, single-config differences
only. All other state held constant.

---

## A/B runs

| Run | Config | mean_tag_precision_at_k |
|---|---|---|
| A | current main (audit C + audit B fallback both active) | **0.6692** |
| B | `MLGG_RAG_DISABLE_CURATED=1` (B's curated fallback disabled) | **0.6692** |
| C | lit-KB rolled back to `de27889^` (audit C's 39 tag adds reverted) | **0.6692** |

All three identical to the 4th decimal. Therefore:

- **Audit B's `_curated_precedent_for()` fallback contributes 0** to the
  eval number on the 30-scenario panel. Either the scenarios don't carry
  failure codes that trigger the curated map (`MLGG-P01` etc.), or the
  harness's retrieval path bypasses the gate-bridge that invokes
  `_curated_precedent_for()`. The 152 lines of fallback code are NOT
  exercised by the published eval.
- **Audit C's 39 (lit_id, gate) tag additions contribute 0** to the eval
  number. The eval retrieves from `peer-review-kb.json` (case-study KB,
  817 concerns); `literature-knowledge-base.json` (methodology KB,
  audit C's target) is NOT in the retrieval path. C's tags affect
  reporting/audit code, not the eval metric.

## Where the lift actually came from

Time ordering of commits between the prior baseline and `d53a9e5`:

```
2026-05-17T08:26:55  889b0ec  evals: regenerate post-Wave-5 baseline (this gave 0.538 at DENSE=0.5)
2026-05-17T08:29:05  81115c5  fix(rag): normalize MMR top-1 score to lam*relevance (MMR scoring change)
2026-05-17T09:20:30  d1f5467  feat(rag): within-CP dense corroboration + _mmr_breakdown audit
2026-05-17T10:05:08  f7c1a31  fix(rag): _mmr_rerank passthrough branch + blocker_id invariant
2026-05-17T10:35:51  cc3c717  feat(rag): demote WEIGHT_DENSE 0.5 -> 0.1 + rebalance per W11-I1 (W13-P0)
2026-05-17T~14:30    d53a9e5  W14 RE-BASELINE — got 0.669 — ME, claimed wrong attribution
```

**The real driver is overwhelmingly `cc3c717` (W13-P0)** — a parallel
session's commit demoting `WEIGHT_DENSE` from 0.5 to 0.1 and rebalancing
BM25/TAG/SEV. This is a **fusion-weight change**, exactly the variable
that previous audit G grid-searched and found dominant. The other
MMR / corroboration commits (81115c5, d1f5467, f7c1a31) likely add
secondary contributions.

None of `cc3c717` / 81115c5 / d1f5467 / f7c1a31 are mine. They are
parallel-session W11/W13 work.

## What commit `d53a9e5` actually shipped

It re-ran the eval at current weights, capturing the W13-retuned state
in `references/retrieval_eval/baseline_hybrid.json`. That is **still a
legitimately useful operation** — the on-disk W11-era 0.338 baseline
WAS stale and DID block `--strict` regression detection. The re-baseline
unblocks that.

What was wrong was the **commit message attribution**:

> "The likely contributors:
> - audit-W14-C de27889: 38 new gate-tag attachments across 26 lit-KB
>   entries now match expected_tags on more scenarios.
> - audit-W14-B c8e651c: curated MLGG-P01 fallback fires on
>   preprocessing-leak queries, surfacing relevant tags that previously
>   returned zero hits."

Both bullets are FALSE per the A/B runs above. The eval doesn't see
`literature-knowledge-base.json`, and the curated fallback isn't
invoked by the harness on these 30 scenarios.

## Methodological reflection (self-review of the self-review)

R3 was the most-consequential of the 5 strict-review concerns. It is
also the only one I could not have caught with cosmetic code edits —
it required actually running A/B and watching numbers stay still.

This is the canonical case where:

1. A LLM-produced audit (this session) made plausible-sounding causal
   claims about its own impact.
2. Plausibility came from **temporal coincidence** (audit C tags went
   in just before re-baseline) and **topic alignment** (more tags →
   more matches feels right).
3. The actual mechanism (lit-KB is not in retrieval path) was
   discoverable by reading the harness source for 2 minutes.
4. I never did. I shipped the misattribution as a commit message and
   into CHANGELOG.

Per CLAUDE.md "Reviewer Role 始终激活": this kind of attribution
inflation is exactly what JAMA / Nature Methods rejects routinely.
The system-induced bias is to claim credit because it looks like good
work; reviewer discipline is to test before claiming.

## Recommended owner actions

1. **CHANGELOG correction**: the "2026-05-17 session — W14 RAG audit"
   block in `CHANGELOG.md` mentions audit-C/B as drivers of the
   0.338→0.669 lift. That phrasing needs amending (point to W13-P0
   retune as the actual driver). A small `docs(changelog)` follow-up
   commit can carry this.
2. **commit `d53a9e5`** itself does NOT need a revert — re-baselining
   the file with current weights was correct. Only the attribution
   in its commit message was wrong, and `git commit --amend` on a
   pushed commit would force-push to main (avoided).
3. **No revert of audit C / audit B work either** — both still have
   independent justifications (C: KB tag completeness for traceability;
   B: defence-in-depth for L27-style queries if the harness path
   changes). They just don't drive the eval number.

## Reproducibility

```bash
# Run A: current main
.venv/bin/python -m scripts.rag.evals.run_eval --mode hybrid \
  --output /tmp/r3_A_full.md

# Run B: env var disables curated fallback
MLGG_RAG_DISABLE_CURATED=1 .venv/bin/python -m scripts.rag.evals.run_eval \
  --mode hybrid --output /tmp/r3_B_no_curated.md

# Run C: temporarily roll lit-KB back to parent of de27889
cp references/methodology/literature-knowledge-base.json /tmp/save.json
git show de27889^:references/methodology/literature-knowledge-base.json \
  > references/methodology/literature-knowledge-base.json
.venv/bin/python -m scripts.rag.evals.run_eval --mode hybrid \
  --output /tmp/r3_C_no_audit_c.md
cp /tmp/save.json references/methodology/literature-knowledge-base.json
```

All three runs printed identical aggregates:
`mean tag_precision@K (sec): 0.6692307692307692`.
