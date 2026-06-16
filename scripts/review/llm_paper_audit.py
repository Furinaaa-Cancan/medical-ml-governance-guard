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

from scripts.rag._enrich import default_failure_codes_for_gate

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
    """Final output shape returned by :func:`audit_paper`.

    W31-S1 changes:
    - ``rag_strategy`` replaces the binary ``rag_enriched`` flag — three
      modes now: ``"primed"`` (KB context in prompt), ``"post_hoc"`` (KB
      enrichment per concern, the W29-MVP behaviour), or ``"off"``.
    - ``kb_context_pool`` carries the KB excerpts shown to the LLM in
      priming mode. Empty in post_hoc and off modes.
    """

    paper: str
    model: str
    rag_strategy: str  # "primed" | "post_hoc" | "off"
    major_concerns: list[EnrichedConcern] = field(default_factory=list)
    minor_concerns: list[EnrichedConcern] = field(default_factory=list)
    questions_for_authors: list[str] = field(default_factory=list)
    kb_context_pool: list[KbCitation] = field(default_factory=list)
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
            "rag_strategy": self.rag_strategy,
            "methods_text_chars": self.methods_text_chars,
            "methods_text_sha256": self.methods_text_sha256,
            "major_concerns": [_ec(ec) for ec in self.major_concerns],
            "minor_concerns": [_ec(ec) for ec in self.minor_concerns],
            "questions_for_authors": self.questions_for_authors,
            "kb_context_pool": [asdict(c) for c in self.kb_context_pool],
        }


# ─────────────────────────────────────────────────────────────────────────
# Reviewer prompt — operationalized version of the W28 sub-agent prompt
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an independent strict reviewer for a medical-ML prediction-model paper at
Nature Methods / JAMA / BMJ level. Your opinion is grounded in (a) the methods
text from THE paper under review and (b) optional REFERENCE PEER-REVIEW CONCERNS
from a curated knowledge base of 817 published reviewer comments on 154 Nature
Communications / Communications Medicine papers.

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

REFERENCE PEER REVIEWS — discipline for using the KB excerpts (when provided):

R1. KB excerpts come from OTHER papers — they show shapes of concerns that real
    NC/CM reviewers raised on similar-domain studies. They are calibration,
    NOT ground truth for THIS paper.
R2. A KB concern only applies to this paper if you can independently verify
    it in the methods text below. Cite the page+section of THIS paper, then
    optionally reference the KB concern_id as a precedent (e.g.
    "p. 14 §5; precedent: PR-019-C02").
R3. NEVER raise a concern just because the KB has a similar one. The KB is
    biased — it only contains issues that real reviewers caught on
    already-published papers; absence of a KB match for an issue you observe
    in this paper is also not evidence the issue is unreal.
R4. If a KB excerpt's concern does NOT apply to this paper, silently ignore
    it. Do not list it.
R5. The 33 MLGG gates are pipeline contracts for instrumented training runs;
    do not assume this paper's authors used them. `suggested_gate_hint` is
    only for downstream taxonomy, not a claim that the gate "ran".

Severity guide:
  CRITICAL — the headline claim of the paper depends on this being wrong.
  HIGH     — substantial bias / interpretability impact.
  MEDIUM   — reporting gap or minor design issue.
  LOW      — copy-edit-level.
