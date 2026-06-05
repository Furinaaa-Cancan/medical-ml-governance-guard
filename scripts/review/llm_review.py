"""LLM review synthesis producer (asymmetric two-tier harness, P1.0).

Gathers all gate evidence (+ optionally RAG concerns), hands it to a pluggable
synthesis adapter, and writes ``evidence/llm_review_report.json`` in the schema
the publication_gate asymmetric channel consumes (P0.0). The advisory layer can
only RAISE concerns; it can never clear a gate failure — that asymmetry is
enforced downstream by publication_gate, not here.

Adapters:
  * ``DeterministicReviewAdapter`` (default) — rule-based, NO network. Echoes
    gate warnings as advisory concerns. Runs unattended and is fully testable.
  * ``LiveClaudeReviewAdapter`` — real Claude synthesis. NOT used by default and
    guarded so it cannot make an accidental paid/external call in an unattended
    run; wiring the live call is a deliberate, user-enabled step (P1.0b).

Run: ``python3 scripts/review/llm_review.py --evidence-dir evidence/``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Put the repo root on sys.path so the lazy ``from scripts.rag.query import
# rag_query`` in ``main`` resolves when this file is invoked directly
# (``python3 scripts/review/llm_review.py``) or dispatched via ``mlgg``. Cheap:
# importing the function never pulls the dense stack (rag_query defers torch).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _format_rag_concern(record: Dict[str, Any]) -> str:
    """Render one retrieved KB concern record into a single prompt line."""
    severity = str(record.get("severity") or "").strip().upper()
    category = str(record.get("category") or "").strip()
    text = str(
        record.get("evidence_text")
        or record.get("concern_text")
        or record.get("message")
        or ""
    ).strip()
    cid = str(record.get("concern_id") or record.get("id") or "").strip()
    head = " ".join(
        p for p in (f"[{severity}]" if severity else "", f"({category})" if category else "") if p
    )
    line = (f"{head} {text}" if head else text).strip() or "(no concern text)"
    return f"{line} — KB:{cid}" if cid else line


def gather_rag_concerns(
    gates: List[Dict[str, Any]],
    retriever: Optional[Any],
    max_per_gate: int = 3,
    max_total: int = 12,
) -> List[str]:
    """The ②→④ wire: retrieve real peer-review precedent for each FAILING gate.

    ``retriever`` is any callable with the :func:`scripts.rag.query.rag_query`
    signature ``(query, gate, failure_codes, top_k) -> list[dict]``. For every
    gate that failed, its codes + failure messages form the query; the returned
    KB concern records are formatted into deduped, bounded human-readable strings
    for the live reviewer's context. Returns ``[]`` when ``retriever`` is ``None``
    or yields nothing. Never raises: a retriever error degrades that gate to no
    concerns — the advisory layer must not crash a review run.
    """
    if retriever is None:
        return []
    out: List[str] = []
    seen: set = set()
    for gate in gates:
        failures = gate.get("failures") or []
        if str(gate.get("status")).lower() != "fail" and not failures:
            continue
        gate_name = gate.get("gate")
        codes = [str(f.get("code")) for f in failures if isinstance(f, dict) and f.get("code")]
        messages = [
            str(f.get("message")) for f in failures if isinstance(f, dict) and f.get("message")
        ]
        query = ": ".join(
            p for p in [str(gate_name or "").strip(), " ; ".join(messages)] if p
        ) or str(gate_name or "gate failure")
        try:
            records = retriever(
                query=query, gate=gate_name, failure_codes=codes or None, top_k=max_per_gate
            )
        except Exception:
            continue  # advisory layer is best-effort; never crash the review
        for record in list(records or [])[:max_per_gate]:
            if not isinstance(record, dict):
                continue
            line = _format_rag_concern(record)
            dedup_key = str(record.get("concern_id") or record.get("id") or "") or line
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append(line)
            if len(out) >= max_total:
                return out
    return out


def gather_evidence(evidence_dir: Path, retriever: Optional[Any] = None) -> Dict[str, Any]:
    """Collect gate reports from ``evidence_dir`` into a synthesis context.

    When ``retriever`` is provided (the ②→④ wire: typically
    :func:`scripts.rag.query.rag_query`), each failing gate's codes + messages
    pull real peer-review precedent from the KB into ``rag_concerns``, which the
    live reviewer renders into its prompt. Default ``None`` keeps this path
    retrieval-free — deterministic and with no dense-stack import.
    """
    gates: List[Dict[str, Any]] = []
    run_ids = set()
    for path in sorted(Path(evidence_dir).glob("*_report.json")):
        if path.name == "llm_review_report.json":
            continue  # never feed our own prior output back in
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(report, dict):
            continue
        rid = report.get("run_id")
        if isinstance(rid, str) and rid.strip():
            run_ids.add(rid.strip())
        gates.append({
            "gate": report.get("gate_name") or path.stem,
            "status": report.get("status"),
            "failure_count": report.get("failure_count"),
            "warning_count": report.get("warning_count"),
            "failures": report.get("failures") or [],
            "warnings": report.get("warnings") or [],
            "summary": report.get("summary") or {},
        })
    return {
        "evidence_dir": str(evidence_dir),
        "gates": gates,
        "gate_count": len(gates),
        "run_id": sorted(run_ids)[0] if len(run_ids) == 1 else None,
        "rag_concerns": gather_rag_concerns(gates, retriever),
    }


class ReviewAdapter:
    """Base adapter: ``synthesize(context) -> {concerns: [...], meta: {...}}``."""

    name = "base"

    def synthesize(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class DeterministicReviewAdapter(ReviewAdapter):
    """Default, no-network, deterministic adapter.

    If ``concerns`` is provided it is returned verbatim (test control). Otherwise
    it derives ADVISORY concerns by echoing each gate warning — a safe,
    deterministic stand-in for the real reviewer that never invents blocking
    findings (only the live reviewer can raise a blocking semantic concern).
    """

    name = "deterministic-double"

    def __init__(self, concerns: Optional[List[Dict[str, Any]]] = None):
        self._concerns = concerns

    def synthesize(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self._concerns is not None:
            concerns = list(self._concerns)
        else:
            concerns = []
            for g in context.get("gates", []):
                for w in g.get("warnings", []):
                    concerns.append({
                        "severity": "advisory",
                        "code": "echo_" + str(w.get("code") or "warning"),
                        "message": str(w.get("message") or "Gate warning echoed by deterministic reviewer."),
                        "detail": {"gate": g.get("gate")},
                    })
        prompt_hash = hashlib.sha256(
            json.dumps(context.get("gates", []), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return {
            "concerns": concerns,
            "meta": {
                "model": self.name,
                "prompt_hash": prompt_hash,
                "evidence_seen": context.get("gate_count", 0),
            },
        }


_REVIEWER_SYSTEM = (
    "You are a Nature Methods / JAMA-grade methodology reviewer for retrospective-cohort "
    "binary-classification medical ML. You are given the deterministic gate evidence (failures, "
    "warnings, and summaries) plus any retrieved peer-review concerns. Surface methodology concerns "
    "the gates cannot see — feature-timing / post-index (F02) leakage, definition-variable leakage, "
    "variable aliasing, calibration / decision-curve gaps, fairness. You may ONLY raise concerns; you "
    "never clear or override a gate's verdict. Mark a concern 'blocking' only for a genuine "
    "methodology defect that should block publication-grade; otherwise 'advisory'. Be specific and "
    "cite the gate/feature. Report exclusively via the report_concerns tool."
)

# Forced structured output: the model must return concerns in the P0.0 schema that
# publication_gate's asymmetric channel consumes.
_REPORT_CONCERNS_TOOL = {
    "name": "report_concerns",
    "description": (
        "Report methodology review concerns about the ML evidence. Each concern can only RAISE a "
        "doubt — it is consumed as a failure/warning by the gate and can never clear a gate failure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concerns": {
                "type": "array",
                "description": "Methodology concerns; empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["blocking", "advisory"]},
                        "code": {"type": "string", "description": "short stable code, e.g. f02_post_index_feature"},
                        "message": {"type": "string", "description": "human-readable concern"},
                        "detail": {"type": "object", "description": "optional structured context (feature, gate, ...)"},
                    },
                    "required": ["severity", "code", "message"],
                },
            },
        },
        "required": ["concerns"],
    },
}


def _build_review_prompt(context: Dict[str, Any]) -> str:
    """Render gathered gate evidence (+ optional RAG concerns) into the user prompt."""
    lines = ["# Deterministic gate evidence", ""]
    for g in context.get("gates", []):
        lines.append(
            f"## {g.get('gate')} — status={g.get('status')} "
            f"(failures={g.get('failure_count')}, warnings={g.get('warning_count')})"
        )
        for f in g.get("failures", []) or []:
            lines.append(f"- FAIL [{f.get('code')}]: {f.get('message')}")
        for w in g.get("warnings", []) or []:
            lines.append(f"- WARN [{w.get('code')}]: {w.get('message')}")
        lines.append("")
    rag = context.get("rag_concerns")
    if rag:
        lines.append("# Retrieved peer-review concerns")
        lines += [f"- {c}" for c in rag]
        lines.append("")
    lines.append(
        "Review the evidence above. Report methodology concerns via the report_concerns tool — "
        "raise concerns only; do not attempt to clear any gate failure."
    )
    return "\n".join(lines)


def _extract_tool_concerns(response: Any) -> List[Dict[str, Any]]:
    """Pull the report_concerns tool_use input out of a messages.create response (duck-typed)."""
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_concerns":
            data = getattr(block, "input", None)
            concerns = data.get("concerns") if isinstance(data, dict) else None
            return [c for c in concerns if isinstance(c, dict)] if isinstance(concerns, list) else []
    return []


class LiveClaudeReviewAdapter(ReviewAdapter):
    """Real Claude synthesis — NOT used unattended.

    Requires an explicit configured ``client`` AND ``enabled=True``. Without
    both, ``synthesize`` raises, so no accidental paid/external call can occur in
    tests or in the unattended loop. Prompt construction + the actual API call
    are a deliberate, user-enabled step (model / cost / prompt are the operator's
    decision) — see docs/asymmetric-two-tier-GOAL.md P1.0b.
    """

    name = "live-claude"

    def __init__(self, client: Any = None, model: str = "claude-opus-4-8", enabled: bool = False):
        self._client = client
        self._model = model
        self._enabled = enabled

    def synthesize(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled or self._client is None:
            raise RuntimeError(
                "LiveClaudeReviewAdapter is disabled. Real Claude synthesis requires an "
                "explicit configured client AND enabled=True. This guard prevents accidental "
                "paid/external calls in unattended runs."
            )
        prompt = _build_review_prompt(context)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        # Forced tool_choice guarantees structured concerns in the P0.0 schema. The static
        # system prompt is cache-marked (stable across runs); the per-run evidence is the
        # volatile user turn. Client is duck-typed (anything with .messages.create) — no hard
        # anthropic dependency; tests inject a mock so no real/paid call happens.
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=[{"type": "text", "text": _REVIEWER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[_REPORT_CONCERNS_TOOL],
            tool_choice={"type": "tool", "name": "report_concerns"},
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "concerns": _extract_tool_concerns(response),
            "meta": {
                "model": self._model,
                "prompt_hash": prompt_hash,
                "evidence_seen": context.get("gate_count", 0),
            },
        }


def run_llm_review(
    evidence_dir: Path,
    adapter: Optional[ReviewAdapter] = None,
    out_path: Optional[Path] = None,
    retriever: Optional[Any] = None,
) -> Dict[str, Any]:
    """Gather evidence (+ optional RAG concerns), synthesize, write the P0.0 report.

    ``retriever`` (the ②→④ wire) is forwarded to :func:`gather_evidence`; when
    set, retrieved peer-review precedent is fed to the reviewer and its count is
    recorded in the report for the audit trail.
    """
    adapter = adapter or DeterministicReviewAdapter()
    context = gather_evidence(Path(evidence_dir), retriever=retriever)
    result = adapter.synthesize(context)
    report: Dict[str, Any] = {
        "concerns": result.get("concerns", []),
        "meta": result.get("meta", {}),
        "rag_evidence_count": len(context.get("rag_concerns") or []),
    }
    rid = context.get("run_id") or os.environ.get("MLGG_RUN_ID")
    if rid:
        report["run_id"] = rid
    out = Path(out_path) if out_path else Path(evidence_dir) / "llm_review_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LLM review synthesis producer (asymmetric two-tier).")
    parser.add_argument("--evidence-dir", required=True, help="Directory of gate *_report.json files.")
    parser.add_argument("--out", default=None, help="Output path (default: <evidence-dir>/llm_review_report.json).")
    parser.add_argument(
        "--live", action="store_true",
        help="Use the LIVE Claude adapter (real, paid API call; needs ANTHROPIC_API_KEY). "
             "Default is the deterministic, no-network double.",
    )
    parser.add_argument("--model", default="claude-opus-4-8", help="Model for --live (default: claude-opus-4-8).")
    parser.add_argument(
        "--rag", action="store_true",
        help="Retrieve real peer-review concerns from the KB for each failing gate and "
             "attach them to the reviewer's context (the evidence->LLM wire). Implied by "
             "--live; usable alone to preview what precedent would be surfaced.",
    )
    args = parser.parse_args(argv)

    adapter = None
    if args.live:
        # Lazy import so the default path keeps zero hard dependency on the SDK.
        import anthropic  # noqa: PLC0415

        adapter = LiveClaudeReviewAdapter(client=anthropic.Anthropic(), model=args.model, enabled=True)

    retriever = None
    if args.rag or args.live:
        # Lazy import: rag_query itself defers the dense/torch stack, so this is
        # cheap and degrades to [] when the RAG stack or KB is unavailable.
        from scripts.rag.query import rag_query  # noqa: PLC0415

        retriever = rag_query

    report = run_llm_review(
        Path(args.evidence_dir),
        adapter=adapter,
        out_path=Path(args.out) if args.out else None,
        retriever=retriever,
    )
    print(
        f"[llm-review] wrote {len(report.get('concerns', []))} concern(s) "
        f"via adapter='{report.get('meta', {}).get('model')}' "
        f"(evidence_seen={report.get('meta', {}).get('evidence_seen')}, "
        f"rag_evidence={report.get('rag_evidence_count', 0)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
