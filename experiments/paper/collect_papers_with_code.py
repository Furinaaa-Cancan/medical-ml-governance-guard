#!/usr/bin/env python3
"""
Collect medical ML papers with public code from PubMed Central.

Strategy:
  1. Search PMC for medical ML prediction papers (full-text indexed)
  2. Fetch full-text XML for each paper
  3. Extract GitHub/GitLab URLs from the text
  4. Output a JSONL manifest for scan_published_repos.py

PMC is used instead of PubMed because PMC has full-text search,
allowing us to find GitHub links mentioned anywhere in the paper.

Usage:
  python3 experiments/paper/collect_papers_with_code.py \\
      --output experiments/paper/papers_with_code.jsonl \\
      --max-results 500 \\
      --email your@email.com
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# PubMed / PMC E-utilities
# ---------------------------------------------------------------------------

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Search query: medical ML papers mentioning "github" in full text (PMC)
PMC_SEARCH_QUERY = (
    '("machine learning" OR "deep learning" OR "random forest" OR "XGBoost" '
    'OR "gradient boosting" OR "neural network" OR "logistic regression") '
    'AND ("prediction" OR "classification" OR "prognostic" OR "diagnostic") '
    'AND ("patient" OR "clinical" OR "EHR" OR "electronic health record" '
    'OR "hospital" OR "cohort") '
    'AND "github.com" '
    'AND (2019:2025[pdat])'
)

GITHUB_URL_PATTERN = re.compile(
    r'https?://github\.com/[\w\-\.]+/[\w\-\.]+',
    re.IGNORECASE
)

# Known framework/library/tool repos — NOT paper-specific code.
# These get cited in papers but are not the paper's own implementation.
EXCLUDED_REPOS = {
    "scikit-learn/scikit-learn", "dmlc/xgboost", "fchollet/keras",
    "keras-team/keras", "tensorflow/tensorflow", "pytorch/pytorch",
    "microsoft/LightGBM", "catboost/catboost", "facebook/prophet",
    "PyTorchLightning/pytorch-lightning", "Lightning-AI/pytorch-lightning",
    "huggingface/transformers", "google/automl",
    "MIT-LCP/mimic-code", "MIT-LCP/mimic-iv", "MIT-LCP/mimic-iii",
    "YerevaNN/mimic3-benchmarks", "OHDSI/MIMIC",
    "jadore801120/attention-is-all-you-need-pytorch",
    "xiaopeng-liao/Pytorch-UNet", "numpy/numpy", "pandas-dev/pandas",
    "scipy/scipy", "statsmodels/statsmodels", "matplotlib/matplotlib",
    "mwaskom/seaborn", "Rdatatable/data.table",
    "OHDSI/CommonDataModel", "OHDSI/Atlas", "OHDSI/Achilles",
    "epfml/sent2vec", "google-research/bert",
}

DISEASE_KEYWORDS = {
    "cardiovascular": ["heart", "cardiac", "cardiovascular", "atrial", "coronary", "stroke", "hypertension"],
    "oncology": ["cancer", "tumor", "oncology", "malignant", "carcinoma", "lymphoma", "melanoma"],
    "diabetes": ["diabetes", "diabetic", "glycemic", "hba1c", "glucose", "insulin"],
    "sepsis_icu": ["sepsis", "icu", "intensive care", "critical care", "mortality prediction"],
    "kidney_disease": ["kidney", "renal", "aki", "ckd", "dialysis", "nephro"],
    "respiratory": ["lung", "pulmonary", "respiratory", "copd", "pneumonia", "covid"],
    "neurology": ["alzheimer", "dementia", "parkinson", "epilepsy", "stroke", "neurological"],
}


def _http_get(url: str, max_retries: int = 3) -> str:
    """HTTP GET with retries and rate limiting."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MLGG-PaperCollector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def search_pmc(query: str, max_results: int = 500, email: str = "") -> List[str]:
    """Search PMC and return list of PMC IDs."""
    params = {
        "db": "pmc",
        "term": query,
        "retmax": min(max_results, 10000),
        "retmode": "json",
        "sort": "relevance",
    }
    if email:
        params["email"] = email

    url = f"{EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    print(f"Searching PMC: {query[:80]}...")
    raw = _http_get(url)
    data = json.loads(raw)

    result = data.get("esearchresult", {})
    total = int(result.get("count", 0))
    ids = result.get("idlist", [])
    print(f"  Found {total} results, fetching top {len(ids)}")
    return ids


def fetch_pmc_summary(pmc_ids: List[str], email: str = "") -> List[Dict[str, Any]]:
    """Fetch summary metadata for a batch of PMC articles."""
    summaries: List[Dict[str, Any]] = []

    # Process in batches of 100
    for i in range(0, len(pmc_ids), 100):
        batch = pmc_ids[i:i + 100]
        params = {
            "db": "pmc",
            "id": ",".join(batch),
            "retmode": "json",
        }
        if email:
            params["email"] = email

        url = f"{EUTILS_BASE}/esummary.fcgi?{urllib.parse.urlencode(params)}"
        raw = _http_get(url)
        data = json.loads(raw)

        result = data.get("result", {})
        for pmcid in batch:
            info = result.get(pmcid, {})
            if not isinstance(info, dict):
                continue
            summaries.append({
                "pmcid": f"PMC{pmcid}",
                "title": info.get("title", ""),
                "source": info.get("source", ""),  # journal
                "pubdate": info.get("pubdate", ""),
                "doi": info.get("doi", ""),
                "pmid": info.get("pmid", ""),
                "authors": [
                    a.get("name", "") for a in info.get("authors", [])
                    if isinstance(a, dict)
                ][:5],
            })

        if i + 100 < len(pmc_ids):
            time.sleep(0.5)  # Rate limit

    return summaries


