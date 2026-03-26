#!/usr/bin/env python3
"""
Verify and quality-filter the papers_with_code manifest.

Automated quality checks:
  1. Repo downloadable (zip download succeeds)
  2. Repo has Python files with ML training code (imports sklearn etc.)
  3. Repo README/description mentions the paper (DOI or title match)
  4. Paper title contains prediction/classification keywords
  5. Repo is not empty or trivially small

Usage:
  python3 experiments/paper/verify_repos.py \\
      --input experiments/paper/papers_with_code.jsonl \\
      --output experiments/paper/papers_verified.jsonl \\
      --max-repos 50
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ML_TRAINING_IMPORTS = {
    "sklearn", "scikit-learn", "xgboost", "lightgbm", "catboost",
    "tensorflow", "keras", "torch", "pytorch",
}

ML_TRAINING_CALLS = {
    "train_test_split", "cross_val_score", "GridSearchCV",
    "RandomizedSearchCV", "StratifiedKFold", "KFold",
    ".fit(", ".fit_transform(", ".predict(", ".predict_proba(",
}

PREDICTION_KEYWORDS = {
    "predict", "prediction", "predictive", "prognos", "diagnos",
    "classif", "detection", "detect", "risk score", "risk model",
    "mortality", "readmission", "survival", "screening",
    "early warning", "triage", "severity",
}

TITLE_EXCLUDE = {
    "review", "survey", "meta-analysis", "systematic review",
    "tutorial", "benchmark", "overview", "guideline",
}


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------

def check_title_relevance(title: str) -> Tuple[bool, str]:
    """Check if title suggests a prediction/classification study."""
    t = title.lower()
    if any(kw in t for kw in TITLE_EXCLUDE):
        return False, "title_is_review_or_survey"
    if any(kw in t for kw in PREDICTION_KEYWORDS):
        return True, "title_has_prediction_keyword"
    return False, "title_no_prediction_keyword"


def download_repo_zip(github_url: str, timeout: int = 30) -> Optional[zipfile.ZipFile]:
    """Download repo as zip, return ZipFile or None."""
    repo_path = github_url.rstrip("/").replace("https://github.com/", "").replace("http://github.com/", "")
    for branch in ("main", "master"):
        zip_url = f"https://codeload.github.com/{repo_path}/zip/refs/heads/{branch}"
        try:
            req = urllib.request.Request(zip_url, headers={"User-Agent": "MLGG-Verify/1.0"})
            data = urllib.request.urlopen(req, timeout=timeout).read()
            return zipfile.ZipFile(io.BytesIO(data))
        except Exception:
            continue
    return None


def check_repo_has_training_code(zf: zipfile.ZipFile) -> Tuple[bool, Dict[str, Any]]:
    """Check if repo contains Python files with ML training code."""
    py_files = [n for n in zf.namelist() if n.endswith(".py") or n.endswith(".ipynb")]
    if not py_files:
        return False, {"reason": "no_python_files", "py_count": 0}

    has_ml_import = False
    has_training_call = False
    files_with_ml = 0

    for name in py_files:
        try:
            content = zf.read(name).decode("utf-8", errors="replace")
        except Exception:
            continue

        content_lower = content.lower()

        # Check ML imports
        if any(lib in content_lower for lib in ML_TRAINING_IMPORTS):
            has_ml_import = True

        # Check training calls
        if any(call in content for call in ML_TRAINING_CALLS):
            has_training_call = True
            files_with_ml += 1

    has_training = has_ml_import and has_training_call
    return has_training, {
        "py_count": len(py_files),
        "has_ml_import": has_ml_import,
        "has_training_call": has_training_call,
        "files_with_ml": files_with_ml,
    }


def check_repo_mentions_paper(zf: zipfile.ZipFile, doi: str, title: str) -> Tuple[bool, str]:
    """Check if repo README mentions the paper's DOI or title."""
    readme_names = [n for n in zf.namelist()
                    if n.lower().split("/")[-1] in ("readme.md", "readme.txt", "readme.rst", "readme")]

    if not readme_names:
        return False, "no_readme"

    for name in readme_names:
        try:
            content = zf.read(name).decode("utf-8", errors="replace")
        except Exception:
            continue

        # Check DOI match
        if doi and doi in content:
            return True, "doi_in_readme"

        # Check title match (fuzzy: at least 3 consecutive title words)
        if title:
            title_words = [w.lower() for w in title.split() if len(w) > 3]
            content_lower = content.lower()
            # Check if ≥3 consecutive title words appear in README
            for i in range(len(title_words) - 2):
                phrase = " ".join(title_words[i:i+3])
                if phrase in content_lower:
                    return True, "title_phrase_in_readme"

    return False, "no_match_in_readme"


