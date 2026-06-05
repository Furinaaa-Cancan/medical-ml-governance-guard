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
from pathlib import Path
from typing import Any, Dict, List, Optional


def gather_evidence(evidence_dir: Path) -> Dict[str, Any]:
    """Collect gate reports from ``evidence_dir`` into a synthesis context."""
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
        raise NotImplementedError(
            "Live Claude synthesis wiring is intentionally deferred to a user-enabled step "
            "(P1.0b): construct the prompt from `context`, call the API with self._model, and "
            "return {'concerns': [...], 'meta': {...}}."
        )


def run_llm_review(
    evidence_dir: Path,
    adapter: Optional[ReviewAdapter] = None,
    out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Gather evidence, synthesize concerns, write the P0.0-schema review report."""
    adapter = adapter or DeterministicReviewAdapter()
    context = gather_evidence(Path(evidence_dir))
    result = adapter.synthesize(context)
    report: Dict[str, Any] = {
        "concerns": result.get("concerns", []),
        "meta": result.get("meta", {}),
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
    args = parser.parse_args(argv)
    report = run_llm_review(Path(args.evidence_dir), out_path=Path(args.out) if args.out else None)
    print(
        f"[llm-review] wrote {len(report.get('concerns', []))} concern(s) "
        f"via adapter='{report.get('meta', {}).get('model')}' "
        f"(evidence_seen={report.get('meta', {}).get('evidence_seen')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
