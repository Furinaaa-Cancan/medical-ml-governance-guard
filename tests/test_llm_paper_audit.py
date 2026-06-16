"""Unit tests for W29-MVP + W31-S1 ``scripts/review/llm_paper_audit``.

All tests run without the ``anthropic`` SDK or an API key: the LLM call
is mocked via ``unittest.mock.patch`` at the function boundary
(``call_llm_review``). The RAG calls are also mocked via the
``scripts.rag.query.rag_query`` import boundary.

W31-S1 added the ``rag_strategy`` parameter (replacing the binary
``use_rag_enrichment``) with three modes: ``"primed"`` (KB context in
prompt, default), ``"post_hoc"`` (W29-MVP behaviour, per-concern
enrichment after LLM), and ``"off"`` (LLM only).
"""
from __future__ import annotations

from unittest import mock

import pytest

from scripts.review.llm_paper_audit import (
    AuditReport,
    Concern,
    EnrichedConcern,
    KbCitation,
    LlmAuditOutput,
    SYSTEM_PROMPT,
    _build_user_prompt,
    _format_kb_context_for_prompt,
    _format_report_markdown,
    _retrieve_rag_context_for_priming,
    audit_paper,
    enrich_with_rag,
)


# ─────────────────────────────────────────────────────────────────────────
# Schema tests
# ─────────────────────────────────────────────────────────────────────────


def test_concern_schema_minimal_round_trip():
    """A Concern with only the required fields validates and serializes."""
    c = Concern(
        headline="predictor contains FBG while DM defined by HbA1c (leakage)",
        severity="CRITICAL",
        body="See p. 14 §5 Definition of Data. GLM7 includes FBG; DM = HbA1c >= 6.5%.",
    )
    d = c.model_dump()
    assert d["severity"] == "CRITICAL"
    assert d["suggested_gate_hint"] is None
    assert d["page_cites"] == []


def test_concern_severity_validation_rejects_unknown_value():
    """Pydantic enum-style validator rejects anything off the Severity literal."""
    with pytest.raises(Exception):  # ValidationError under pydantic v2
        Concern(headline="x", severity="WAT", body="y")  # type: ignore[arg-type]


def test_llm_audit_output_empty_is_valid():
    """Empty audit (no concerns found) is a valid LlmAuditOutput."""
    out = LlmAuditOutput()
    assert out.major_concerns == []
    assert out.minor_concerns == []
    assert out.questions_for_authors == []


# ─────────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────────


def test_system_prompt_carries_leakage_and_circularity_keywords():
    """The prompt must keep its grep-able keywords so we can verify in
    audit outputs that the LLM was instructed to surface them."""
    for keyword in ("leakage", "derivation circularity", "temporal validity"):
        assert keyword in SYSTEM_PROMPT, (
            f"prompt is missing grep-anchor for {keyword!r} — keep this verbatim"
        )


def test_system_prompt_lists_gate_hints():
    """The prompt enumerates concrete gate hints so the LLM picks from
    them; downstream RAG enrichment relies on these matching real KB tags."""
    for gate in (
        "leakage_gate",
        "calibration_dca_gate",
        "external_validation_gate",
        "split_protocol_gate",
        "cohort_definition_gate",
        "ci_matrix_gate",
    ):
        assert gate in SYSTEM_PROMPT


def test_system_prompt_disciplines_kb_use():
    """W31-S1: the prompt must include the R1-R5 anti-rubber-stamp rules
    so the LLM doesn't auto-apply KB concerns to every paper."""
    for anchor in (
        "REFERENCE PEER REVIEWS",
        "calibration,\n    NOT ground truth",
        "independently verify",
        "NEVER raise a concern just because",
    ):
        assert anchor in SYSTEM_PROMPT, f"prompt missing R1-R5 anchor: {anchor!r}"


def test_user_prompt_embeds_methods_text_and_label():
    msg = _build_user_prompt(
        methods_text="<<METHODS BODY>>",
        paper_label="glm7_paper",
    )
    assert "<<METHODS BODY>>" in msg
    assert "glm7_paper" in msg
    assert "LlmAuditOutput" in msg