def check_not_trivial(zf: zipfile.ZipFile) -> Tuple[bool, str]:
    """Check repo is not empty or trivially small."""
    files = [n for n in zf.namelist() if not n.endswith("/")]
    if len(files) < 2:
        return False, "too_few_files"
    py_files = [n for n in files if n.endswith(".py") or n.endswith(".ipynb")]
    if not py_files:
        return False, "no_python_files"
    # Check total Python LOC
    total_loc = 0
    for name in py_files[:20]:  # Cap to avoid huge repos
        try:
            content = zf.read(name).decode("utf-8", errors="replace")
            total_loc += content.count("\n")
        except Exception:
            pass
    if total_loc < 20:
        return False, f"trivial_code_{total_loc}_loc"
    return True, f"ok_{len(py_files)}_files_{total_loc}_loc"


# ---------------------------------------------------------------------------
# Main verification pipeline
# ---------------------------------------------------------------------------

def verify_paper(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Run all verification checks on a single paper."""
    result = {
        "paper_id": paper.get("paper_id", ""),
        "github_url": paper.get("github_url", ""),
        "title": paper.get("title", ""),
        "doi": paper.get("doi", ""),
        "journal": paper.get("journal", ""),
        "year": paper.get("year"),
        "checks": {},
        "include": False,
        "exclude_reason": None,
    }

    # Check 1: Title relevance
    title_ok, title_reason = check_title_relevance(paper.get("title", ""))
    result["checks"]["title_relevance"] = {"pass": title_ok, "detail": title_reason}
    if not title_ok:
        result["exclude_reason"] = title_reason
        return result

    # Check 2: Download repo
    zf = download_repo_zip(paper.get("github_url", ""))
    if zf is None:
        result["checks"]["downloadable"] = {"pass": False, "detail": "download_failed"}
        result["exclude_reason"] = "download_failed"
        return result
    result["checks"]["downloadable"] = {"pass": True}

    # Check 3: Not trivial
    trivial_ok, trivial_detail = check_not_trivial(zf)
    result["checks"]["not_trivial"] = {"pass": trivial_ok, "detail": trivial_detail}
    if not trivial_ok:
        result["exclude_reason"] = trivial_detail
        zf.close()
        return result

    # Check 4: Has ML training code
    train_ok, train_detail = check_repo_has_training_code(zf)
    result["checks"]["has_training_code"] = {"pass": train_ok, "detail": train_detail}
    if not train_ok:
        result["exclude_reason"] = "no_training_code"
        zf.close()
        return result

    # Check 5: Repo mentions paper
    mention_ok, mention_detail = check_repo_mentions_paper(
        zf, paper.get("doi", ""), paper.get("title", "")
    )
    result["checks"]["repo_mentions_paper"] = {"pass": mention_ok, "detail": mention_detail}
    # This is a WARNING, not exclusion — many repos don't have DOI in README
    # but are still the paper's code

    zf.close()

    # All critical checks passed
    result["include"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify paper repo quality.")
    parser.add_argument("--input", required=True, help="Input JSONL manifest.")
    parser.add_argument("--output", required=True, help="Output verified JSONL.")
    parser.add_argument("--max-repos", type=int, help="Limit repos to verify.")
    parser.add_argument("--report", type=str, help="Output verification report JSON.")
    args = parser.parse_args()

    with open(args.input) as f:
        papers = [json.loads(line) for line in f if line.strip()]

    if args.max_repos:
        papers = papers[:args.max_repos]

    total = len(papers)
    included = []
    excluded = []
    exclude_reasons: Dict[str, int] = {}

    for i, paper in enumerate(papers, 1):
        pid = paper.get("paper_id", "?")
        print(f"[{i}/{total}] {pid}...", end="", flush=True)

        result = verify_paper(paper)

        if result["include"]:
            included.append({**paper, "_verification": result["checks"]})
            mention = "✓" if result["checks"].get("repo_mentions_paper", {}).get("pass") else "?"
            print(f" INCLUDE (paper-link={mention})")
        else:
            excluded.append(result)
            reason = result["exclude_reason"]
            exclude_reasons[reason] = exclude_reasons.get(reason, 0) + 1
            print(f" EXCLUDE ({reason})")

        time.sleep(0.3)  # Rate limit

    # Save verified manifest
    with open(args.output, "w") as f:
        for p in included:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Print summary
    print(f"\n{'='*60}")
    print(f"VERIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Total: {total}")
    print(f"  Included: {len(included)} ({len(included)/total*100:.1f}%)")
    print(f"  Excluded: {len(excluded)} ({len(excluded)/total*100:.1f}%)")
    print(f"\nExclusion reasons:")
    for reason, count in sorted(exclude_reasons.items(), key=lambda x: -x[1]):
        print(f"  {count:4d}  {reason}")

    mention_count = sum(
        1 for p in included
        if p.get("_verification", {}).get("repo_mentions_paper", {}).get("pass")
    )
    print(f"\nRepo-paper link verified: {mention_count}/{len(included)} ({mention_count/len(included)*100:.1f}%)" if included else "")

    # Save report
    if args.report:
        report = {
            "total": total,
            "included": len(included),
            "excluded": len(excluded),
            "exclude_reasons": exclude_reasons,
            "repo_paper_link_verified": mention_count,
            "excluded_details": excluded,
        }
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport: {args.report}")

    print(f"Verified manifest: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
