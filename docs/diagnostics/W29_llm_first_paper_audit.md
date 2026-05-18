# W29 — LLM-first paper audit + RAG enrichment (MVP + W31-S1 priming refactor)

**Date**: 2026-05-18 (MVP), 2026-05-18 (W31-S1 priming refactor)
**Status**: Module + 26 unit tests + CLI wiring shipped. Three RAG strategies now supported (`primed` default, `post_hoc` ablation, `off` baseline). **Real-paper validation still deferred** to W29-V2 (requires `pip install anthropic` + `ANTHROPIC_API_KEY` + actual API call on GLM7 paper).

## W31-S1 update (this section is newer than the rest of the doc)

The W29-MVP architecture was "LLM → RAG enrich after". Today's discussion with the user concluded the better architecture is **"RAG → LLM with KB context"** (primed mode). The data flow changed:

```
W29-MVP:    PDF → LLM(prompt + methods) → concerns → for each: RAG → citations
W31-S1:     PDF → RAG retrieves general+leakage pool → LLM(prompt + KB context + methods) → concerns
```

In primed mode the LLM **forms opinions with KB excerpts already in its context**, not as post-hoc anchoring. The SYSTEM_PROMPT gained 5 anti-rubber-stamp rules (R1-R5) explicitly disciplining the LLM not to apply KB concerns automatically.

`audit_paper(rag_strategy=...)` now accepts:
- `"primed"` (W31, default) — KB retrieved first via `_retrieve_rag_context_for_priming()` (general free-text + `gate="leakage_gate"` BM25 pass merged), injected into user prompt
- `"post_hoc"` (W29-MVP behaviour, kept for ablation) — LLM first, then per-concern `enrich_with_rag()`
- `"off"` — no RAG anywhere; baseline for measuring RAG contribution

`AuditReport` gained `kb_context_pool: list[KbCitation]` carrying the full pool the LLM saw in primed mode. The W29-MVP `rag_enriched: bool` field is replaced by `rag_strategy: str`.

The W29-V2 validation matrix below grew from 1 mode to 3; the new pre-registered comparison is:

| Setup | rag_strategy | What we're measuring |
|---|---|---|
| Baseline | `"off"` | LLM-only ceiling (does prompt-engineering alone catch 3/3 CRITICAL?) |
| Primed | `"primed"` | The user's pick — RAG informs LLM during audit |
| Post-hoc | `"post_hoc"` | Original W29-MVP — RAG anchors LLM concerns after the fact |

If `off ≈ primed`, RAG NC KB adds zero marginal value on GLM7 → retire. If `primed > off ≥ post_hoc`, RAG-as-priming is the right reposition. If `post_hoc > primed`, the user's intuition was wrong and we go back to enrichment.

---


**Cross-refs**:
- Architecture rationale → today's GLM7 controlled experiment (this session, agent vs MLGG vs human read).
- W28-V1 Johnson 2017 replay → `docs/diagnostics/W28_V1_johnson2017_w26r1_w27r1_replay.md`.
- Two-product-line framing → `docs/PRODUCTS.md`.

---

## 1. Why this exists

The 2026-05-18 GLM7 controlled experiment (Wang et al., *Advanced Science* 2025, "GLM7: A Novel Composite Glycolipid Index") gave us the first non-circular signal on what RAG can and cannot catch on a paper neither the team nor the KB had previously seen.

### Headline result

| Reviewer | Total flags | **CRITICAL hits (3 real)** | HIGH+ hits |
|---|---:|---:|---:|
| Independent Claude agent (strict reviewer prompt) | 10 Major + 9 Minor + 10 Questions | **3 / 3** | 6 / 7 |
| Human reading the PDF cold | 11 findings | **3 / 3** | 4 / 7 |
| **`synthesize_flags_from_rag` (W26-R1 + W27-R1)** | **9 flags** | **0 / 3** | 3 / 7 |

The 3 CRITICALs MLGG retrieval missed:

| # | Issue | Why retrieval missed it |
|---|---|---|
| **C1** | Target / definition leakage (FBG and insulin inside the predictor of a DM label defined by HbA1c ≥ 6.5%; same logic on LDL-c → CVD) | `gate=` not set → BM25 silent; KB leakage concerns ~4% post-pre-pub filter; semantic embedding maps "FBG predicts HbA1c-defined DM" to "biomarker combination", not "leakage" |
| **C2** | Cross-sectional design framed as "prediction" (NHANES has no follow-up; prevalent disease at the same visit as predictors) | No `temporal_validity_gate` exists in the KB; reviewer concerns of this shape are rare in NC peer-review (NC mostly publishes longitudinal designs) |
| **C3** | Derivation circularity — 49 → top-10 → 7 Venn-intersected variables, all on full NHANES, then formula evaluated on the same NHANES 0.7/0.3 split | Concept is in `model_selection_audit_gate` family, but query lexical surface ("univariate ROC + Venn diagram") is far from KB phrasing about "hyperparameter tuning on test set" |

MLGG retrieval **did** complementary work that the LLM agent missed: calibration / DCA absence, AUROC-without-CI, sample-size in subgroups, reporting-bias quantification. The two layers are **complementary, not redundant**.

### Conclusion that this commit operationalizes

The product is `LLM → RAG enrichment → consolidated report`, not `RAG → LLM cleanup`.

## 2. Architecture (shipped this commit)

```
PDF
 ↓ extract_methods_section()
methods_text
 ↓ Anthropic Claude messages.parse() with output_format=LlmAuditOutput
LlmAuditOutput (major[], minor[], questions[])
 ↓ enrich_with_rag() — for each concern call rag_query(
 ↓     query=f"{c.headline}. {c.body}",
 ↓     gate=c.suggested_gate_hint,    # ← key: activates BM25 in hybrid_rank
 ↓     top_k=3, min_score=0.2,        # ← W27-R2 floor
 ↓ )
AuditReport (major[EnrichedConcern], minor[EnrichedConcern], questions[])
```

**Three things worth noting** about the wiring:

1. **`suggested_gate_hint` is what makes RAG enrichment useful.** The hybrid ranker only activates BM25 when `gate=` is set (SKILL.md §Hybrid retrieval caveat). The system prompt enumerates the 11 candidate gates so the LLM can pick one per concern; downstream `enrich_with_rag()` forwards the hint verbatim. Free-text RAG retrieval is left as the fallback.

2. **RAG citations are background, not ground truth.** Each KB record is rendered as `concern_id (score X.XX): excerpt…` under the concern. The LLM's claim is primary; the KB excerpt is the "another reviewer noticed this on a different paper" anchor. This matches the SKILL.md guidance: "Gate 失败 = leakage → 优先 lint R001-R028 + leakage_gate，KB 仅辅助".

3. **W27-R2 `min_score` plugs in here.** Default `0.2` keeps citations honest. Setting it lower includes noisier hits; setting it higher means some concerns get zero citations (which is fine — the LLM concern still stands).

## 3. Prompt design (operationalized)

The `SYSTEM_PROMPT` is the operationalized version of today's sub-agent prompt that scored 3/3 CRITICAL on GLM7. Five anti-failure-mode rules locked in:

| Failure mode the prompt is preventing | Rule in prompt |
|---|---|
| Diplomatic softening ("authors might consider…") | "NO praise, NO summary, concerns only" |
| Free-form citations / hallucinated page refs | "cite specific page+section, e.g. 'p. 14 §5'" |
| Leakage concept buried in vague language | Hard-rule: if leakage class, **use the literal word "leakage"** so it's grep-able |
| Cross-sectional-as-prediction missed | Hard-rule: use the literal phrase **"temporal validity"** |
| Formula-on-outcome derivation buried | Hard-rule: use the literal phrase **"derivation circularity"** |
| Headline being the consequence, not the flaw | "Headline is the FLAW, not its consequence" with worked example |
| LLM inflating count to look thorough | "3-12 Major is normal. Quality > quantity." |

Two of the three CRITICALs from GLM7 (C2 temporal validity, C3 derivation circularity) had no obvious matching MLGG gate, which is why the prompt **defines its own grep anchors** rather than relying on `suggested_gate_hint` to surface them. The hint is for RAG enrichment, not for issue discovery.

## 4. What this commit ships