def test_user_prompt_without_kb_context_has_no_reference_section():
    """W31-S1: when kb_context is None or empty, no KB block is rendered."""
    msg = _build_user_prompt("methods", "p", kb_context=None)
    assert "Reference peer-review concerns" not in msg
    msg2 = _build_user_prompt("methods", "p", kb_context=[])
    assert "Reference peer-review concerns" not in msg2


def test_user_prompt_with_kb_context_renders_excerpts_before_methods():
    """W31-S1: priming mode injects KB excerpts BEFORE the methods text so
    the LLM reads them as calibration during opinion formation."""
    kb = [
        KbCitation(concern_id="PR-001-C02", excerpt="def-var leakage example",
                   score=0.82, mlgg_gates=["leakage_gate"]),
        KbCitation(concern_id="PR-021-C04", excerpt="no calibration reported",
                   score=0.65, mlgg_gates=["calibration_dca_gate"]),
    ]
    msg = _build_user_prompt(
        methods_text="<<METHODS BODY>>",
        paper_label="glm7",
        kb_context=kb,
    )
    # Each KB excerpt appears
    assert "PR-001-C02" in msg
    assert "PR-021-C04" in msg
    # KB block comes BEFORE methods body (priming, not citation)
    assert msg.index("PR-001-C02") < msg.index("<<METHODS BODY>>"), (
        "KB context must precede methods text in priming mode"
    )


def test_format_kb_context_empty_returns_empty_string():
    assert _format_kb_context_for_prompt([]) == ""


def test_format_kb_context_truncates_long_excerpts():
    """Excerpts >240 chars are truncated with ellipsis to bound prompt size."""
    long = "x" * 500
    kb = [KbCitation(concern_id="PR-A", excerpt=long, score=0.5, mlgg_gates=[])]
    out = _format_kb_context_for_prompt(kb)
    assert "…" in out
    assert "x" * 250 not in out  # full 500 not present


# ─────────────────────────────────────────────────────────────────────────
# RAG retrieval — primed mode (W31-S1) and post_hoc enrichment (W29-MVP)
# ─────────────────────────────────────────────────────────────────────────


def _kb_rec(cid: str, text: str, score: float, gates: list[str]) -> dict:
    return {
        "concern_id": cid,
        "concern_text": text,
        "_final_score": score,
        "mlgg_gates": gates,
    }


# --- priming retrieval ---


def test_retrieve_rag_context_for_priming_does_two_passes():
    """W31-S1: priming calls rag_query TWICE — once free-text, once with
    gate='leakage_gate' — so leakage-class concerns surface even when the
    methods text doesn't say the word 'leakage' (W30-R1 logic)."""
    calls: list[dict] = []

    def fake_rq(**kwargs):
        calls.append(kwargs)
        if kwargs.get("gate") == "leakage_gate":
            return [_kb_rec("PR-001-C02", "leakage example", 0.85, ["leakage_gate"])]
        return [_kb_rec("PR-007-C01", "topic match", 0.55, ["cohort_definition_gate"])]

    with mock.patch("scripts.rag.query.rag_query", side_effect=fake_rq):
        pool = _retrieve_rag_context_for_priming(
            "methods text", top_k_general=5, top_k_leakage=3
        )

    assert len(calls) == 2
    assert calls[0].get("gate") is None         # free-text first
    assert calls[1].get("gate") == "leakage_gate"  # leakage probe second
    assert calls[1].get("failure_codes"), (
        "leakage_gate priming call must pass failure_codes so BM25 is active; "
        f"got {calls[1]!r}"
    )
    assert "definition_variable_leakage" in calls[1]["failure_codes"]
    ids = {c.concern_id for c in pool}
    assert ids == {"PR-001-C02", "PR-007-C01"}


def test_retrieve_rag_context_merges_by_concern_id_taking_higher_score():
    """When both passes return the same concern_id, the higher-score
    record wins; duplicates are removed."""
    def fake_rq(**kwargs):
        if kwargs.get("gate") == "leakage_gate":
            return [_kb_rec("PR-X", "high", 0.90, ["leakage_gate"])]
        return [_kb_rec("PR-X", "low", 0.30, ["leakage_gate"])]

    with mock.patch("scripts.rag.query.rag_query", side_effect=fake_rq):
        pool = _retrieve_rag_context_for_priming("methods", top_k_general=3, top_k_leakage=3)

    assert len(pool) == 1
    assert pool[0].concern_id == "PR-X"
    assert pool[0].score == pytest.approx(0.90)
    assert pool[0].excerpt.startswith("high")


