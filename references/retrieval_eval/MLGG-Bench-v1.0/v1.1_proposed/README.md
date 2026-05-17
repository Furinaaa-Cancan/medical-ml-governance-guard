# MLGG-Bench v1.1 — Proposed Artifacts (NOT promoted)

Three autonomous v1.1 experiments executed on 2026-05-17. Each artifact in this directory is a **draft pending review** — not part of the shipped benchmark.

| Artifact | Hypothesis | Measured outcome | Decision |
|---|---|---|---|
| `draft_meta_entries.{json,md}` | Adding 30 TRIPOD+AI / PROBAST+AI / STRATOS meta-level KB entries will lift ood_03 (currently cp_hit@5 = 0.20) | **ood_03 hit@5: 0.30 → 0.50 (Δ=+0.20)** verified via temp-augmented KB; cp_hit@5 unchanged | Hold for clinical methodologist review (KB additions cannot be auto-promoted per project disease-KB provenance policy) |
| `compound_query_proto.py` + `compound_query_NEGATIVE.md` | Decompose-and-merge compound queries will lift bench_03 (currently hit@5 = 0.20) | **NEGATIVE: 0 hit improvement, -0.10 cp_hit** on bench_03 | Do not ship. Real failure mode is partly gold-label noise (ultra-rare paper-specific tags) not retrievable from any compound-detection strategy. |
| (in v1.0.1 PATCH instead) | Full-pass CP relabel will improve cp_hit | **cp_hit@5: 0.794 → 0.821 (Δ=+0.027)** verified | **Promoted to v1.0.1** at `../v1.0.1/` |

## Why these are in `v1.1_proposed/` not in any released version

The two artifacts here both require human review before adoption:

1. **`draft_meta_entries`** — every entry is marked `_provenance: "LLM-DRAFT-v1.1-pending-clinical-review"`. Per project policy (`disease-KB` is LLM-generated and needs clinical review + guideline citations before publication-grade claims), these cannot be auto-merged into `references/case-studies/peer-review-kb.json`. Once a clinical methodologist signs off on the 30 entries (plus the 3 proposed new CPs CP-050/051/052 and the 14 proposed new tags), they become part of v1.1.0.

2. **`compound_query_NEGATIVE.md`** — documents an honest failed experiment. Kept here as an ablation record for the eventual v1.1.0 SPEC, so future contributors don't redo the same naive fix.

## Verified-but-untyped: the META-augmented ood_03 lift

The +0.20 lift on ood_03 hit@5 was measured by:
1. Building a temporary augmented KB = `peer-review-kb.json` (335 entries / 817 concerns) + 31 META draft entries (=366 entries / 848 concerns)
2. Monkey-patching `scripts.rag.config.KB_PATH` to point at the augmented KB
3. Clearing the `.cache/rag/concerns_embeddings.npz` so the BGE re-indexes
4. Running the ood_03 scenarios through `rag_query()`

This proves the meta-entries direction works. The script is reproducible: see the bash heredoc in `../../../../tmp/mlgg_benchmark/` (transient — re-write from this README if needed).

## Open questions for the v1.1.0 release decision

1. Do CP-050/051/052 get minted, or do the meta-entries collapse onto existing CPs (which the agent showed *understates* their value)?
2. Are the 3 anchor entries (META-ANCHOR-001/002/003 = DeGrave / Zech / Wong) re-modeled as normal paper-level entries with a `meta_anchor: true` flag, instead of `domain: "methodology"`?
3. Does the CP-Relabel methodology in v1.0.1 also run on the OOD slices (currently only indist_155 was full-pass relabeled)?
4. Is the v1.1.0 release gated on clinical-reviewer turnaround time, or do we ship META entries as `_provenance: pending_review` and let the field correct?

Reviewer notes: see `draft_meta_entries.md` for the 7 open questions specific to the meta entries themselves.
