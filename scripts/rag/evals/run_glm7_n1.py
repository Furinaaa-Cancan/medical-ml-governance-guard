#!/usr/bin/env python3
"""Integration-benchmark N=1 runner — GLM7 (PMC12622479, Adv Sci 2025).

The first cross-layer integration record (NCPR-Bench v2, Tier B+ per
``docs/integration-benchmark-PLAN.md``). It re-executes the two
*script-reproducible* layers on a real paper's declared features and reports
them, plus the frozen LLM layer, against an isolated ground-truth answer key.

Layers:
  - **Deterministic** — ``definition_variable_guard`` on the declared feature
    manifest vs a disease-KB-derived phenotype spec. Genuinely measured +
    reproducible; it BINDS the verdict (a gate FAIL cannot be cleared).
  - **RAG** — ``retrieve_for_failure`` on the failure classes (shipping BM25
    gate path), LOPO-excluded (a no-op here: GLM7 is not in the KB).
  - **LLM** — a FROZEN independent-reviewer capture; NOT regenerated.

HONEST METRIC SEMANTICS (see ground_truth.json `_provenance_caveats`):
  - deterministic coverage/column-recall are MEASURED against the gate output.
  - the RAG number is **retrieval self-consistency**, not blind recall: the GT's
    ``rag_concern_ids`` were observed from a retrieval run, so it answers "does
    the shipping path surface an on-topic KB concern for each failure class",
    counting *distinct* retrieved concerns to avoid double-credit.
  - the LLM number is **self-attested** via the frozen file's own ``addresses_gt``
    tags (same author wrote both); it is not independently adjudicated and the
    reviewer is non-reproducible.
  - two verdicts are reported: ``reproducible`` (deterministic+RAG only) and
    ``frozen_augmented`` (folds in the frozen LLM).

This runner is data-driven from ground_truth.json (failure classes, deterministic
targets, definition columns), so it has no per-paper literals; a second case is a
new GT/inputs folder. (Auto-deriving failure classes from a live gate run, and a
blind LLM-to-GT adjudicator, are the general-harness next phase — plan P1/P2.)

Usage::

    python3 scripts/rag/evals/run_glm7_n1.py            # check vs frozen record.json (exit 2 on drift)
    python3 scripts/rag/evals/run_glm7_n1.py --write     # regenerate record.json
    python3 scripts/rag/evals/run_glm7_n1.py --json       # print the computed record
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORD_DIR = REPO_ROOT / "references" / "benchmark" / "integration" / "glm7_n1"
INPUTS = RECORD_DIR / "inputs"
GUARD = REPO_ROOT / "scripts" / "gates" / "definition_variable_guard.py"

# GLM7 is NOT in the peer-review KB, so this LOPO exclusion is a declared no-op;
# kept so the call shape is honest for cases that ARE in the KB.
GLM7_KB_ID = "glm7-n1-not-in-kb"


def _load(name: str) -> Dict[str, Any]:
    return json.loads((RECORD_DIR / name).read_text(encoding="utf-8"))


def _run_guard(target: str) -> Dict[str, Any]:
    """Run definition_variable_guard for one target; return status + hits."""
    out = INPUTS / f"_guard_{target}.report.json"
    cmd = [
        sys.executable, str(GUARD),
        "--target", target,
        "--definition-spec", str(INPUTS / "phenotype_spec.json"),
        "--train", str(INPUTS / "features.csv"),
        "--target-col", "GLM7",
        "--cross-sectional",
        "--report", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
    report = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    hits: List[Dict[str, str]] = []
    codes: List[str] = []
    for f in report.get("failures", []):
        if f.get("code"):
            codes.append(f["code"])
        if f.get("code") == "definition_variable_leakage":
            hits = f.get("details", {}).get("hits", [])
    return {"target": target, "status": report.get("status"), "exit_code": proc.returncode,
            "hits": hits, "emitted_codes": sorted(set(codes))}


def _run_rag(
    failure_classes: List[Dict[str, Any]],
    gate_emitted_codes: Dict[str, List[str]],
    excluded_paper_ids: List[str] | None = None,
) -> Dict[str, Any]:
    """Drive the shipping BM25 retrieval path for each failure class (LOPO-excluded).

    Failure-class provenance: a ``source == "gate_run"`` class whose gate actually
    ran on this paper DERIVES its codes from the live gate output (not the
    hand-authored list); ``analysis`` classes have no runnable gate on a paper, so
    their codes are analyst-asserted from the text. Both are recorded. The
    ``excluded_paper_ids`` argument is threaded into BM25 so the declared LOPO
    provenance and the actual retrieval call shape cannot drift.
    """
    if excluded_paper_ids is None:
        excluded_paper_ids = [GLM7_KB_ID]

    sys.path.insert(0, str(REPO_ROOT))
    from scripts.rag.retrieval.bm25 import retrieve_for_failure

    retrievals: Dict[str, List[str]] = {}
    provenance: Dict[str, Dict[str, Any]] = {}
    for fc in failure_classes:
        if fc.get("source") == "gate_run" and gate_emitted_codes.get(fc["gate"]):
            codes = gate_emitted_codes[fc["gate"]]
            source = "gate_run"
        else:
            codes = fc["codes"]
            source = fc.get("source", "analysis")
        provenance[fc["label"]] = {"source": source, "codes_used": codes, "gate": fc["gate"]}
        try:
            res = retrieve_for_failure(
                fc["gate"],
                codes,
                limit=4,
                excluded_paper_ids=excluded_paper_ids,
            )
        except Exception as exc:  # pragma: no cover - retrieval availability
            retrievals[fc["label"]] = [f"<error: {exc}>"]
            continue
        ids = [r.get("concern_id") or r.get("id") or r.get("citation_id") for r in res]
        retrievals[fc["label"]] = [c for c in ids if c]
    return {"retrievals": retrievals, "provenance": provenance}


def _verdict_min(*verdicts: str) -> str:
    order = {"fail": 0, "concern": 1, "pass": 2}
    return min(verdicts, key=lambda v: order.get(v, 2))


def compute_record() -> Dict[str, Any]:
    paper = _load("inputs/paper.json")
    spec = _load("inputs/phenotype_spec.json")
    llm = _load("llm_review.frozen.json")
    gt = _load("ground_truth.json")  # validity control C5: loaded with inputs but used only after flags
    concerns = gt["concerns"]
    try:
        adj = _load("adjudication.frozen.json")  # blind-to-labels adjudication (frozen, non-reproducible)
    except FileNotFoundError:
        adj = None

    # --- Layer 1: deterministic (real gate), driven by GT deterministic_target ---
    targets = sorted({c["deterministic_target"] for c in concerns if c.get("deterministic_target")})
    guard_runs = [_run_guard(t) for t in targets]
    targets_failed = {g["target"] for g in guard_runs if g["status"] == "fail"}
    det_verdict = "fail" if targets_failed else "pass"

    # Column-level recall: expected columns come from GT data, not a code literal.
    expected_cols, seen = [], set()
    for c in concerns:
        for col in c.get("definition_columns", []):
            if col not in seen:
                seen.add(col); expected_cols.append(col)
    det_caught_cols = sorted({h["feature"] for g in guard_runs for h in g["hits"]})
    det_missed_cols = [c for c in expected_cols if c not in det_caught_cols]

    # --- Layer 2: RAG (real retrieval). Honest framing: SELF-CONSISTENCY, not recall. ---
    # The one gate that runs on a paper (definition_variable_guard) feeds its EMITTED
    # codes into the matching failure class (gate-derived, not hand-authored).
    gate_emitted = {"definition_variable_guard": sorted({c for g in guard_runs for c in g.get("emitted_codes", [])})}
    rag_out = _run_rag(
        gt["rag_failure_classes"],
        gate_emitted,
        excluded_paper_ids=[GLM7_KB_ID],
    )
    retrievals = rag_out["retrievals"]
    rag_provenance = rag_out["provenance"]
    retrieved_ids = {cid for ids in retrievals.values() for cid in ids}
    rag_verdict = "concern"  # advisory layer: a fixed, structural cap (cannot clear a floor, cannot raise one)

    # --- Attribution: which layer caught each GT, scored vs the pre-registration ---
    llm_self_attested = {c.get("addresses_gt") for c in llm.get("concerns", [])}
    attribution = []
    rag_credited_concern_ids = set()  # distinct retrieved concerns that earned a GT credit
    for c in concerns:
        caught = []
        if c.get("deterministic_target") in targets_failed:
            caught.append("deterministic")
        hit_ids = [cid for cid in c.get("rag_concern_ids", []) if cid in retrieved_ids]
        if hit_ids:
            caught.append("rag")
            rag_credited_concern_ids.update(hit_ids)
        if c["id"] in llm_self_attested:
            caught.append("llm")
        off_prediction = [layer for layer in caught if layer not in c["expected_layers"]]
        attribution.append({
            "gt_id": c["id"], "severity": c["severity"], "rule": c["rule"],
            "headline": c["headline"], "expected_layers": c["expected_layers"],
            "caught_by": caught, "uncaught": not caught,
            "off_prediction_layers": off_prediction,
        })

    n = len(concerns)
    def _cov(layer: str) -> int:
        return sum(1 for a in attribution if layer in a["caught_by"])

    # Verdicts: reproducible (det+rag) vs frozen-augmented (folds in the frozen LLM).
    llm_verdict = "fail" if llm.get("verdict") == "not_publication_grade" else "concern"
    reproducible_verdict = _verdict_min(det_verdict, rag_verdict)
    frozen_augmented_verdict = _verdict_min(reproducible_verdict, llm_verdict)

    # --- Blind-to-labels adjudication (frozen, non-reproducible) ---
    # Upgrades the two soft numbers: the LLM panel re-derived coverage WITHOUT
    # seeing addresses_gt (catches self-attestation inflation); RAG relevance was
    # judged blind to retrieval rank (turns "self-consistency" into real precision).
    adjudication = None
    if adj:
        la = adj["llm_blind_adjudication"]
        ra = adj["rag_independent_relevance"]
        adjudication = {
            "method": adj.get("method"),
            "reproducible": False,
            "llm": {
                "blind_adjudicated_coverage": la["blind_gts_covered"],
                "blind_matches_self_declared": la["blind_matches_self_declared"],
                "self_attestation_validated": la["blind_matches_self_declared"] == f"{n}/{n}",
            },
            "rag": {
                "independent_precision": ra["overall_precision"],
                "per_class": {k: f"{v['on_topic']}/{v['of']}" for k, v in ra["per_class"].items()},
            },
            "note": "Blind-to-labels (panel never saw addresses_gt; relevance judged blind to retrieval "
                    "rank), same model family -- catches self-attestation inflation, not shared-model bias.",
        }

    followups = []
    if det_missed_cols:
        followups.append({
            "type": "disease_kb_synonym_gap",
            "detail": f"definition_variable_guard missed {det_missed_cols} because the disease-KB "
                      f"definition_variables_to_exclude lists canonical names but not these abbreviations "
                      f"('fbg' for fasting_plasma_glucose, 'cr' for creatinine).",
            "proposed_fix": "Add 'fbg' to type_2_diabetes and 'cr' to chronic_kidney_disease synonym lists "
                            "in disease-definition-knowledge-base.json (REQUIRES human confirmation; references/*.json is not auto-edited).",
            "caught_instead_by": ["llm"],
        })

    return {
        "case_id": "glm7-n1",
        "schema": "integration_benchmark_n1.v2",
        "generated_by": "scripts/rag/evals/run_glm7_n1.py",
        "tier": paper["tier"],
        "provenance": {
            "fulltext_sha256": paper["source"]["fulltext_sha256"],
            "disease_kb_version": spec["_provenance"]["disease_kb_version"],
            "in_peer_review_kb": paper["source"]["in_peer_review_kb"],
            "lopo_excluded_paper_ids": [GLM7_KB_ID],
        },
        "layers": {
            "deterministic": {
                "measured": True, "reproducible": True,
                "guard_runs": guard_runs,
                "verdict": det_verdict,
                "binding": True,
                "concern_coverage": f"{_cov('deterministic')}/{n}",
                "column_level": {
                    "expected_definition_columns": expected_cols,
                    "caught": det_caught_cols,
                    "missed": det_missed_cols,
                    "recall": f"{len(det_caught_cols)}/{len(expected_cols)}",
                },
            },
            "rag": {
                "metric_kind": "retrieval_self_consistency",
                "metric_caveat": "GT rag ids were observed from retrieval, so this is NOT blind recall.",
                "reproducible": True,
                "retrievals": retrievals,
                "failure_class_provenance": rag_provenance,
                "gate_derived_classes": sorted(k for k, v in rag_provenance.items() if v["source"] == "gate_run"),
                "verdict": rag_verdict,
                "on_topic_coverage": f"{_cov('rag')}/{n}",
                "distinct_concerns_credited": len(rag_credited_concern_ids),
                "independent_precision": adjudication["rag"]["independent_precision"] if adjudication else None,
            },
            "llm": {
                "metric_kind": "self_attested",
                "metric_caveat": "self_attested_coverage is from the frozen file's own addresses_gt; "
                                 "blind_adjudicated_coverage is the independent blind check (see adjudication).",
                "reproducible": False,
                "verdict": llm_verdict,
                "self_attested_coverage": f"{_cov('llm')}/{n}",
                "blind_adjudicated_coverage": adjudication["llm"]["blind_adjudicated_coverage"] if adjudication else None,
            },
        },
        "attribution": attribution,
        "metrics": {
            "n_ground_truth": n,
            "deterministic_concern_coverage": f"{_cov('deterministic')}/{n}",
            "deterministic_column_recall": f"{len(det_caught_cols)}/{len(expected_cols)}",
            "rag_retrieval_self_consistency": f"{_cov('rag')}/{n}",
            "rag_independent_precision": adjudication["rag"]["independent_precision"] if adjudication else None,
            "llm_self_attested_coverage": f"{_cov('llm')}/{n}",
            "llm_blind_adjudicated_coverage": adjudication["llm"]["blind_adjudicated_coverage"] if adjudication else None,
            "llm_self_attestation_validated": adjudication["llm"]["self_attestation_validated"] if adjudication else None,
            "union_any_layer": f"{sum(1 for a in attribution if a['caught_by'])}/{n}",
            "union_reproducible_layers_only": f"{sum(1 for a in attribution if ({'deterministic','rag'} & set(a['caught_by'])))}/{n}",
            "reproducible_verdict": reproducible_verdict,
            "frozen_augmented_verdict": frozen_augmented_verdict,
            "off_prediction_hits": [a["gt_id"] for a in attribution if a["off_prediction_layers"]],
            "asymmetry": {
                "property": "structural",
                "note": "final = min(...) can never RAISE a verdict by construction. This N=1 cannot empirically TEST asymmetry: rag_verdict is a fixed advisory cap and every layer here lands at <= concern, so nothing was in a position to (incorrectly) raise the verdict. Report this as a design invariant, not a measurement.",
            },
        },
        "adjudication": adjudication,
        "followups": followups,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Regenerate the frozen record.json.")
    ap.add_argument("--json", action="store_true", help="Print the computed record to stdout.")
    args = ap.parse_args()

    record = compute_record()
    record_path = RECORD_DIR / "record.json"

    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=False))

    if args.write:
        record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[run_glm7_n1] wrote {record_path.relative_to(REPO_ROOT)}")
        return 0

    if not record_path.exists():
        print(f"[run_glm7_n1] no frozen record at {record_path} — run with --write first.", file=sys.stderr)
        return 2

    frozen = json.loads(record_path.read_text(encoding="utf-8"))
    # The drift check covers ONLY the script-reproducible layers + their metrics.
    # The frozen LLM layer is re-read each run, so it cannot drift by construction
    # (and is excluded from the comparison's meaning, not its bytes).
    if frozen.get("layers", {}).get("deterministic") != record["layers"]["deterministic"] \
            or frozen.get("layers", {}).get("rag") != record["layers"]["rag"] \
            or frozen.get("metrics") != record["metrics"]:
        print("[run_glm7_n1] DRIFT: recomputed deterministic/RAG layers or metrics differ from frozen record.json.", file=sys.stderr)
        for layer in ("deterministic", "rag"):
            if frozen.get("layers", {}).get(layer) != record["layers"][layer]:
                print(f"  - layer '{layer}' changed", file=sys.stderr)
        if frozen.get("metrics") != record["metrics"]:
            print("  - metrics changed", file=sys.stderr)
        return 2

    m = record["metrics"]
    print(f"[run_glm7_n1] OK — reproducible layers match. "
          f"reproducible_verdict={m['reproducible_verdict']} (det binds) | "
          f"det concern {m['deterministic_concern_coverage']} col {m['deterministic_column_recall']} | "
          f"rag self-consistency {m['rag_retrieval_self_consistency']} (blind precision {m['rag_independent_precision']}) | "
          f"llm self-attested {m['llm_self_attested_coverage']} (blind-adjudicated {m['llm_blind_adjudicated_coverage']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
