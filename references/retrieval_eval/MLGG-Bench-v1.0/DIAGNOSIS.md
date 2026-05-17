# MLGG-Bench v1.0 — Known Failure Modes & v1.1 Work Items

Generated from full 305-scenario benchmark run on 2026-05-17.
Companion to BENCHMARK_SPEC.md §8 Known Limitations.

> 📌 **v1.1 prototype results landed in [`v1.1_proposed/`](./v1.1_proposed/)** the same day. Each failure mode below now has a measured experiment outcome. See per-failure annotations.

---

## Failure 1 — Compound 2-CP queries (bench_03_compound)

**Measured:** hit@5 = 0.20, cp_hit@5 = 0.50 (n=10).

> **v1.1 update (2026-05-17):** A decompose-and-merge prototype was implemented and benchmarked → **NEGATIVE RESULT** (0 hit improvement, -0.10 cp_hit). See [`v1.1_proposed/compound_query_NEGATIVE.md`](./v1.1_proposed/compound_query_NEGATIVE.md). The failure is partly RAG single-CP bias and partly bench_03 gold-label noise (~60% of expected_tags are KB-rare). A real fix needs gold cleanup + aspect-based retrieval — not naive split.

**Root cause (verified by trace):** RAG hybrid retrieval concentrates on a single dominant CP per query. For 7/10 compound scenarios the top-5 returned concerns cluster around ONE of the two expected CPs and never bridge to the second.

**Example — `bench03_compound_pr-007_cp-002_cp-022`:**
- expected_cps = [CP-002, CP-022]
- ret_cps      = [CP-002, None, CP-002, CP-002, None]
- cp_overlap   = [CP-002, CP-002, CP-002]  ← three copies, never finds CP-022

**Why MMR is insufficient:** MMR diversity penalty (`MMR_LAMBDA=0.7`, `MMR_SAME_PAPER_PENALTY=0.5`, `MMR_COSINE_FLOOR=0.88`) penalizes near-duplicates within a single CP cluster but does not actively *seek* representation from a second CP cluster when the query semantically spans two.

**v1.1 candidate fixes (in order of cost):**

| Fix | Cost | Expected lift |
|---|---|---|
| (a) Raise `MMR_LAMBDA` to 0.5 | 1 line config | small — still single-cluster bias |
| (b) Post-process: detect query has bundling conjunctions (" AND ", ";", "two issues", "(1)…(2)…") → run RAG twice with split queries, merge top-K | ~30 lines retrieval/hybrid.py | medium |
| (c) Multi-aspect retrieval: extract entity/aspect spans from query, retrieve per-aspect, fuse | ~150 lines + new module | large — best long-term |

**Recommendation:** ship v1.0 with this measured weakness documented; tackle (b) in v1.1.

---

## Failure 2 — Meta-methodology queries (ood_03 TRIPOD+AI / PROBAST+AI)

**Measured:** hit@5 = 0.30, cp_hit@5 = 0.20 (n=10).

> **v1.1 update (2026-05-17):** A 30-entry draft of TRIPOD+AI / PROBAST+AI / STRATOS / systematic-review KB meta-entries was generated and benchmarked via a temp-augmented KB → **VERIFIED LIFT: ood_03 hit@5 0.30 → 0.50 (+0.20)**. See [`v1.1_proposed/draft_meta_entries.{json,md}`](./v1.1_proposed/draft_meta_entries.md). `cp_hit@5` did NOT lift because the draft entries map to existing CPs; the proposal includes 3 new CPs (CP-050/051/052) which need minting before the cp_hit lift can be tested. KB additions held pending clinical-methodologist review per project disease-KB provenance policy.

**Root cause:** KB concerns are paper-specific (e.g., "PR-001's NSAID variable is an outcome proxy"). TRIPOD+AI / PROBAST+AI critiques are *meta-level* (e.g., "checklist item 17 — uncertainty quantification — is widely under-reported"). The two live at different abstraction tiers.

**Why the RAG can't bridge:**
- BGE-small embeddings cluster the meta query near generic reporting concerns, but the KB has no concept-level entries (only paper-level).
- BM25 keyword overlap is weak because meta queries use checklist vocabulary (`item 14`, `checklist gap`, `reporting completeness`) absent in the KB.

**v1.1 candidate fixes:**

| Fix | Cost | Expected lift |
|---|---|---|
| (a) Add meta-level entries to KB — one per TRIPOD+AI/PROBAST+AI checklist item (~30 items) tagged with `canonical_pattern_id`, severity, gates | ~40 KB entries, needs clinical review per project disease_kb_provenance memory | large |
| (b) Add a `meta_critique_gate` and route TRIPOD/PROBAST-style queries to it separately | medium | medium |
| (c) Retrieve KB entries cited in TRIPOD+AI itself as anchors (Zech 2018, Wong 2021, etc.) | small (KB add ~10) | small |

**Recommendation:** v1.1 should adopt (a) as a deliberate scoping expansion. Document v1.0 OOD score on ood_03 honestly as "RAG outside trained scope".

---

## Failure 3 — F1000/eLife OOD tag-vs-CP divergence (ood_04)

**Measured:** hit@5 = 0.90 (high!) BUT cp_hit@5 = 0.20 (low).

**Diagnosis:** F1000/eLife reviewer queries paraphrase concerns in ways that lexically overlap KB tags (so tag-overlap scoring rewards) but the underlying canonical pattern in our 49-CP taxonomy doesn't map cleanly — these reviewers raise concerns at granularities our CP taxonomy doesn't yet name.

**Implication:** the 49-CP taxonomy is incomplete for ~20% of real-world peer review. Either:
- (a) Add 5–10 new CPs derived from the ood_04 patterns
- (b) Accept that tag-overlap remains the primary metric; CP-hit is a stricter sub-metric for in-distribution-derived queries

**Recommendation:** for v1.0, report both metrics per slice as already done. For v1.1, expand CP taxonomy after a domain-expert pass over the 8 ood_04 mis-fits.

---

## Distractor false-positive (bench_05)

**Measured:** false_strong_hit_rate = 1/10 = 0.10 (top-1 cosine 0.97 on a query that should not match).

The single offender is recoverable case-by-case — log of the over-fire query goes into the v1.0 release notes; investigate post-release. Not a v1.0 blocker.

---

## v1.0 vs v1.1 release decision

**Ship v1.0 now** with:
- 305 scenarios across 9 slices
- BENCHMARK_SPEC.md documenting all 3 failure modes
- bench_06 IRR backlog: 28% of indist_155 CP labels flagged for re-labeling (CP-Relabel agent in flight at time of writing; results merge into v1.0 if completed before release)

**v1.1 backlog:**
1. Apply compound-query bundle-detector fix (Failure 1, fix (b))
2. Add 30 meta-level KB entries for TRIPOD+AI/PROBAST+AI (Failure 2, fix (a))
3. Expand CP taxonomy by 5–10 patterns based on ood_04 (Failure 3, fix (a))
4. Address bench_05 single distractor over-fire
5. Apply CP-Relabel v2 if not folded into v1.0