def test_retrieve_rag_context_sorts_by_score_descending():
    def fake_rq(**kwargs):
        if kwargs.get("gate") == "leakage_gate":
            return [
                _kb_rec("PR-A", "a", 0.30, []),
                _kb_rec("PR-B", "b", 0.90, []),
            ]
        return [
            _kb_rec("PR-C", "c", 0.60, []),
            _kb_rec("PR-D", "d", 0.50, []),
        ]

    with mock.patch("scripts.rag.query.rag_query", side_effect=fake_rq):
        pool = _retrieve_rag_context_for_priming("methods", top_k_general=5, top_k_leakage=5)

    scores = [p.score for p in pool]
    assert scores == sorted(scores, reverse=True)
    assert pool[0].concern_id == "PR-B"  # highest


def test_retrieve_rag_context_tolerates_failing_rag_query():
    """Priming retrieval must degrade to [] (not crash) when RAG is cold."""
    def boom(**_kw):
        raise RuntimeError("KB unavailable")

    with mock.patch("scripts.rag.query.rag_query", side_effect=boom):
        pool = _retrieve_rag_context_for_priming("methods")
    assert pool == []


# --- post_hoc enrichment ---


def test_enrich_with_rag_attaches_citations_in_input_order():
    """Each input concern gets its own citation list; order is preserved."""
    concerns = [
        Concern(
            headline="leakage of FBG",
            severity="CRITICAL",
            body="...",
            suggested_gate_hint="leakage_gate",
        ),
        Concern(
            headline="no calibration",
            severity="HIGH",
            body="...",
            suggested_gate_hint="calibration_dca_gate",
        ),
    ]

    def fake_rag_query(query, gate=None, top_k=3, min_score=0.0, **_):
        if gate == "leakage_gate":
            return [_kb_rec("PR-001-C02", "definition variable leakage example", 0.81, ["leakage_gate"])]
        if gate == "calibration_dca_gate":
            return [
                _kb_rec("PR-021-C04", "calibration not reported", 0.65, ["calibration_dca_gate"]),
                _kb_rec("PR-022-C01", "DCA missing", 0.55, ["calibration_dca_gate"]),
            ]
        return []

    with mock.patch("scripts.rag.query.rag_query", side_effect=fake_rag_query):
        enriched = enrich_with_rag(concerns, top_k=3, min_score=0.0)

    assert len(enriched) == 2
    assert enriched[0].concern.headline == "leakage of FBG"
    assert len(enriched[0].kb_citations) == 1
    assert enriched[0].kb_citations[0].concern_id == "PR-001-C02"
    assert enriched[0].kb_citations[0].score == pytest.approx(0.81)
    assert enriched[1].kb_citations[0].mlgg_gates == ["calibration_dca_gate"]


def test_enrich_with_rag_passes_gate_hint_through():
    """Gate hints are forwarded, and leakage hints carry BM25 probe codes."""
    calls: list[dict] = []

    def capture(query, gate=None, top_k=3, min_score=0.0, **kwargs):
        calls.append({
            "query": query,
            "gate": gate,
            "top_k": top_k,
            "min_score": min_score,
            **kwargs,
        })
        return []

    concerns = [
        Concern(headline="A", severity="CRITICAL", body="b", suggested_gate_hint="leakage_gate"),
        Concern(headline="B", severity="HIGH", body="b", suggested_gate_hint=None),
    ]
    with mock.patch("scripts.rag.query.rag_query", side_effect=capture):
        enrich_with_rag(concerns)
    assert [c.get("gate") for c in calls] == ["leakage_gate", None]
    assert calls[0].get("failure_codes"), (
        f"leakage_gate enrichment must supply BM25 failure_codes; got {calls[0]!r}"
    )
    assert "definition_variable_leakage" in calls[0]["failure_codes"]
    assert calls[1].get("failure_codes") is None