def fetch_pmc_fulltext(pmcid: str, email: str = "") -> Optional[str]:
    """Fetch full-text XML from PMC."""
    # Strip "PMC" prefix if present
    numeric_id = pmcid.replace("PMC", "")
    params = {
        "db": "pmc",
        "id": numeric_id,
        "retmode": "xml",
    }
    if email:
        params["email"] = email

    url = f"{EUTILS_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
    try:
        return _http_get(url)
    except Exception:
        return None


def extract_github_urls(xml_text: str) -> List[str]:
    """Extract GitHub URLs from PMC full-text XML."""
    urls = set(GITHUB_URL_PATTERN.findall(xml_text))
    # Clean up URLs (remove trailing punctuation, fragments)
    cleaned: Set[str] = set()
    for url in urls:
        url = url.rstrip(".,;:)")
        # Normalize to repo root (remove tree/blob paths)
        parts = url.split("/")
        if len(parts) >= 5:
            repo_url = "/".join(parts[:5])  # https://github.com/user/repo
            cleaned.add(repo_url)
    return sorted(cleaned)


def classify_disease(title: str, abstract: str = "") -> str:
    """Classify paper into disease area based on title/abstract keywords."""
    text = (title + " " + abstract).lower()
    for area, keywords in DISEASE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return area
    return "other"


def extract_year(pubdate: str) -> Optional[int]:
    """Extract year from pubdate string."""
    if not pubdate:
        return None
    for part in pubdate.split():
        if part.isdigit() and len(part) == 4:
            return int(part)
    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def collect_papers(
    max_results: int = 500,
    email: str = "",
    output_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Full pipeline: search → fetch metadata → extract GitHub URLs."""

    # Step 1: Search PMC
    pmc_ids = search_pmc(PMC_SEARCH_QUERY, max_results=max_results, email=email)
    if not pmc_ids:
        print("No results found.")
        return []

    # Step 2: Fetch summaries
    print(f"Fetching metadata for {len(pmc_ids)} articles...")
    summaries = fetch_pmc_summary(pmc_ids, email=email)
    print(f"  Got {len(summaries)} summaries")

    # Step 3: Fetch full text and extract GitHub URLs
    papers_with_code: List[Dict[str, Any]] = []
    seen_repos: Set[str] = set()

    print(f"Scanning full texts for GitHub URLs...")
    for i, s in enumerate(summaries):
        pmcid = s["pmcid"]
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(summaries)}] scanned...")

        xml = fetch_pmc_fulltext(pmcid, email=email)
        if not xml:
            continue

        github_urls = extract_github_urls(xml)
        if not github_urls:
            continue

        # Deduplicate by repo URL and filter out known libraries
        for url in github_urls:
            if url in seen_repos:
                continue
            # Extract "user/repo" and check against exclusion list
            parts = url.rstrip("/").split("/")
            if len(parts) >= 5:
                user_repo = f"{parts[3]}/{parts[4]}"
                if user_repo in EXCLUDED_REPOS:
                    continue
            seen_repos.add(url)

            year = extract_year(s["pubdate"])
            first_author = s["authors"][0].split()[-1] if s["authors"] else "unknown"
            disease = classify_disease(s["title"])
            paper_id = f"{first_author.lower()}_{year}_{disease}"

            # Ensure unique paper_id
            base_id = paper_id
            counter = 2
            while any(p["paper_id"] == paper_id for p in papers_with_code):
                paper_id = f"{base_id}_{counter}"
                counter += 1

            papers_with_code.append({
                "paper_id": paper_id,
                "doi": s.get("doi", ""),
                "pmcid": pmcid,
                "pmid": s.get("pmid", ""),
                "github_url": url,
                "journal": s.get("source", ""),
                "year": year,
                "disease_area": disease,
                "title": s.get("title", ""),
                "authors": s.get("authors", []),
            })

        # Rate limit for PMC
        time.sleep(0.4)

    print(f"\nFound {len(papers_with_code)} papers with unique GitHub repos")

    # Step 4: Save
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as f:
            for p in papers_with_code:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"Saved to {output_path}")

    return papers_with_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect medical ML papers with public code from PMC."
    )
    parser.add_argument("--output", type=str,
                        default="experiments/paper/papers_with_code.jsonl",
                        help="Output JSONL path.")
    parser.add_argument("--max-results", type=int, default=500,
                        help="Max PMC search results.")
    parser.add_argument("--email", type=str, default="",
                        help="Email for NCBI E-utilities (recommended for large queries).")

    args = parser.parse_args()

    papers = collect_papers(
        max_results=args.max_results,
        email=args.email,
        output_path=Path(args.output),
    )

    if papers:
        # Print summary
        journals: Dict[str, int] = {}
        diseases: Dict[str, int] = {}
        years: Dict[int, int] = {}
        for p in papers:
            j = p.get("journal", "unknown")
            journals[j] = journals.get(j, 0) + 1
            d = p.get("disease_area", "other")
            diseases[d] = diseases.get(d, 0) + 1
            y = p.get("year")
            if y:
                years[y] = years.get(y, 0) + 1

        print(f"\n{'='*50}")
        print(f"COLLECTION SUMMARY: {len(papers)} papers")
        print(f"{'='*50}")
        print(f"\nTop journals:")
        for j, c in sorted(journals.items(), key=lambda x: -x[1])[:10]:
            print(f"  {c:3d}  {j}")
        print(f"\nDisease areas:")
        for d, c in sorted(diseases.items(), key=lambda x: -x[1]):
            print(f"  {c:3d}  {d}")
        print(f"\nYears:")
        for y, c in sorted(years.items()):
            print(f"  {y}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
