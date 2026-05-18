"""LLM-first paper audit with optional RAG enrichment (W29-MVP).

Implements the architecture that W28-V1's Johnson 2017 replay + the GLM7
paper experiment selected:

    PDF
     ↓ extract_methods_section()              (reused from
     ↓                                         scripts.rag.evals.ncpr_extract_methods_from_pdf)
    methods_text
     ↓ Anthropic Claude reviewer call         (Major / Minor / Questions)
     ↓ structured output via Pydantic
    concerns[]
     ↓ optional: for each concern, rag_query()  (KB peer-review citations
     ↓                                          as background, not as ground truth)
    AuditReport(major, minor, questions, kb_citations)

Why LLM-first:

    The 2026-05-17 controlled experiment on the GLM7 paper (Wang et al.,
    Advanced Science 2025) showed that ``synthesize_flags_from_rag`` —
    the pure-RAG retrieval path — caught 0 of the 3 CRITICAL methodology
    flaws (target leakage, cross-sectional-design-as-prediction,
    derivation circularity) while a strict-reviewer LLM prompt caught all
    3, plus 3 more the human pre-analysis missed. The retrieval system
    has a structural blind spot for design-flaw concepts that aren't
    lexically present in the KB. LLM-first puts the design audit where
    the LLM excels; RAG enrichment then anchors each LLM concern to real
    peer-review evidence (and back-stops the reporting checklist: CI,
    calibration, DCA, sample-size — things the LLM tends to forget).

This module is the canonical entry point for Mode B/C review per
docs/PRODUCTS.md (Mode B = external code + paper, Mode C = paper only;
this script targets Mode C — code repo not required).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("Missing dependency: pydantic. `pip install pydantic>=2.0`", file=sys.stderr)
    sys.exit(2)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Pydantic schemas — structured LLM output + final report shape
# ─────────────────────────────────────────────────────────────────────────


Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class Concern(BaseModel):
    """A single methodology concern with locator + suggested gate hint.

    ``suggested_gate_hint`` is consumed by :func:`enrich_with_rag` to
    pull peer-review citations from the KB. The LLM is asked to pick
    from the MLGG gate registry (e.g. ``leakage_gate``,
    ``calibration_dca_gate``) but is allowed to leave it null when no
    obvious gate maps.
    """

    headline: str = Field(
        ...,
        description="One-line issue statement (the flaw, not its consequence).",
    )
    severity: Severity
    body: str = Field(
        ...,
        description="2-4 sentences of specifics. Cite page numbers as 'p. N §X'.",
    )
    page_cites: list[str] = Field(
        default_factory=list,
        description="e.g. ['p. 14 §5 Definition of Data', 'p. 3 Eq. 1'].",
    )
    suggested_gate_hint: Optional[str] = Field(
        None,
        description=(
            "MLGG gate name best matching this concern, or null. Examples: "
            "leakage_gate, calibration_dca_gate, external_validation_gate, "
            "split_protocol_gate, evaluation_quality_gate, cohort_definition_gate, "
            "sample_size_gate, model_selection_audit_gate, "
            "ci_matrix_gate, reporting_bias_gate, fairness_equity_gate. "
            "Pick the most specific match or leave null."
        ),
    )


class LlmAuditOutput(BaseModel):
    """The structured shape we ask Claude to return."""

    major_concerns: list[Concern] = Field(default_factory=list)
    minor_concerns: list[Concern] = Field(default_factory=list)
    questions_for_authors: list[str] = Field(default_factory=list)


@dataclass
class KbCitation:
    """A single RAG-retrieved KB concern used to back up an LLM concern."""

    concern_id: str
    excerpt: str           # first ~200 chars of concern_text
    score: float           # _final_score from hybrid_rank
    mlgg_gates: list[str] = field(default_factory=list)


@dataclass
class EnrichedConcern:
    """An LLM ``Concern`` plus its RAG-retrieved KB backing (possibly empty)."""

    concern: Concern
    kb_citations: list[KbCitation] = field(default_factory=list)


@dataclass
class AuditReport:
    """Final output shape returned by :func:`audit_paper`."""

    paper: str
    model: str
    rag_enriched: bool
    major_concerns: list[EnrichedConcern] = field(default_factory=list)
    minor_concerns: list[EnrichedConcern] = field(default_factory=list)
    questions_for_authors: list[str] = field(default_factory=list)
    methods_text_chars: int = 0
    methods_text_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        def _ec(ec: EnrichedConcern) -> dict[str, Any]:
            return {
                "concern": ec.concern.model_dump(),
                "kb_citations": [asdict(c) for c in ec.kb_citations],
            }
        return {
            "paper": self.paper,
            "model": self.model,
            "rag_enriched": self.rag_enriched,
            "methods_text_chars": self.methods_text_chars,
            "methods_text_sha256": self.methods_text_sha256,
            "major_concerns": [_ec(ec) for ec in self.major_concerns],
            "minor_concerns": [_ec(ec) for ec in self.minor_concerns],
            "questions_for_authors": self.questions_for_authors,
        }


# ─────────────────────────────────────────────────────────────────────────
# Reviewer prompt — operationalized version of the W28 sub-agent prompt
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an independent strict reviewer for a medical-ML prediction-model paper at
Nature Methods / JAMA / BMJ level. This is a BLIND audit — form your opinion only
from the methods text below. Do not consult outside knowledge about the paper.

Output a structured list of methodology concerns. Hard rules:

1. NO praise, NO summary of what the paper does, NO verdict paragraph. Concerns only.
2. For each concern, cite the specific page+section from the methods text
   (e.g. "p. 14 §5 Definition of Data" or "p. 3 Eq. 1").
3. If you find a LEAKAGE-class issue (definition variable in predictor, target
   leakage, temporal leakage, treatment-effect-in-predictor), call it out
   using the literal word "leakage" so it is grep-able.
4. If you find a DERIVATION CIRCULARITY issue (predictor formula chosen by
   inspecting the same outcome data later used for evaluation), call it out
   using the literal phrase "derivation circularity".
5. If you find a TEMPORAL VALIDITY issue (cross-sectional design framed as
   "prediction", prevalent vs incident outcomes), call it out using the
   literal phrase "temporal validity".
6. Pick a `suggested_gate_hint` from this list when it fits naturally,
   otherwise leave null:
   leakage_gate, calibration_dca_gate, external_validation_gate,
   split_protocol_gate, evaluation_quality_gate, cohort_definition_gate,
   sample_size_gate, model_selection_audit_gate, ci_matrix_gate,
   reporting_bias_gate, fairness_equity_gate.
7. Headline is the FLAW, not its consequence ("predictor contains FBG while
   DM is defined by HbA1c" — not "AUROC of 0.966 is suspicious").
8. Don't pad. 3-12 Major is normal. Quality > quantity.

Severity guide:
  CRITICAL — the headline claim of the paper depends on this being wrong.
  HIGH     — substantial bias / interpretability impact.
  MEDIUM   — reporting gap or minor design issue.
  LOW      — copy-edit-level.
"""