def test_enrich_with_rag_tolerates_failing_rag_query():
    """A crash inside rag_query (e.g. KB cache cold) must not kill the audit."""
    def boom(*_a, **_kw):
        raise RuntimeError("KB unavailable")

    concerns = [Concern(headline="x", severity="HIGH", body="y")]
    with mock.patch("scripts.rag.query.rag_query", side_effect=boom):
        enriched = enrich_with_rag(concerns)
    assert len(enriched) == 1
    assert enriched[0].kb_citations == []


# ─────────────────────────────────────────────────────────────────────────
# audit_paper — end-to-end across all three rag_strategy modes
# ─────────────────────────────────────────────────────────────────────────


_FAKE_LLM_OUT = LlmAuditOutput(
    major_concerns=[
        Concern(
            headline="leakage: FBG in predictor of HbA1c-defined DM",
            severity="CRITICAL",
            body="See p. 14. GLM7 includes FBG; DM defined via HbA1c.",
            page_cites=["p. 14 §5"],
            suggested_gate_hint="leakage_gate",
        ),
    ],
    minor_concerns=[],
    questions_for_authors=["Refit without FBG and report AUROC delta."],
)


def _make_fake_pdf(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def test_audit_paper_post_hoc_mode_is_default(tmp_path):
    """W31-V2: rag_strategy='post_hoc' is now the default (demoted from
    'primed' after the GLM7 3-way ablation found primed-mode KB pool is
    missingness-biased and the leakage_probe path is dead on long methods
    text). post_hoc runs the LLM with no KB context, then enriches per
    concern with targeted rag_query."""
    fake_pdf = _make_fake_pdf(tmp_path)
    captured_kb: list = []

    def fake_call_llm(*, kb_context=None, **_kw):
        captured_kb.append(kb_context)
        return _FAKE_LLM_OUT

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="some methods text",
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            side_effect=fake_call_llm,
        ),
        mock.patch(
            "scripts.rag.query.rag_query",
            return_value=[_kb_rec("PR-007-C01", "FBG-as-feature", 0.78, ["leakage_gate"])],
        ),
    ):
        report = audit_paper(fake_pdf)  # default = post_hoc per W31-V2

    assert report.rag_strategy == "post_hoc"
    # LLM was called WITHOUT KB context in post_hoc mode
    assert captured_kb == [None]
    # KB pool is empty (priming not used)
    assert report.kb_context_pool == []
    # per-concern citation attached
    assert len(report.major_concerns[0].kb_citations) == 1
    assert report.major_concerns[0].kb_citations[0].concern_id == "PR-007-C01"


def test_audit_paper_primed_mode_explicit_opt_in(tmp_path):
    """W31-S1 priming behaviour preserved as explicit opt-in (no longer
    default per W31-V2). When rag_strategy='primed' is requested, KB
    context is retrieved first and injected into the LLM prompt."""
    fake_pdf = _make_fake_pdf(tmp_path)
    captured_kb: list = []

    def fake_call_llm(*, kb_context=None, **_kw):
        captured_kb.append(kb_context)
        return _FAKE_LLM_OUT

    def fake_rq(**kwargs):
        if kwargs.get("gate") == "leakage_gate":
            return [_kb_rec("PR-A", "leakage example", 0.85, ["leakage_gate"])]
        return [_kb_rec("PR-B", "topic match", 0.55, [])]

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="some methods text",
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            side_effect=fake_call_llm,
        ),
        mock.patch("scripts.rag.query.rag_query", side_effect=fake_rq),
    ):
        report = audit_paper(fake_pdf, rag_strategy="primed")

    assert report.rag_strategy == "primed"
    assert len(captured_kb) == 1
    kb_seen = captured_kb[0]
    assert kb_seen is not None
    assert {kb.concern_id for kb in kb_seen} == {"PR-A", "PR-B"}
    assert {kb.concern_id for kb in report.kb_context_pool} == {"PR-A", "PR-B"}
    assert report.major_concerns[0].kb_citations == []