"""


def _format_kb_context_for_prompt(kb_pool: list["KbCitation"]) -> str:
    """W31-S1: render retrieved KB excerpts as a prompt-ready block.

    Format matches what the SYSTEM_PROMPT R1-R5 rules expect: each excerpt
    on one line with its concern_id, mlgg_gates, and a truncated body so
    the LLM can reference it by id (e.g. "precedent: PR-019-C02").
    """
    if not kb_pool:
        return ""
    lines = ["# Reference peer-review concerns (KB precedent — see SYSTEM rules R1-R5)"]
    lines.append("")
    for kb in kb_pool:
        gates = ",".join(kb.mlgg_gates) if kb.mlgg_gates else "—"
        excerpt = kb.excerpt.strip().replace("\n", " ")
        if len(excerpt) > 240:
            excerpt = excerpt[:237] + "…"
        lines.append(
            f"- [{kb.concern_id}] (score {kb.score:.2f}, gates: {gates}) {excerpt}"
        )
    lines.append("")
    return "\n".join(lines)


def _build_user_prompt(
    methods_text: str,
    paper_label: str,
    *,
    kb_context: Optional[list["KbCitation"]] = None,
) -> str:
    """Render the per-paper user message, with optional KB priming context.

    When ``kb_context`` is provided (W31-S1 priming mode), KB excerpts are
    placed BEFORE the methods text so the LLM reads them as calibration
    while forming opinions on this paper. The SYSTEM_PROMPT R1-R5 block
    disciplines how the LLM may use them (no rubber-stamping).
    """
    sections: list[str] = [f"# Paper: {paper_label}", ""]
    if kb_context:
        sections.append(_format_kb_context_for_prompt(kb_context))
    sections.extend([
        "# Methods text (extracted from PDF)",
        "",
        methods_text,
        "",
        "---",
        "",
        "Produce the structured audit. Return JSON matching the LlmAuditOutput "
        "schema: major_concerns[], minor_concerns[], questions_for_authors[].",
    ])
    return "\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────
# LLM call — Anthropic Claude (structured output)
# ─────────────────────────────────────────────────────────────────────────


def call_llm_review(
    methods_text: str,
    paper_label: str,
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 8192,
    temperature: float = 0.0,
    kb_context: Optional[list["KbCitation"]] = None,
) -> LlmAuditOutput:
    """Send the methods text to Claude and return a parsed ``LlmAuditOutput``.

    Uses ``client.messages.parse`` with a Pydantic ``output_format`` to
    avoid free-form JSON parsing. Lazy-imports ``anthropic`` so the
    module loads even when the SDK isn't installed (unit tests mock this
    function).

    Args:
        kb_context: W31-S1. When provided (priming mode), the KB excerpts
            are placed BEFORE the methods text in the user message. The
            SYSTEM_PROMPT R1-R5 block disciplines how the LLM uses them.
            When None (post_hoc or off modes), no KB section is rendered.

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
            {
                "role": "user",
                "content": _build_user_prompt(
                    methods_text, paper_label, kb_context=kb_context
                ),
            }
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
# W31-S1: RAG priming — retrieve KB context BEFORE the LLM call
# ─────────────────────────────────────────────────────────────────────────


def _retrieve_rag_context_for_priming(
    methods_text: str,
    *,
    top_k_general: int = 10,
    top_k_leakage: int = 5,
    min_score: float = 0.1,
    max_excerpt_chars: int = 200,
) -> list[KbCitation]:
    """Dual-path retrieval to assemble the KB context shown to the LLM
    in priming mode.

    Two retrieval passes are merged so the prompt sees BOTH topical
    matches and leakage-class concerns regardless of whether the methods
    text mentions leakage lexically (the W30-R1 finding: BM25 is silent
    on free-text rag_query, so leakage-class concerns are otherwise
    under-retrieved on papers that don't say the word "leakage"):

    1. General free-text rag_query on the methods text — surfaces topic
       neighbours (cohort design, evaluation metrics, etc.). 4-signal
       fusion (dense + tag + severity + corroboration), no BM25.
    2. Focused rag_query with ``gate="leakage_gate"`` plus leakage
       failure-code probes — activates BM25 on the leakage-tagged subset
       (W30-R1 logic, but ALWAYS-on here since priming asks "what concerns
       should I be aware of?", not "what concerns has the user already
       named").

    Merge: union by ``concern_id``, keep the higher ``_final_score`` per
    record. Order by score desc. Truncate by sum of top_k_general +
    top_k_leakage so the prompt size stays bounded.

    Returns an empty list if RAG is unavailable (degrades gracefully so
    priming mode falls back to LLM-only without crashing).
    """
    try:
        from scripts.rag.query import rag_query
    except ImportError:
        log.warning("RAG stack unavailable; priming will skip KB context")
        return []

    def _safe_call(**kw) -> list[dict]:
        try:
            return rag_query(query=methods_text, min_score=min_score, **kw) or []
        except Exception as exc:  # noqa: BLE001 — RAG failure must not kill audit
            log.warning("rag_query failed during priming: %s", exc)
            return []

    general = _safe_call(top_k=max(1, top_k_general))
    leakage_kwargs: dict[str, Any] = {
        "gate": "leakage_gate",
        "top_k": max(1, top_k_leakage),
    }
    leakage_failure_codes = default_failure_codes_for_gate("leakage_gate")
    if leakage_failure_codes:
        leakage_kwargs["failure_codes"] = leakage_failure_codes
    leakage = _safe_call(**leakage_kwargs)

    # Merge by concern_id; higher score wins. Records without concern_id
    # are kept individually (defensive: malformed KB rows can't drop legit hits).
    by_id: dict[str, dict] = {}
    no_id: list[dict] = []
    for rec in [*general, *leakage]:
        cid = rec.get("concern_id")
        if cid:
            existing = by_id.get(str(cid))
            if existing is None or float(rec.get("_final_score", 0.0)) > float(
                existing.get("_final_score", 0.0)
            ):
                by_id[str(cid)] = rec
        else:
            no_id.append(rec)

    merged = list(by_id.values()) + no_id
    merged.sort(key=lambda r: float(r.get("_final_score", 0.0)), reverse=True)
    cap = top_k_general + top_k_leakage
    merged = merged[:cap]

    return [
        KbCitation(
            concern_id=str(r.get("concern_id", "")),
            excerpt=str(r.get("concern_text", r.get("excerpt", "")))[:max_excerpt_chars],
            score=float(r.get("_final_score", 0.0)),
            mlgg_gates=list(r.get("mlgg_gates", []) or []),
        )
        for r in merged
    ]