- `scripts/review/llm_paper_audit.py` (390 LoC, ~250 of which is the public API; the rest is CLI + markdown rendering).
- `tests/test_llm_paper_audit.py` (14 tests, all mocked — no network, no SDK required to run unit suite). Coverage:
  - 3 schema-validation tests (Pydantic round-trip, severity enum, empty audit).
  - 3 prompt-construction tests (grep anchors present, gate hint list present, user prompt embeds methods text).
  - 3 `enrich_with_rag` tests (order, gate-hint forwarding, RAG failure tolerance).
  - 4 `audit_paper` end-to-end mocked tests (with/without RAG, missing PDF, empty methods).
  - 1 markdown-rendering test (all sections present).
- CLI wiring: `mlgg llm-audit <pdf>` (full surface) and `mlgg-review llm-audit <pdf>` (focused review-line surface, W28-S1).
- SKILL.md row in `[review]` group + README updates (28→29 subcommand bumps).

## 5. What this commit does NOT ship (deferred to W29-V2)

- **Actual run on GLM7 paper.** Requires the user to:
  1. `pip install anthropic>=0.40.0`
  2. `export ANTHROPIC_API_KEY=sk-ant-...`
  3. `mlgg-review llm-audit /Users/wengcan/Downloads/Advanced\ Science\ -\ 2025\ -\ Wang\ -\ GLM7*.pdf`
- **Numbers vs the W28-V1 baseline** (CRITICAL recall, KB citation hit rate, cost per audit). These will land in `docs/diagnostics/W29_V2_glm7_replay.md` after the API call.
- **Multi-paper benchmark.** GLM7 is N=1. W29-V3 would sweep 3-5 known-bad papers the user has on hand.
- **Cost telemetry.** Each audit is ~3-4 Claude Opus messages.parse calls + 5-10 rag_query calls; rough estimate $0.05-0.20/paper. Not yet measured.

## 6. Validation plan (W29-V2)

Pre-registered before the API call so we don't post-hoc shape the success criterion:

| Metric | Target | Why |
|---|---|---|
| CRITICAL recall on GLM7 (vs 3 known: leakage / temporal / derivation) | **3 / 3** | Matches today's blind agent baseline; below 3 means prompt regressed |
| KB citations attached per Major concern (median) | **≥ 1** | If 0, RAG enrichment is dead weight and we drop it from default |
| Citations whose `mlgg_gates` includes the LLM's `suggested_gate_hint` | **≥ 50 %** | Confirms `gate=` forwarding actually anchors retrieval |
| Total Major + Minor count | **8-20** | Sanity bound on noise/recall |
| Latency p50 | **< 60 s** (LLM) + **< 15 s** (RAG) | Useable as a CLI |

Anti-pre-reg (what would tell us the design is wrong):

- If CRITICAL recall < 3 → SYSTEM_PROMPT regressed; re-tune.
- If KB citations are mostly off-topic (semantic-only, no gate match) → BM25-via-`gate=` insufficient; need a separate retrieval mode for design-flaw queries.
- If LLM consistently picks `null` for `suggested_gate_hint` → gate enumeration in prompt is too long / too vague; trim to top-5.

## 7. Open architecture questions (not blocking)

- **Should the LLM call cache responses by `(methods_text_sha256, model)`?** Today's audit on the same PDF costs the same $0.05-0.20 twice. A simple disk cache under `.cache/llm_audits/` would let us iterate on prompts without re-spending. Not in MVP scope — premature optimization until the prompt stabilizes.
- **Reviewer-role variants** (`nature_methods` vs `jama` vs `bmj`): currently the prompt is generic "Nature Methods / JAMA / BMJ-level". If we find different journals want different concern severity weights, we'd parameterize. Defer until we have concrete signal that the prompt is over-fitting to one journal style.
- **Multi-LLM A/B**: The user picked Anthropic-only. We may want to A/B against DeepSeek (already wired in `extract_paper_metadata.py`) or GPT-4 once we have 3+ papers' worth of data to score. Defer.

## 8. CLAUDE.md / project guardrails honored

- `anthropic` SDK is imported **lazily** inside `call_llm_review` — module loads without it, unit tests run without it. No `pip install` performed (CLAUDE.md NEVER list).
- `ANTHROPIC_API_KEY` is read from env var, never logged, never embedded in commit messages.
- Reviewer-role prompt is a Python constant in code, not pulled from markdown — gates do not consult markdown for verdict logic (CLAUDE.md "Engineering guarantees").
- No `eval / exec / subprocess(shell=True)` (CLAUDE.md "Code Standards 禁止").
- All file writes go through `Path.write_text` + explicit encoding.
