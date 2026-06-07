# RAG gate-path precision — what the GLM7 N=1 found (and why the quick fixes don't work)

The blind adjudication measured the BM25 gate-path retrieval (`retrieve_for_failure`) at
**8/16 = 50% precision** on this paper (per class: definition_leakage 1/4, cross_sectional 2/4,
selection 2/4, incomplete_eval 3/4). This note records what was tried to raise it, and the result —
**so nobody re-attempts a fix the data already refutes.**

## Three principled fixes, all empirically refuted (N=1, 4 queries / 16 candidates)

| Fix | Result | Evidence |
|---|---|---|
| **`min_score` threshold** | ✗ no help | On- and off-topic candidates score the SAME. selection_leakage: a top OFF (`PR-EXP-0155-C03`) ties the top ON at 11, and an ON (`PR-114-C04`) scores 8 *below* an OFF at 9. incomplete_eval: all four score exactly 4. Any threshold that drops an off-topic drops an on-topic too. |
| **exact-issue-code-as-tag bonus** | ✗ no help | Simulated +5 for a verbatim issue-code tag → **precision@4 unchanged in 0/4 classes**. Only definition_leakage (1 candidate) and incomplete_eval (3) have an exact tag, and those are already in the top-4; cross_sectional and selection have **0** exact-tag candidates. |
| **structured `mlgg_rules` / `canonical_pattern_id` rerank** | ✗ no help | They don't separate on/off (definition_leakage: the ON and two OFF all carry `MLGG-F04`; cross_sectional: ON and OFF both `CP-002`) and the rule vocabulary is inconsistent (`M01` vs `MLGG-M01`). |

## Root cause — architectural, not a tuning bug

The off-topic retrievals are **not** junk: they are the *same gate's concern family, a different specific
mechanism*. For `definition_variable_leakage` the gate returns, alongside the on-topic
"defining-variable-used-as-its-own-feature" concern, three same-family concerns —
target-leakage-via-NSAID-proxy, eGFR definitional *collinearity*, definitional *confounding*. All four
are legitimately tagged `definition_variable*` and share the category keywords, so BM25 keyword overlap
cannot rank them apart.

The blind adjudicator separated them by **reading `concern_text` and judging mechanism match** — a
*semantic* operation. That is the **dense / hybrid retrieval path**, not the BM25 gate path. Per the
two-path architecture (`RAG_PATH_FINDINGS.md` / project memory), **gates ship BM25-only on purpose**
(deterministic, no model dependency), so mechanism-level precision is structurally out of reach on the
gate path. The 50% is a *category-precision* number, and category-precision is what this path is for.

## Real levers (each a real decision, not a patch)

1. **Accept it.** Report the gate-path number as *category* precision and rely on the LLM advisory layer
   (which the adjudication validated at 6/6) for mechanism-level discrimination. Cheapest; arguably correct.
2. **Route gate enrichment through the dense/hybrid path.** Would buy mechanism-precision but changes the
   shipping architecture (model dependency, non-determinism) — the documented two-path tension. Big call.
3. **Finer KB tagging + an exact-tag-priority mode.** Make tags mechanism-specific and prefer verbatim
   issue-code↔tag matches. Helps only where the KB is precisely tagged (here: incomplete_eval); labor-
   intensive and partial.

## Bottom line

The N=1 surfaced a genuine, non-obvious product fact: **the gate-path retrieval is category-precise, and
no scoring tweak makes it mechanism-precise** — that needs semantics (dense path) or much finer KB tags.
This is the second concrete product finding from this benchmark (the first being the disease-KB synonym
gaps, which *were* fixable and were fixed in KB v1.3).