# ─────────────────────────────────────────────────────────────────────────
# RAG enrichment (post-hoc) — call rag_query per concern, attach citations
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
    rag_query when present. For known gate-scoped probes such as
    ``leakage_gate``, this also supplies default ``failure_codes`` because
    ``hybrid_rank`` needs both fields before BM25 is active. Falls back to
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
            rag_kwargs: dict[str, Any] = {
                "query": query_text,
                "gate": c.suggested_gate_hint,
                "top_k": top_k,
                "min_score": min_score,
            }
            failure_codes = default_failure_codes_for_gate(c.suggested_gate_hint)
            if failure_codes:
                rag_kwargs["failure_codes"] = failure_codes
            records = rag_query(**rag_kwargs)
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


RagStrategy = Literal["primed", "post_hoc", "off"]


def audit_paper(
    pdf_path: str | Path,
    *,
    model: str = "claude-opus-4-7",
    rag_strategy: RagStrategy = "post_hoc",
    top_k: int = 3,
    min_score: float = 0.2,
    priming_top_k_general: int = 10,
    priming_top_k_leakage: int = 5,
) -> AuditReport:
    """End-to-end paper audit. PDF in, ``AuditReport`` out.

    Three RAG strategies (W31-S1 designed; W31-V2 demoted `primed`):

    - ``"post_hoc"`` (W31-V2 default after the GLM7 ablation): LLM first
      via :func:`call_llm_review` with no KB context, then per-concern
      :func:`enrich_with_rag` attaches up to ``top_k`` targeted KB
      citations using ``concern.suggested_gate_hint`` as the gate filter.
      ``kb_context_pool`` is empty in this mode. W31-V2 measured 47 %
      on-topic citation rate on GLM7 vs ``primed``'s 40 %, and zero
      priming-bias risk.
    - ``"primed"`` (W31-S1 design, demoted from default after W31-V2):
      Retrieve KB context FIRST via :func:`_retrieve_rag_context_for_priming`,
      inject it into the user prompt under "Reference peer-review concerns",
      let the single LLM call form opinions WITH the KB as calibration.
      W31-V2 found the dual-path retrieval returns 0 leakage hits on long
      methods text (W30-R1 leakage_probe is dead) and the resulting pool
      is biased toward missingness topics. Use only for explicit ablation.
    - ``"off"``: No RAG at any stage. LLM only. ``kb_context_pool`` empty,
      ``EnrichedConcern.kb_citations`` empty. W31-V2 measured CRITICAL
      recall equivalent to ``post_hoc``; ``off`` is the architectural
      baseline.

    Args:
        pdf_path: Path to the paper PDF.
        model: Anthropic model id. Default tracks the latest Opus.
        rag_strategy: See above. Default ``"post_hoc"``.
        top_k: post_hoc only — citations per concern.
        min_score: post_hoc only — floor on ``_final_score`` for cited
            records (W27-R2).
        priming_top_k_general: primed only — free-text retrieval pool size.
        priming_top_k_leakage: primed only — leakage-gate BM25 pool size.
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

    # Branch 1: priming — retrieve KB first, then LLM with KB context
    kb_context_pool: list[KbCitation] = []
    if rag_strategy == "primed":
        kb_context_pool = _retrieve_rag_context_for_priming(
            methods_text,
            top_k_general=priming_top_k_general,
            top_k_leakage=priming_top_k_leakage,
            min_score=min_score,
        )

    llm_output = call_llm_review(
        methods_text=methods_text,
        paper_label=pdf.stem,
        model=model,
        kb_context=kb_context_pool if rag_strategy == "primed" else None,
    )

    # Branch 2: post_hoc — per-concern enrichment after the LLM has spoken
    if rag_strategy == "post_hoc":
        major = enrich_with_rag(
            llm_output.major_concerns, top_k=top_k, min_score=min_score
        )
        minor = enrich_with_rag(
            llm_output.minor_concerns, top_k=top_k, min_score=min_score
        )
    else:
        # primed and off both leave per-concern citations empty.
        major = [EnrichedConcern(concern=c) for c in llm_output.major_concerns]
        minor = [EnrichedConcern(concern=c) for c in llm_output.minor_concerns]

    return AuditReport(
        paper=pdf.name,
        model=model,
        rag_strategy=rag_strategy,
        major_concerns=major,
        minor_concerns=minor,
        questions_for_authors=list(llm_output.questions_for_authors),
        kb_context_pool=kb_context_pool,
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
        f"_model={report.model}, rag_strategy={report.rag_strategy}, "
        f"kb_pool_size={len(report.kb_context_pool)}, "
        f"methods_chars={report.methods_text_chars}, "
        f"sha256={report.methods_text_sha256[:12]}…_"
    )
    lines.append("")
    if report.kb_context_pool:
        lines.append("## KB context shown to LLM (priming pool)")
        for kb in report.kb_context_pool:
            gates = ",".join(kb.mlgg_gates) if kb.mlgg_gates else "—"
            lines.append(
                f"- `{kb.concern_id}` (score {kb.score:.2f}, gates: {gates}): {kb.excerpt}"
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
        description=(
            "LLM-first paper audit with RAG strategy selection (W29-MVP + W31-S1). "
            "Default: 'post_hoc' (LLM-first audit, then per-concern targeted RAG enrichment)."
        ),
    )
    parser.add_argument("pdf", help="Path to paper PDF.")
    parser.add_argument(
        "--rag-strategy",
        choices=("primed", "post_hoc", "off"),
        default="post_hoc",
        help=(
            "RAG mode: 'post_hoc' (W31-V2 default, LLM-first then per-"
            "concern targeted RAG enrichment — best on-topic citation "
            "rate), 'primed' (W31-S1 design, KB context in prompt — "
            "demoted after W31-V2 found long-methods leakage_probe is "
            "dead and pool is missingness-biased), 'off' (LLM only)."
        ),
    )
    parser.add_argument(
        "--model", default="claude-opus-4-7",
        help="Anthropic model id (default: claude-opus-4-7).",
    )
    parser.add_argument(
        "--top-k", type=int, default=3,
        help="post_hoc mode only — citations per concern (default: 3).",
    )
    parser.add_argument(
        "--min-score", type=float, default=0.2,
        help="RAG score floor (default: 0.2, W27-R2).",
    )
    parser.add_argument(
        "--priming-top-k-general", type=int, default=10,
        help="primed mode — general retrieval pool size (default: 10).",
    )
    parser.add_argument(
        "--priming-top-k-leakage", type=int, default=5,
        help="primed mode — leakage_gate BM25 pool size (default: 5).",
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
        rag_strategy=args.rag_strategy,
        top_k=args.top_k,
        min_score=args.min_score,
        priming_top_k_general=args.priming_top_k_general,
        priming_top_k_leakage=args.priming_top_k_leakage,
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
