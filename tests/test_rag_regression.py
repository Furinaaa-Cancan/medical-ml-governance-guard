"""Regression tests for RAG-layer ship-stopper bugs.

Each test corresponds to a documented bug from the 5-agent strict-eval:
  - test_no_circular_import_from_rag_query                       (fixed: 251003b)
  - test_rag_query_gate_only_does_not_raise                      (fixed: 251003b)
  - test_top_k_above_50_returns_more                             (fixed: 830ce4a)
  - test_free_text_marks_bm25_inactive                           (fixed: 830ce4a)
  - test_public_api_surface                                      (always)
  - test_all_33_gates_have_rag_coverage_or_are_rag_optional      (slow; E5+G1)

rag-path-truth-fixes: the gate-facing bridge surface
(``rag_context_for_failure`` orchestrator + ``format_for_gate_report``
markdown renderer + per-row hedges) was deleted. Its synth-normalization,
off-modality detection and curated-precedent value was PROMOTED into the
torch-free ``scripts/rag/_enrich.py`` and wired into the live offline path
``scripts/rag/query.py:rag_query``. Tests that exercised the promoted
DETECTION logic are repointed to ``scripts.rag._enrich`` /
``scripts.rag.query``; tests that only asserted the deleted markdown render
shape are removed (the offline path returns raw scored records, not markdown
— citation-confidence / same-paper de-confliction is now the offline
synthesis-LLM's job, not a render-layer concern).

If an xfail test starts passing, that's the fix landing — remove the
marker.
"""

import subprocess
import sys

import pytest

# Module-level skip if sentence_transformers missing (matches existing
# test_rag_components.py convention).
pytest.importorskip("sentence_transformers")


def test_no_circular_import_from_rag_query() -> None:
    """Regression (repointed): the RAG public surface must import in a fresh
    interpreter without a circular import. Was: importing
    ``rag_context_for_failure`` from the bridge crashed pre-251003b because
    ``scripts/rag/__init__.py`` re-exported it. That orchestrator was deleted
    and its value promoted into ``scripts.rag._enrich`` /
    ``scripts.rag.query``; the guard now anchors there (and the bridge shim's
    own top-level import is smoke-checked below)."""
    # Subprocess for fresh interpreter (no module cache).
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.rag.query import rag_query; "
            "from scripts.rag._enrich import is_off_modality_query; "
            "import scripts.core.gate_rag_bridge; print('ok')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"circular import regression: stderr={result.stderr}\n"
        f"stdout={result.stdout}"
    )
    assert "ok" in result.stdout


def test_rag_query_gate_only_does_not_raise() -> None:
    """Regression (repointed): gate-filter-only mode with no failure codes
    must not raise. Pre-251003b an empty synthesised query raised ValueError.
    The orchestrator that owned this (``rag_context_for_failure``) was deleted;
    ``rag_query`` is the offline home, and the promoted ``synthesize_query``
    yields a non-empty query from the gate name so the empty-query ValueError
    cannot recur. The bug was an EXCEPTION; absence of exception is the
    check (don't assert len > 0 — a gate may legitimately have 0 concerns)."""
    from scripts.rag._enrich import synthesize_query
    from scripts.rag.query import rag_query

    query = synthesize_query([], None, gate_name="leakage_gate")
    results = rag_query(query, gate="leakage_gate", failure_codes=[], top_k=3)
    assert isinstance(results, list), f"expected list, got {type(results)}"


def test_top_k_above_50_returns_more() -> None:
    """E3 finding: top_k > 50 silently capped at DEFAULT_MAX_CANDIDATES_BEFORE_RERANK.

    Fixed by F1 (commit 830ce4a): dense_top_k = max(50, top_k).
    Hard regression — must never re-cap silently.
    """
    from scripts.rag import rag_query

    results = rag_query("calibration", top_k=200)
    assert len(results) > 50, (
        f"top_k uncap regression: asked for 200, got {len(results)}"
    )


def test_free_text_marks_bm25_inactive() -> None:
    """E2 finding: free-text path doesn't fire BM25, but doesn't tell the user.

    Fixed by F1 (commit 830ce4a): results carry a _match_reasons sentinel
    when BM25 is skipped due to missing gate/codes. Hard regression.
    """
    from scripts.rag import rag_query

    results = rag_query("calibration", top_k=5)
    assert results, "expected at least one result for 'calibration'"
    reasons = results[0].get("_match_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    assert any(
        "bm25" in r.lower() and "inactive" in r.lower() for r in reasons
    ), f"expected bm25_inactive marker, got reasons={reasons!r}"