def test_audit_paper_post_hoc_mode_preserves_w29_mvp_behaviour(tmp_path):
    """rag_strategy='post_hoc' is the original W29-MVP path: LLM first,
    then per-concern enrichment. kb_context_pool is empty."""
    fake_pdf = _make_fake_pdf(tmp_path)

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="some methods text",
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            return_value=_FAKE_LLM_OUT,
        ),
        mock.patch(
            "scripts.rag.query.rag_query",
            return_value=[_kb_rec("PR-007-C01", "FBG-as-feature", 0.78, ["leakage_gate"])],
        ),
    ):
        report = audit_paper(fake_pdf, rag_strategy="post_hoc")

    assert report.rag_strategy == "post_hoc"
    assert report.kb_context_pool == []      # priming pool empty
    # per-concern citation attached
    assert len(report.major_concerns[0].kb_citations) == 1
    assert report.major_concerns[0].kb_citations[0].concern_id == "PR-007-C01"


def test_audit_paper_off_mode_does_zero_rag_calls(tmp_path):
    """rag_strategy='off' must never call rag_query. Useful as baseline."""
    fake_pdf = _make_fake_pdf(tmp_path)

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="some methods text",
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            return_value=_FAKE_LLM_OUT,
        ),
        mock.patch("scripts.rag.query.rag_query") as mocked_rag,
    ):
        report = audit_paper(fake_pdf, rag_strategy="off")

    mocked_rag.assert_not_called()
    assert report.rag_strategy == "off"
    assert report.kb_context_pool == []
    assert report.major_concerns[0].kb_citations == []


def test_audit_paper_primed_mode_passes_methods_chars_and_sha256(tmp_path):
    fake_pdf = _make_fake_pdf(tmp_path)
    text = "abc methods"
    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value=text,
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            return_value=_FAKE_LLM_OUT,
        ),
        mock.patch("scripts.rag.query.rag_query", return_value=[]),
    ):
        report = audit_paper(fake_pdf)
    assert report.methods_text_chars == len(text)
    assert len(report.methods_text_sha256) == 64


def test_audit_paper_raises_on_missing_pdf(tmp_path):
    with pytest.raises(FileNotFoundError):
        audit_paper(tmp_path / "does_not_exist.pdf")


def test_audit_paper_raises_on_empty_methods_extraction(tmp_path):
    fake_pdf = _make_fake_pdf(tmp_path)
    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="   \n  \n",
        ),
        pytest.raises(RuntimeError, match="Methods extraction returned empty"),
    ):
        audit_paper(fake_pdf)


# ─────────────────────────────────────────────────────────────────────────
# Markdown rendering
# ─────────────────────────────────────────────────────────────────────────


def test_format_report_markdown_includes_all_sections():
    report = AuditReport(
        paper="x.pdf",
        model="claude-opus-4-7",
        rag_strategy="post_hoc",
        major_concerns=[
            EnrichedConcern(
                concern=Concern(
                    headline="leakage example",
                    severity="CRITICAL",
                    body="body of concern",
                    page_cites=["p. 14 §5"],
                    suggested_gate_hint="leakage_gate",
                ),
                kb_citations=[
                    KbCitation(
                        concern_id="PR-001-C02",
                        excerpt="example excerpt",
                        score=0.78,
                        mlgg_gates=["leakage_gate"],
                    )
                ],
            )
        ],
        questions_for_authors=["Q1?"],
        methods_text_chars=42,
        methods_text_sha256="a" * 64,
    )
    md = _format_report_markdown(report)
    assert "# Audit: x.pdf" in md
    assert "## Major Concerns" in md
    assert "## Minor Concerns" in md
    assert "## Questions for Authors" in md
    assert "1. Q1?" in md
    assert "PR-001-C02" in md
    assert "leakage_gate" in md
    assert "[CRITICAL]" in md


def test_format_report_markdown_primed_mode_renders_kb_pool():
    """W31-S1: primed-mode reports should expose the KB pool shown to the
    LLM so reviewers can audit what the model was primed with."""
    report = AuditReport(
        paper="x.pdf",
        model="claude-opus-4-7",
        rag_strategy="primed",
        major_concerns=[],
        kb_context_pool=[
            KbCitation(concern_id="PR-A", excerpt="aa", score=0.7, mlgg_gates=["leakage_gate"]),
            KbCitation(concern_id="PR-B", excerpt="bb", score=0.5, mlgg_gates=[]),
        ],
        methods_text_chars=42,
        methods_text_sha256="a" * 64,
    )
    md = _format_report_markdown(report)
    assert "KB context shown to LLM" in md
    assert "PR-A" in md
    assert "PR-B" in md
    assert "rag_strategy=primed" in md