def _build_user_prompt(methods_text: str, paper_label: str) -> str:
    """Render the per-paper user message."""
    return (
        f"# Paper: {paper_label}\n\n"
        f"# Methods text (extracted from PDF)\n\n"
        f"{methods_text}\n\n"
        f"---\n\n"
        f"Produce the structured audit. Return JSON matching the LlmAuditOutput "
        f"schema: major_concerns[], minor_concerns[], questions_for_authors[]."
    )


# ─────────────────────────────────────────────────────────────────────────
# LLM call — Anthropic Claude (structured output)
# ─────────────────────────────────────────────────────────────────────────


def call_llm_review(
    methods_text: str,
    paper_label: str,
    *,
    model: str = "claude-opus-4-5",
    max_tokens: int = 8192,
    temperature: float = 0.0,
) -> LlmAuditOutput:
    """Send the methods text to Claude and return a parsed ``LlmAuditOutput``.

    Uses ``client.messages.parse`` with a Pydantic ``output_format`` to
    avoid free-form JSON parsing. Lazy-imports ``anthropic`` so the
    module loads even when the SDK isn't installed (unit tests mock this
    function).

    Raises:
        RuntimeError if ANTHROPIC_API_KEY is missing or the SDK is absent.
    """
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without SDK
        raise RuntimeError(
            "anthropic SDK not installed. Run `pip install anthropic>=0.40.0` "
            "or use the [llm] extra: `pip install -e .[llm]`."
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY env var not set. Acquire from console.anthropic.com "
            "and `export ANTHROPIC_API_KEY=sk-ant-...` before running."
        )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": _build_user_prompt(methods_text, paper_label)}
        ],
        output_format=LlmAuditOutput,
    )
    parsed = response.parsed_output
    if not isinstance(parsed, LlmAuditOutput):
        raise RuntimeError(
            f"Anthropic returned unparsed output (type={type(parsed).__name__}). "
            f"Raw content: {response.content[:200]!r}"
        )
    return parsed