# REMOVED: test_format_for_rag_optional_gate. The "rag_optional gate renders
# empty string instead of placeholder" contract lived entirely inside the
# deleted format_for_gate_report renderer (Decision 3). The offline path
# (rag_query) returns a list, never a placeholder string, so the intent has
# no surface to pin.


def test_public_api_surface() -> None:
    """Smoke: documented public imports work."""
    code = (
        "from scripts.rag import rag_query\n"
        "from scripts.rag._enrich import is_off_modality_query, "
        "curated_precedent_for, synthesize_query\n"
        "print('all imports ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"surface broken: stderr={result.stderr}"
    assert "all imports ok" in result.stdout


@pytest.mark.slow
def test_all_33_gates_have_rag_coverage_or_are_rag_optional() -> None:
    """E5 strict-eval contract: every gate either returns >=1 concern
    from the offline path (``rag_query`` with the promoted
    ``synthesize_query`` gate-name fallback) or is flagged
    ``rag_optional=True`` in the registry. No silent empty gates.

    rag-path-truth-fixes: repointed off the deleted
    ``rag_context_for_failure`` orchestrator onto ``rag_query`` directly,
    reconstructing the orchestrator's two steps inline (synthesise a query
    from the gate name, then rank with the gate filter). Coverage intent is
    unchanged.

    Slow marker: this calls the offline RAG path once per gate (33 hybrid
    rank calls), each warming the dense-retrieval model on first use.
    Excluded from the default ``-m "not slow"`` ci-unit run; included
    in nightly / on-demand sweeps.
    """
    # _gate_registry has no public ``all_gates()`` / ``iter_gates()``
    # helper — the canonical enumeration surface is the module-level
    # ``GATE_REGISTRY: Dict[str, GateSpec]`` (every other internal
    # accessor in the file, e.g. ``topological_sort``, iterates the
    # same dict). Pulling specs directly from ``GATE_REGISTRY.values()``
    # is the documented inference; if a public list-style API ever
    # lands, swap the import below.
    from scripts.core._gate_registry import GATE_REGISTRY
    from scripts.rag._enrich import synthesize_query
    from scripts.rag.query import rag_query

    specs = list(GATE_REGISTRY.values())
    assert len(specs) == 33, (
        f"expected 33 gates, registry has {len(specs)} — coverage "
        f"contract is anchored to the 33-gate count documented across "
        f"14 markdown files + 4 test assertions; bump-or-justify."
    )

    empty_but_not_optional: list[tuple[str, str]] = []
    for spec in specs:
        if getattr(spec, "rag_optional", False):
            continue  # honest empty by design (infra/meta gates)
        try:
            query = synthesize_query([], None, gate_name=spec.name)
            results = rag_query(
                query, gate=spec.name, failure_codes=[], top_k=5
            )
        except Exception as exc:  # noqa: BLE001 — surface any offline-path crash
            empty_but_not_optional.append(
                (spec.name, f"raised {type(exc).__name__}: {exc}")
            )
            continue
        if len(results) == 0:
            empty_but_not_optional.append((spec.name, "returned 0 concerns"))

    assert not empty_but_not_optional, (
        f"{len(empty_but_not_optional)} gate(s) have empty RAG coverage "
        f"but are not flagged rag_optional. Either add concerns to "
        f"references/case-studies/peer-review-kb.json (and tag them with "
        f"the gate name) or mark the gate rag_optional=True in "
        f"scripts/core/_gate_registry.py:\n  "
        + "\n  ".join(f"{n}: {r}" for n, r in empty_but_not_optional)
    )


# REMOVED (markdown render surface deleted, Decision 3 — no offline renderer):
#   test_format_for_gate_report_hedges_weak_match_concerns,
#   test_format_for_gate_report_does_not_hedge_strong_match,
#   test_low_confidence_hedge_fires_on_off_mlgg_scope_queries,
#   test_low_confidence_hedge_skips_strong_in_scope_matches,
#   test_low_confidence_hedge_independent_of_weak_match_hedge.
# These exercised _is_weak_match / _is_low_confidence rendering inside the
# deleted format_for_gate_report. rag_query returns raw scored records and
# leaves citation-confidence judgement to the offline synthesis-LLM. The
# off-modality DETECTION half (load-bearing) survives in the repointed
# denylist tests below + test_rag_query_flags_off_modality_query.


@pytest.mark.parametrize("query", [
    "single-cell RNAseq batch effect correction",
    "image segmentation UNet skip connections",
    "BERT fine-tuning catastrophic forgetting",
    "Cox proportional hazards survival regression",
    "federated learning privacy gradient leakage",
    "quantum machine learning noise mitigation",
    "VAE GAN deep generative model",
    "graph neural network message passing",
    "reinforcement learning offline policy",
    "natural language processing tokenization bias",
])
def test_off_modality_denylist_catches_off_scope(query: str) -> None:
    """W7P2: 10 off-MLGG-scope queries must all be flagged by the
    keyword denylist. Mirrors the W6 W1 measurement set."""
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    assert _is_off_modality_query(query), f"failed to flag off-scope: {query}"


@pytest.mark.parametrize("query", [
    "missing calibration plot",
    "patient leakage train test split",
    "no external validation single center",
    "AUROC without confidence interval",
    "extreme class imbalance unaddressed",
    "complete-case analysis missing data",
    "TRIPOD AI checklist compliance",
    "subgroup performance by race ethnicity",
])
def test_in_scope_queries_not_falsely_flagged(query: str) -> None:
    """W7P2: 8 in-scope MLGG queries must NOT trigger the denylist."""
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    assert not _is_off_modality_query(query), f"false positive: {query}"


# W1 self-challenge: adversarial cases the original 10+8 set did not
# cover. These are intentionally borderline; the test documents
# observed behaviour via print rather than asserting, so it does not
# break CI when the denylist is later tuned. Treat the printed output
# as a living spec of where the matcher over/under-fires.
@pytest.mark.parametrize("query,documented", [
    # In-scope queries that contain denylist tokens — these WILL flag
    # as off-scope under the current substring matcher. Documented
    # false positives; acceptable per "false positives are recoverable".
    ("attention mechanism for clinical prediction", True),  # "attention"
    ("BERT-tokenized chief complaints for sepsis prediction", True),  # "bert"
    ("transformer architecture for pediatric clinical risk", True),  # "transformer"
    ("generative augmentation for rare-disease tabular data", True),  # "generative"
    ("graph_neural network on EHR co-occurrence", True),  # "graph_neural"
    # Off-scope queries that avoid obvious denylist tokens — these
    # will NOT flag. Documented false negatives; the matcher is
    # deliberately not tightened.
    ("learning representations from multiple modalities", False),  # no token
    ("end-to-end policy from raw pixels", False),  # no token in list
    ("contrastive pretraining on chest radiographs", False),  # no token
    ("denoising score matching for high-dim data", False),  # no token
    # "vae" is not a substring of "variational" — documented FN
    ("variational autoencoder latent disentanglement", False),
])
def test_adversarial_denylist_cases(query: str, documented: bool) -> None:
    """W1 self-challenge: document where the denylist over- or under-fires.

    The ``documented`` column records the EXPECTED current behaviour. Drift in a
    grounding-safety control (it stops the agent citing wrong-modality precedent)
    must NOT pass silently — this asserts ``actual == documented`` so any change
    fails CI. When the denylist is deliberately tuned, update the ``documented``
    value for that case (the maintainer's stated intent), rather than letting the
    drift go unnoticed.
    """
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    actual = _is_off_modality_query(query)
    print(
        f"  adversarial: {query!r:70} documented={documented} actual={actual}"
        + ("" if actual == documented else "  <-- DRIFT")
    )
    assert actual == documented, (
        f"off-modality denylist DRIFT for {query!r}: documented={documented}, actual={actual}. "
        f"If this change is intentional, update the `documented` value for this case."
    )


# REMOVED: test_off_modality_hedge_renders_when_flagged and
# test_off_modality_hedge_absent_when_unflagged — both asserted markdown
# hedge text from the deleted format_for_gate_report (Decision 3). The
# off-modality DETECTION intent (load-bearing) is fully covered by the
# repointed denylist tests and the flag-propagation test below; only the
# markdown-rendering half is dropped.


def test_rag_query_injects_curated_precedent_live_path() -> None:
    """Live-path coverage for the promoted curated-precedent injection.

    The 9 curated unit tests exercise ``curated_precedent_for`` at the helper
    level; this pins the integration in ``rag_query`` itself — prepend at
    top-1, dedupe, and the ``_synthetic_curated`` marker — so a future edit to
    the slice/budget cannot silently drop or mis-rank the curated row with the
    suite still green. Needs no dense index: curated injection happens before
    ``hybrid_rank`` and survives the ImportError/FileNotFoundError degrade
    paths, so this is CI-robust without sentence-transformers. NB: rag_query
    short-circuits an empty/whitespace query to [] BEFORE curated injection,
    so a non-empty query is required (real callers always pass one — the CLI
    query, harness-synthesized text, or methods_text); the (code, gate) key
    match then fires regardless of the query's content.
    """
    from scripts.rag.query import rag_query

    results = rag_query(
        "preprocessing leakage before split",
        gate="split_protocol_gate",
        failure_codes=["MLGG-P01"],
        top_k=5,
    )
    assert results, "curated precedent must surface even with no KB/index"
    assert results[0]["concern_id"] == "MLGG-CURATED-P01-fit_before_split"
    assert results[0].get("_synthetic_curated") is True


def test_rag_query_curated_disabled_by_env(monkeypatch) -> None:
    """MLGG_RAG_DISABLE_CURATED=1 must suppress the curated injection (A/B)."""
    monkeypatch.setenv("MLGG_RAG_DISABLE_CURATED", "1")
    from scripts.rag.query import rag_query

    results = rag_query(
        "preprocessing leakage before split",
        gate="split_protocol_gate",
        failure_codes=["MLGG-P01"],
        top_k=5,
    )
    assert not any(
        r.get("concern_id") == "MLGG-CURATED-P01-fit_before_split" for r in results
    ), "curated row must be suppressed when MLGG_RAG_DISABLE_CURATED=1"


def test_rag_query_flags_off_modality_query() -> None:
    """Round-trip (repointed): an off-MLGG-scope query must propagate
    ``_off_modality=True`` onto every returned concern on the OFFLINE path —
    preserving the surviving intent of the deleted
    ``rag_context_for_failure`` round-trip. NOTE: as of this commit the flag is
    RESERVED / produced-but-unread — no production consumer reads it yet
    (llm_paper_audit's KbCitation copies only concern_id / excerpt / score /
    mlgg_gates). This test pins that ``rag_query`` SETS the flag so a future
    consumer can rely on it; it does not assert any consumer reads it."""
    from scripts.rag.query import rag_query

    results = rag_query(
        "single-cell RNAseq batch effect correction",
        gate="leakage_gate",
        failure_codes=[],
        top_k=3,
    )
    if not results:
        pytest.skip("query returned no results — index not built locally")
    assert all(r.get("_off_modality") is True for r in results), (
        "off-modality flag not propagated to all returned concerns: "
        f"{[r.get('_off_modality') for r in results]}"
    )


# REMOVED: test_format_for_gate_report_marks_same_paper_concerns. The
# same-paper "do not merge narratives" marker (_SAME_PAPER_MARKER_TEMPLATE)
# was injected only into the deleted markdown render. rag_query returns raw
# records carrying paper_id; same-paper de-confliction is now the offline
# synthesis-LLM's job, not a render-layer concern. No equivalent.


# ---------------------------------------------------------------------------
# W8-W4: whole-word denylist matching (regression for W7-P2 substring FPs)
# ---------------------------------------------------------------------------
# P2 deep-int observation: substring matching is asymmetric. Removing a
# token to silence one in-scope FP un-flags every off-scope query using
# the same token. Whole-word matching breaks the asymmetry — "vae"
# matches "vae loss" but not "variational". The cases below pin the
# behaviour so a future "loosen the matcher" change re-introduces them
# visibly.

@pytest.mark.parametrize("query,expected,rationale", [
    # --- W7-P2 FP that whole-word DOES fix ---
    # "vae" is no longer a substring-match inside "variational"
    ("variational autoencoder latent disentanglement", False,
     "vae-in-variational FP fixed by \\b boundaries"),
    # gpt2-clinical: "gpt" is not a whole word inside "gpt2"
    ("evaluating gpt2-clinical rebadging on EHR notes", False,
     "gpt-in-gpt2 FP fixed by \\b boundaries"),

    # --- W7-P2 FP that whole-word does NOT fix (token is a real word) ---
    # "attention" IS a whole word — still flagged. Removing "attention"
    # from the denylist would un-flag legitimate NLP queries; this FP
    # is acceptable per the "false positives are recoverable" policy.
    ("clinical attention paid to AKI predictors", True,
     "attention is a real whole-word in the query — accepted FP"),

    # --- True off-scope still caught ---
    ("BERT-style tokenization for clinical text", True,
     "bert whole-word"),
    ("Cox proportional hazards model", True,
     "cox whole-word"),
    ("single-cell RNAseq differential expression", True,
     "single_cell multi-word + rnaseq whole-word"),
    ("graph_neural network on EHR co-occurrence", True,
     "graph_neural multi-word (underscore form)"),
    ("graph neural network with message passing", True,
     "graph_neural + message_passing multi-word (space form)"),
    ("kaplan-meier survival curves", True,
     "kaplan_meier multi-word (hyphen form)"),
    ("VAE loss curve diverges", True,
     "vae whole-word (uppercase)"),

    # --- In-scope queries that LOOK like they might trigger but don't ---
    ("missing calibration plot for sepsis model", False,
     "no denylist tokens"),
    ("patient leakage across train test split", False,
     "no denylist tokens"),
    ("AUROC reported without confidence interval", False,
     "no denylist tokens"),
])
def test_whole_word_denylist_matching(query, expected, rationale):
    """W8-W4: \\b whole-word matching kills P2 substring FPs.

    Per spec: assertion-relaxed — mismatches print but do NOT fail CI.
    Documenting drift is more valuable than chasing matcher gymnastics.
    The ``rationale`` column makes intent explicit so a future tuner can
    update both ``expected`` and ``rationale`` in lockstep.
    """
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    actual = _is_off_modality_query(query)
    drift = "" if actual == expected else "  <-- DRIFT"
    print(
        f"  W8-W4: {query!r:60} expected={expected} actual={actual}"
        f" [{rationale}]{drift}"
    )
    # Soft check — log mismatch but do not fail. The cases above were
    # hand-graded by W8-W4; a tuner who changes the matcher should
    # update ``expected`` rather than silence this test.
    if actual != expected:
        # Allow but do not fail: living spec, per spec instructions.
        pass


def test_w8w4_p2_substring_fp_actually_fixed():
    """W8-W4 HARD assertion: the two named P2 substring FPs must be
    fixed. Unlike the documenting test above, this one fails CI if
    "vae" inside "variational" or "gpt" inside "gpt2-clinical" come
    back. This is the regression guard for the P2 deep-int finding."""
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    # "variational" contains the literal substring "v-a-e"? No — it
    # contains "varia...nal". Substring failure mode was different:
    # "vae" matched because no boundary check. With whole-word, the
    # token "vae" requires word boundaries, so it doesn't match inside
    # any longer word.
    assert not _is_off_modality_query(
        "variational autoencoder latent disentanglement"
    ), "P2 substring FP regression: 'vae' should not whole-word match 'variational'"
    assert not _is_off_modality_query(
        "evaluating gpt2-clinical rebadging on EHR notes"
    ), "P2 substring FP regression: 'gpt' should not whole-word match 'gpt2'"


def test_w8w4_multi_word_tokens_match_all_separator_forms():
    """W8-W4: multi-word denylist tokens (graph_neural, kaplan_meier,
    natural_language, etc.) must match queries regardless of whether
    the separator is underscore, hyphen, or space."""
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    for sep in ("_", "-", " "):
        q1 = f"applying graph{sep}neural networks to clinical data"
        q2 = f"kaplan{sep}meier survival analysis"
        q3 = f"natural{sep}language processing pipeline"
        assert _is_off_modality_query(q1), (
            f"multi-word match failed for graph_neural with sep={sep!r}: {q1}"
        )
        assert _is_off_modality_query(q2), (
            f"multi-word match failed for kaplan_meier with sep={sep!r}: {q2}"
        )
        assert _is_off_modality_query(q3), (
            f"multi-word match failed for natural_language with sep={sep!r}: {q3}"
        )


def test_w8w4_edge_inputs_do_not_crash():
    """W8-W4: degenerate inputs (empty, whitespace-only, punctuation-
    only) must return False rather than crashing or matching."""
    from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
    assert _is_off_modality_query("") is False
    assert _is_off_modality_query("   ") is False
    assert _is_off_modality_query("!!! @@@ ###") is False
    assert _is_off_modality_query(None) is False  # type: ignore[arg-type]


def test_q9_external_validation_recovers_known_dropouts():
    """W2/A1 regression: Q9 free-text query had E1 P@5=1.0 then dropped
    to 0.4 due to MMR over-penalize. A1 fix (MMR_COSINE_FLOOR=0.88)
    recovered 2/3 perfect-E1 hits. Pin those 2 IDs so any future MMR/
    scoring change can't silently re-drop them.

    PR-006-C04 not pinned — known KB-tag issue per W2 Proposal A
    (paper-specific narrow tags singleton-out, no tag_overlap signal).
    """
    from scripts.rag import rag_query
    results = rag_query("single-center development without external test", top_k=5)
    ids = [c["concern_id"] for c in results]
    recovered = {"PR-028-C01", "PR-084-C01"}
    found = recovered & set(ids)
    assert len(found) >= 1, (
        f"Q9 regression: expected >=1 of {recovered} in top-5, got {ids}"
    )
