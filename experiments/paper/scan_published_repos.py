#!/usr/bin/env python3
"""
Large-scale code audit of published medical ML repositories.

Pipeline:
  1. Read a manifest of published papers with GitHub URLs
  2. Clone each repo (shallow, temp dir)
  3. Run MLGG lint (R001-R020) on all .py and .ipynb files
  4. Aggregate leakage prevalence statistics

Manifest format (papers_with_code.jsonl):
  {"paper_id": "smith_2023", "doi": "10.1234/...", "github_url": "https://github.com/...", "journal": "Nature Medicine", "year": 2023, "disease_area": "cardiovascular", "title": "..."}

Usage:
  # Scan repos listed in manifest
  python3 experiments/paper/scan_published_repos.py \\
      --manifest experiments/paper/papers_with_code.jsonl \\
      --output experiments/paper/output/code_audit_results.json

  # Scan a single repo
  python3 experiments/paper/scan_published_repos.py \\
      --repo https://github.com/user/repo \\
      --output /tmp/single_scan.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINT_SCRIPT = REPO_ROOT / "scripts" / "mlgg.py"
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Repository scanning
# ---------------------------------------------------------------------------

def clone_repo(github_url: str, dest: Path, timeout: int = 120) -> bool:
    """Shallow-clone a GitHub repo."""
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", github_url, str(dest)],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def find_ml_files(repo_dir: Path) -> List[Path]:
    """Find Python and Jupyter notebook files likely containing ML code."""
    files: List[Path] = []
    for pattern in ("**/*.py", "**/*.ipynb"):
        for f in repo_dir.glob(pattern):
            # Skip common non-ML directories
            parts = f.relative_to(repo_dir).parts
            skip_dirs = {"node_modules", ".git", "__pycache__", "venv", ".venv",
                         "env", "docs", "doc", "test", "tests", "setup.py"}
            if any(p.lower() in skip_dirs for p in parts):
                continue
            # Skip very large files (>500KB)
            try:
                if f.stat().st_size > 500_000:
                    continue
            except OSError:
                continue
            files.append(f)
    return sorted(files)


def run_lint_on_file(filepath: Path) -> List[Dict[str, Any]]:
    """Run MLGG lint on a single file and return findings."""
    try:
        result = subprocess.run(
            [PYTHON, str(LINT_SCRIPT), "lint", "check", str(filepath), "--format", "json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        if result.stdout.strip():
            findings = json.loads(result.stdout)
            if isinstance(findings, list):
                return findings
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass
    return []


def scan_repo(
    repo_dir: Path,
    paper_id: str = "",
) -> Dict[str, Any]:
    """Scan all ML files in a repo and return aggregated findings."""
    files = find_ml_files(repo_dir)
    all_findings: List[Dict[str, Any]] = []
    files_scanned = 0
    files_with_issues = 0

    for f in files:
        findings = run_lint_on_file(f)
        files_scanned += 1
        if findings:
            files_with_issues += 1
            # Relativize paths
            for finding in findings:
                loc = finding.get("location", {})
                if "file" in loc:
                    try:
                        loc["file"] = str(Path(loc["file"]).relative_to(repo_dir))
                    except ValueError:
                        pass
            all_findings.extend(findings)

    # Aggregate by rule
    rule_counts: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for f in all_findings:
        rid = f.get("rule_id", "unknown")
        rule_counts[rid] = rule_counts.get(rid, 0) + 1
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Determine leakage types present
    leakage_rules = {
        "R001": "preprocessing_before_split",
        "R002": "scaler_on_test",
        "R003": "resample_on_test",
        "R005": "threshold_on_test",
        "R006": "feature_selection_on_full",
        "R007": "target_as_feature",
        "R017": "early_stop_on_test",
        "R020": "global_clean_before_split",
    }
    leakage_types_found = [
        leakage_rules[rid] for rid in rule_counts if rid in leakage_rules
    ]

    has_leakage = any(
        f.get("severity") == "error" and f.get("rule_id", "").startswith("R0")
        for f in all_findings
    )

    return {
        "paper_id": paper_id,
        "files_total": len(files),
        "files_scanned": files_scanned,
        "files_with_issues": files_with_issues,
        "total_findings": len(all_findings),
        "rule_counts": dict(sorted(rule_counts.items())),
        "severity_counts": severity_counts,
        "has_leakage_error": has_leakage,
        "leakage_types_found": leakage_types_found,
        "findings": all_findings,
    }


# ---------------------------------------------------------------------------
# Batch scanning
# ---------------------------------------------------------------------------

def scan_from_manifest(
    manifest_path: Path,
    output_dir: Path,
    max_repos: Optional[int] = None,
) -> Dict[str, Any]:
    """Scan all repos in a manifest file."""
    with manifest_path.open() as f:
        papers = [json.loads(line) for line in f if line.strip()]

    if max_repos:
        papers = papers[:max_repos]

    results: List[Dict[str, Any]] = []
    total = len(papers)

    for i, paper in enumerate(papers, 1):
        paper_id = paper.get("paper_id", f"paper_{i}")
        github_url = paper.get("github_url", "")
        title = paper.get("title", "")[:60]

        print(f"[{i}/{total}] {paper_id}: {title}")

        if not github_url:
            print(f"  SKIP: no GitHub URL")
            continue

        # Check if cached result exists
        cached = output_dir / "per_repo" / f"{paper_id}.json"
        if cached.exists():
            try:
                with cached.open() as f:
                    cached_result = json.load(f)
                results.append(cached_result)
                print(f"  cached ({cached_result.get('total_findings', 0)} findings)")
                continue
            except Exception:
                pass

        # Clone and scan
        with tempfile.TemporaryDirectory(prefix=f"mlgg_scan_{paper_id}_") as tmpdir:
            repo_dir = Path(tmpdir) / "repo"
            print(f"  cloning {github_url}...", end="", flush=True)

            if not clone_repo(github_url, repo_dir):
                print(" FAILED")
                result = {
                    "paper_id": paper_id,
                    "error": "clone_failed",
                    "github_url": github_url,
                }
                results.append(result)
                continue

            print(" scanning...", end="", flush=True)
            result = scan_repo(repo_dir, paper_id=paper_id)
            result["github_url"] = github_url
            result["doi"] = paper.get("doi", "")
            result["journal"] = paper.get("journal", "")
            result["year"] = paper.get("year")
            result["disease_area"] = paper.get("disease_area", "")
            result["title"] = paper.get("title", "")

            # Remove detailed findings from per-repo cache (keep summary only)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {k: v for k, v in result.items() if k != "findings"}
            with cached.open("w") as f:
                json.dump(cache_data, f, indent=2)

            n_findings = result["total_findings"]
            has_leak = "LEAKAGE" if result["has_leakage_error"] else "clean"
            print(f" {n_findings} findings [{has_leak}]")
            results.append(result)

    return aggregate_results(results)


def scan_single_repo(github_url: str) -> Dict[str, Any]:
    """Scan a single repo from URL."""
    with tempfile.TemporaryDirectory(prefix="mlgg_scan_") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"
        print(f"Cloning {github_url}...", flush=True)
        if not clone_repo(github_url, repo_dir):
            return {"error": "clone_failed", "github_url": github_url}
        print(f"Scanning...", flush=True)
        return scan_repo(repo_dir, paper_id="single_scan")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute prevalence statistics across all scanned repos."""
    valid = [r for r in results if "error" not in r]
    n_total = len(results)
    n_valid = len(valid)
    n_failed = n_total - n_valid

    if not valid:
        return {"n_repos": n_total, "n_scanned": 0, "n_failed": n_failed, "results": results}

    n_with_leakage = sum(1 for r in valid if r["has_leakage_error"])
    prevalence = n_with_leakage / n_valid if n_valid > 0 else 0

    # Aggregate rule counts across all repos
    global_rule_counts: Dict[str, int] = {}
    repos_per_rule: Dict[str, int] = {}
    for r in valid:
        for rule, count in r.get("rule_counts", {}).items():
            global_rule_counts[rule] = global_rule_counts.get(rule, 0) + count
            repos_per_rule[rule] = repos_per_rule.get(rule, 0) + 1

    # Leakage type prevalence
    leakage_type_counts: Dict[str, int] = {}
    for r in valid:
        for lt in r.get("leakage_types_found", []):
            leakage_type_counts[lt] = leakage_type_counts.get(lt, 0) + 1

    # Per-journal breakdown
    journal_stats: Dict[str, Dict[str, int]] = {}
    for r in valid:
        j = r.get("journal", "unknown")
        if j not in journal_stats:
            journal_stats[j] = {"total": 0, "with_leakage": 0}
        journal_stats[j]["total"] += 1
        if r["has_leakage_error"]:
            journal_stats[j]["with_leakage"] += 1

    # Strip detailed findings from output (too large)
    summary_results = []
    for r in results:
        sr = {k: v for k, v in r.items() if k != "findings"}
        summary_results.append(sr)

    return {
        "scan_summary": {
            "n_repos_total": n_total,
            "n_repos_scanned": n_valid,
            "n_repos_failed": n_failed,
            "n_with_leakage": n_with_leakage,
            "prevalence_pct": round(prevalence * 100, 1),
            "headline": f"{n_with_leakage}/{n_valid} repos ({prevalence*100:.1f}%) contain detectable data leakage",
        },
        "rule_prevalence": {
            rule: {
                "total_occurrences": global_rule_counts.get(rule, 0),
                "repos_affected": repos_per_rule.get(rule, 0),
                "repo_prevalence_pct": round(repos_per_rule.get(rule, 0) / n_valid * 100, 1),
            }
            for rule in sorted(global_rule_counts, key=lambda r: -global_rule_counts[r])
        },
        "leakage_type_prevalence": {
            lt: {
                "repos_affected": count,
                "prevalence_pct": round(count / n_valid * 100, 1),
            }
            for lt, count in sorted(leakage_type_counts.items(), key=lambda x: -x[1])
        },
        "journal_breakdown": journal_stats,
        "results": summary_results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan published medical ML repositories for data leakage."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--manifest", type=str, help="Path to papers_with_code.jsonl manifest.")
    mode.add_argument("--repo", type=str, help="Single GitHub repo URL to scan.")

    parser.add_argument("--output", type=str, required=True, help="Output JSON path.")
    parser.add_argument("--max-repos", type=int, help="Limit number of repos to scan.")
    parser.add_argument("--output-dir", type=str,
                        default=str(REPO_ROOT / "experiments" / "paper" / "output" / "code_audit"),
                        help="Directory for per-repo cached results.")

    args = parser.parse_args()

    t0 = time.time()

    if args.repo:
        result = scan_single_repo(args.repo)
    else:
        result = scan_from_manifest(
            Path(args.manifest),
            Path(args.output_dir),
            max_repos=args.max_repos,
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0

    if "scan_summary" in result:
        s = result["scan_summary"]
        print(f"\n{'='*60}")
        print(f"SCAN COMPLETE")
        print(f"{'='*60}")
        print(f"  {s['headline']}")
        print(f"  Scanned: {s['n_repos_scanned']}, Failed: {s['n_repos_failed']}")
        print(f"  Time: {elapsed/60:.1f} min")

        if result.get("leakage_type_prevalence"):
            print(f"\nLeakage type prevalence:")
            for lt, info in result["leakage_type_prevalence"].items():
                print(f"  {lt}: {info['repos_affected']} repos ({info['prevalence_pct']}%)")
    else:
        n = result.get("total_findings", 0)
        print(f"\nSingle repo: {n} findings, time: {elapsed:.1f}s")

    print(f"\nOutput: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
