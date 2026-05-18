"""Unit tests for W29-MVP ``scripts/review/llm_paper_audit``.

All tests run without the ``anthropic`` SDK or an API key: the LLM call
is mocked via ``unittest.mock.patch`` at the function boundary
(``call_llm_review``). The RAG enrichment is also mocked via the
``scripts.rag.query.rag_query`` import boundary.
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
    _format_report_markdown,
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


def test_user_prompt_embeds_methods_text_and_label():
    msg = _build_user_prompt(
        methods_text="<<METHODS BODY>>",
        paper_label="glm7_paper",
    )
    assert "<<METHODS BODY>>" in msg
    assert "glm7_paper" in msg
    assert "LlmAuditOutput" in msg


# ─────────────────────────────────────────────────────────────────────────
# enrich_with_rag — RAG enrichment per concern
# ─────────────────────────────────────────────────────────────────────────


def _kb_rec(cid: str, text: str, score: float, gates: list[str]) -> dict:
    return {
        "concern_id": cid,
        "concern_text": text,
        "_final_score": score,
        "mlgg_gates": gates,
    }


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
    """W28 finding: BM25 only activates when gate= is set. The shim must
    forward suggested_gate_hint to rag_query verbatim."""
    seen_gates: list = []

    def capture(query, gate=None, top_k=3, min_score=0.0, **_):
        seen_gates.append(gate)
        return []

    concerns = [
        Concern(headline="A", severity="CRITICAL", body="b", suggested_gate_hint="leakage_gate"),
        Concern(headline="B", severity="HIGH", body="b", suggested_gate_hint=None),
    ]
    with mock.patch("scripts.rag.query.rag_query", side_effect=capture):
        enrich_with_rag(concerns)
    assert seen_gates == ["leakage_gate", None]


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
# audit_paper — end-to-end, mocked
# ─────────────────────────────────────────────────────────────────────────


def test_audit_paper_end_to_end_with_mocks(tmp_path):
    """End-to-end: PDF extraction, LLM call, RAG enrichment all mocked.
    Verifies the AuditReport shape and that RAG flag actually controls
    whether citations are attached.
    """
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content (mocked extractor)")

    fake_methods = (
        "Cross-sectional NHANES analysis. GLM7 = log10(...FBG...). "
        "DM defined by HbA1c >= 6.5%. 0.7/0.3 random split."
    )
    fake_llm_out = LlmAuditOutput(
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

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value=fake_methods,
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            return_value=fake_llm_out,
        ),
        mock.patch(
            "scripts.rag.query.rag_query",
            return_value=[_kb_rec("PR-007-C01", "FBG-as-feature for HbA1c label", 0.78, ["leakage_gate"])],
        ),
    ):
        report = audit_paper(fake_pdf, use_rag_enrichment=True)

    assert isinstance(report, AuditReport)
    assert report.paper == "fake.pdf"
    assert report.rag_enriched is True
    assert len(report.major_concerns) == 1
    ec = report.major_concerns[0]
    assert ec.concern.severity == "CRITICAL"
    assert ec.kb_citations[0].concern_id == "PR-007-C01"
    assert report.methods_text_chars == len(fake_methods)
    assert len(report.methods_text_sha256) == 64
    assert report.questions_for_authors == ["Refit without FBG and report AUROC delta."]


def test_audit_paper_skips_rag_when_flag_off(tmp_path):
    """use_rag_enrichment=False must not call rag_query at all."""
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")

    with (
        mock.patch(
            "scripts.rag.evals.ncpr_extract_methods_from_pdf.extract_methods_section",
            return_value="some methods text",
        ),
        mock.patch(
            "scripts.review.llm_paper_audit.call_llm_review",
            return_value=LlmAuditOutput(
                major_concerns=[Concern(headline="x", severity="HIGH", body="y")],
            ),
        ),
        mock.patch("scripts.rag.query.rag_query") as mocked_rag,
    ):
        report = audit_paper(fake_pdf, use_rag_enrichment=False)

    mocked_rag.assert_not_called()
    assert report.rag_enriched is False
    assert report.major_concerns[0].kb_citations == []


def test_audit_paper_raises_on_missing_pdf(tmp_path):
    with pytest.raises(FileNotFoundError):
        audit_paper(tmp_path / "does_not_exist.pdf")


def test_audit_paper_raises_on_empty_methods_extraction(tmp_path):
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")
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
        model="claude-opus-4-5",
        rag_enriched=True,
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
