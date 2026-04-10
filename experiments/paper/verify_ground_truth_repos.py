#!/usr/bin/env python3
"""
Verify and scan ground truth candidate repos.

For each candidate:
1. Clone the repo
2. Check if it has Python ML training code
3. Run MLGG lint
4. Output a structured report for human annotation

Usage:
    python3 experiments/paper/verify_ground_truth_repos.py \
        --candidates experiments/paper/ground_truth_candidates.json \
        --output experiments/paper/output/ground_truth_scan.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Reuse scanning functions from scan_published_repos
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_published_repos import clone_repo, find_ml_files, run_lint_on_file, _is_training_file

import tempfile


def scan_candidate(url: str, candidate_id: int, domain: str) -> Dict[str, Any]:
    """Clone, verify, and scan a single candidate repo."""
    with tempfile.TemporaryDirectory(prefix=f"mlgg_gt_{candidate_id}_") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        # Clone
        if not clone_repo(url, repo_dir):
            return {"id": candidate_id, "url": url, "domain": domain,
                    "status": "clone_failed"}

        # Find files
        ml_files = find_ml_files(repo_dir)
        training_files = [f for f in ml_files if _is_training_file(f)]

        if not training_files:
            return {"id": candidate_id, "url": url, "domain": domain,
                    "status": "no_training_code",
                    "python_files": len(ml_files)}

        # Run lint on all training files
        all_findings: List[Dict[str, Any]] = []
        file_reports: List[Dict[str, Any]] = []

        for f in training_files:
            findings = run_lint_on_file(f)
            rel_path = str(f.relative_to(repo_dir))

            # Read first 5000 chars for context
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                line_count = content.count("\n") + 1
            except OSError:
                content = ""
                line_count = 0

            file_report = {
                "file": rel_path,
                "lines": line_count,
                "findings_count": len(findings),
                "findings": [
                    {
                        "rule_id": fd.get("rule_id"),
                        "severity": fd.get("severity"),
                        "message": fd.get("message"),
                        "line": fd.get("location", {}).get("line"),
                    }
                    for fd in findings
                ],
            }
            file_reports.append(file_report)
            for fd in findings:
                loc = fd.get("location", {})
                if "file" in loc:
                    try:
                        loc["file"] = str(Path(loc["file"]).relative_to(repo_dir))
                    except ValueError:
                        pass
            all_findings.extend(findings)

        # Aggregate
        rule_counts = {}
        severity_counts = {"error": 0, "warning": 0, "info": 0}
        for fd in all_findings:
            rid = fd.get("rule_id", "unknown")
            rule_counts[rid] = rule_counts.get(rid, 0) + 1
            sev = fd.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        leakage_rules = {"R001", "R002", "R003", "R005", "R006", "R007",
                         "R017", "R020", "R023", "R024", "R026", "R027"}
        has_leakage = any(
            fd.get("severity") == "error" and fd.get("rule_id") in leakage_rules
            for fd in all_findings
        )

        return {
            "id": candidate_id,
            "url": url,
            "domain": domain,
            "status": "scanned",
            "python_files": len(ml_files),
            "training_files": len(training_files),
            "total_findings": len(all_findings),
            "rule_counts": dict(sorted(rule_counts.items())),
            "severity_counts": severity_counts,
            "lint_says_leakage": has_leakage,
            "file_reports": file_reports,
            # Human annotation fields (to be filled)
            "human_annotation": {
                "has_leakage": None,
                "leakage_types": [],
                "leakage_locations": [],
                "other_issues": [],
                "notes": ""
            }
        }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="experiments/paper/ground_truth_candidates.json")
    parser.add_argument("--output", default="experiments/paper/output/ground_truth_scan.json")
    args = parser.parse_args()

    with open(args.candidates) as f:
        data = json.load(f)

    candidates = data["candidates"]
    print(f"Verifying {len(candidates)} candidate repos...\n")

    results = []
    valid = 0
    for c in candidates:
        cid = c["id"]
        url = c["url"]
        domain = c["domain"]
        name = url.rstrip("/").split("/")[-1]

        print(f"[{cid}/{len(candidates)}] {name} ({domain})...", end="", flush=True)
        result = scan_candidate(url, cid, domain)
        status = result["status"]

        if status == "scanned":
            valid += 1
            leak = "LEAK" if result["lint_says_leakage"] else "clean"
            print(f" {result['training_files']} train files, "
                  f"{result['total_findings']} findings [{leak}]")
        elif status == "no_training_code":
            print(f" no training code ({result['python_files']} py files)")
        else:
            print(f" {status}")

        results.append(result)

    # Summary
    scanned = [r for r in results if r["status"] == "scanned"]
    lint_leak = [r for r in scanned if r["lint_says_leakage"]]

    print(f"\n{'='*60}")
    print(f"VERIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Total candidates: {len(candidates)}")
    print(f"  Clone failed: {sum(1 for r in results if r['status']=='clone_failed')}")
    print(f"  No training code: {sum(1 for r in results if r['status']=='no_training_code')}")
    print(f"  Valid (scanned): {len(scanned)}")
    print(f"  Lint says leakage: {len(lint_leak)}/{len(scanned)}")

    # Save
    output = {
        "experiment": "ground_truth_validation",
        "date": "2026-04-09",
        "summary": {
            "total_candidates": len(candidates),
            "valid_repos": len(scanned),
            "lint_leakage_count": len(lint_leak),
        },
        "results": results,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nOutput: {out_path}")
    print(f"\n下一步: 打开 {out_path}，对每个 scanned repo 填写 human_annotation 字段")
    return 0


if __name__ == "__main__":
    sys.exit(main())