# ─────────────────────────────────────────────────────────────────────────
# RAG enrichment — call rag_query per concern, attach citations
# ─────────────────────────────────────────────────────────────────────────


def enrich_with_rag(
    concerns: list[Concern],
    *,
    top_k: int = 3,
    min_score: float = 0.2,
) -> list[EnrichedConcern]:
    """For each concern, call :func:`scripts.rag.query.rag_query` and
    attach up to ``top_k`` KB citations whose ``_final_score >= min_score``.

    Uses ``concern.suggested_gate_hint`` as the ``gate=`` argument to
    rag_query when present — this is what activates BM25 in the hybrid
    ranker (see SKILL.md §Hybrid retrieval caveat). Falls back to
    free-text retrieval when the hint is null.

    Returns a list of ``EnrichedConcern`` in input order. Citations may be
    empty when the KB has no semantically-close match.
    """
    try:
        from scripts.rag.query import rag_query
    except ImportError:
        # RAG stack not available — return concerns without citations.
        return [EnrichedConcern(concern=c) for c in concerns]

    enriched: list[EnrichedConcern] = []
    for c in concerns:
        query_text = f"{c.headline}. {c.body}"
        try:
            records = rag_query(
                query=query_text,
                gate=c.suggested_gate_hint,
                top_k=top_k,
                min_score=min_score,
            )
        except Exception as exc:  # noqa: BLE001 — RAG failure shouldn't kill the audit
            log.warning("rag_query failed for concern %r: %s", c.headline[:60], exc)
            records = []
        citations = [
            KbCitation(
                concern_id=str(r.get("concern_id", "")),
                excerpt=str(r.get("concern_text", r.get("excerpt", "")))[:200],
                score=float(r.get("_final_score", 0.0)),
                mlgg_gates=list(r.get("mlgg_gates", []) or []),
            )
            for r in records
        ]
        enriched.append(EnrichedConcern(concern=c, kb_citations=citations))
    return enriched


# ─────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────


def audit_paper(
    pdf_path: str | Path,
    *,
    model: str = "claude-opus-4-5",
    use_rag_enrichment: bool = True,
    top_k: int = 3,
    min_score: float = 0.2,
) -> AuditReport:
    """End-to-end paper audit. PDF in, ``AuditReport`` out.

    Args:
        pdf_path: Path to the paper PDF.
        model: Anthropic model id. Default tracks the latest Opus.
        use_rag_enrichment: When True (default), each LLM concern is
            enriched with up to ``top_k`` KB peer-review citations via
            :func:`scripts.rag.query.rag_query`.
        top_k: Citations per concern.
        min_score: Floor on ``_final_score`` for cited KB records.
            Anything below is dropped (W27-R2).
    """
    from hashlib import sha256

    from scripts.rag.evals.ncpr_extract_methods_from_pdf import (
        extract_methods_section,
    )

    pdf = Path(pdf_path).expanduser().resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    methods_text = extract_methods_section(pdf)
    if not methods_text.strip():
        raise RuntimeError(
            f"Methods extraction returned empty text for {pdf}. "
            "Check pdftotext is installed and the PDF is not image-only."
        )

    llm_output = call_llm_review(
        methods_text=methods_text,
        paper_label=pdf.stem,
        model=model,
    )

    if use_rag_enrichment:
        major = enrich_with_rag(
            llm_output.major_concerns, top_k=top_k, min_score=min_score
        )
        minor = enrich_with_rag(
            llm_output.minor_concerns, top_k=top_k, min_score=min_score
        )
    else:
        major = [EnrichedConcern(concern=c) for c in llm_output.major_concerns]
        minor = [EnrichedConcern(concern=c) for c in llm_output.minor_concerns]

    return AuditReport(
        paper=pdf.name,
        model=model,
        rag_enriched=use_rag_enrichment,
        major_concerns=major,
        minor_concerns=minor,
        questions_for_authors=list(llm_output.questions_for_authors),
        methods_text_chars=len(methods_text),
        methods_text_sha256=sha256(methods_text.encode("utf-8")).hexdigest(),
    )


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────


def _format_report_markdown(report: AuditReport) -> str:
    """Render an AuditReport as human-readable markdown."""
    lines: list[str] = []
    lines.append(f"# Audit: {report.paper}")
    lines.append("")
    lines.append(
        f"_model={report.model}, rag_enriched={report.rag_enriched}, "
        f"methods_chars={report.methods_text_chars}, "
        f"sha256={report.methods_text_sha256[:12]}…_"
    )
    lines.append("")
    for tier, items in (
        ("Major Concerns", report.major_concerns),
        ("Minor Concerns", report.minor_concerns),
    ):
        lines.append(f"## {tier}")
        if not items:
            lines.append("_(none)_")
            lines.append("")
            continue
        for i, ec in enumerate(items, 1):
            c = ec.concern
            cites = "; ".join(c.page_cites) or "(no page cite)"
            gate = f"`{c.suggested_gate_hint}`" if c.suggested_gate_hint else "_none_"
            lines.append(f"### {i}. [{c.severity}] {c.headline}")
            lines.append("")
            lines.append(c.body)
            lines.append("")
            lines.append(f"- **Pages**: {cites}")
            lines.append(f"- **Suggested gate**: {gate}")
            if ec.kb_citations:
                lines.append("- **KB peer-review citations**:")
                for kb in ec.kb_citations:
                    lines.append(
                        f"  - `{kb.concern_id}` (score {kb.score:.2f}): {kb.excerpt}"
                    )
            lines.append("")
        lines.append("")
    lines.append("## Questions for Authors")
    if not report.questions_for_authors:
        lines.append("_(none)_")
    else:
        for i, q in enumerate(report.questions_for_authors, 1):
            lines.append(f"{i}. {q}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM-first paper audit with optional RAG enrichment (W29-MVP).",
    )
    parser.add_argument("pdf", help="Path to paper PDF.")
    parser.add_argument(
        "--no-rag", action="store_true",
        help="Skip RAG enrichment (LLM-only — fastest, no KB lookups).",
    )
    parser.add_argument(
        "--model", default="claude-opus-4-5",
        help="Anthropic model id (default: claude-opus-4-5).",
    )
    parser.add_argument(
        "--top-k", type=int, default=3,
        help="KB citations per concern (default: 3).",
    )
    parser.add_argument(
        "--min-score", type=float, default=0.2,
        help="RAG score floor (default: 0.2, W27-R2).",
    )
    parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--out", default="-",
        help="Output file path, or '-' for stdout (default).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    report = audit_paper(
        pdf_path=args.pdf,
        model=args.model,
        use_rag_enrichment=not args.no_rag,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    payload = (
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        if args.format == "json"
        else _format_report_markdown(report)
    )

    if args.out == "-":
        print(payload)
    else:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
