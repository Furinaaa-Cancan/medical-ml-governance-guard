#!/usr/bin/env python3
"""
LLM-based methodology review of medical ML papers using MLGG criteria.

Reads Methods sections from PubMed Central, sends to Qwen API with
MLGG's 12-dimension review standard, outputs structured assessments.

Usage:
  export DASHSCOPE_API_KEY=sk-...
  python3 experiments/paper/review_methods_llm.py \
      --pmcid PMC12345678 \
      --output /tmp/review_result.json

  # Batch mode
  python3 experiments/paper/review_methods_llm.py \
      --pmcid-list experiments/paper/pmcids.txt \
      --output-dir experiments/paper/output/llm_reviews/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# MLGG Review Prompt
# ---------------------------------------------------------------------------

MLGG_REVIEW_PROMPT = """You are an expert reviewer assessing a medical ML prediction study's methodology for data leakage and methodological rigor.

Review the Methods section below and assess EACH of the following 12 dimensions. For each dimension, output:
- score: 0 (not addressed), 1 (partially addressed), 2 (fully addressed)
- issues: list of specific methodological concerns found
- evidence: quote from the text supporting your assessment

## 12 Dimensions

1. **Data Integrity**: Are train/valid/test splits clearly described? Is patient-level separation confirmed? Is temporal ordering maintained?

2. **Leakage Prevention**: Is there evidence of data leakage? Specifically:
   - Was preprocessing (scaling, imputation) fitted on training data only?
   - Was feature selection done on training data only?
   - Were resampling methods (SMOTE) applied to training data only?
   - Is there any indication that test data influenced model development?

3. **Pipeline Isolation**: Is the preprocessing pipeline properly isolated? Is imputation/scaling fitted only on training data and applied (transform only) to test?

4. **Model Selection Rigor**: Were ≥3 candidate models compared? Was there a proper validation strategy? Was the test set held out from all tuning?

5. **Statistical Validity**: Are confidence intervals reported? Is calibration assessed? Is there a permutation test or other significance test? Are bootstrap CIs used?

6. **Generalization Evidence**: Is there external validation? Is the train-test performance gap discussed? Is there multi-site or temporal validation?

7. **Clinical Completeness**: Are sensitivity, specificity, PPV, NPV reported? Is there a decision curve analysis? Is the operating threshold justified?

8. **Reporting Standards**: Does the study follow TRIPOD+AI? PROBAST? Are limitations discussed?

9. **Reproducibility**: Are random seeds documented? Is code available? Are software versions specified?

10. **Security & Provenance**: Is data provenance documented? Are model artifacts versioned?

11. **Fairness & Equity**: Are subgroup analyses performed? Is there assessment of disparate impact across demographics?

12. **Sample Size Adequacy**: Is EPV (events per variable) ≥10? Is the sample size justified? Are minimum event counts met?

## Additional Leakage Checks (Kapoor & Narayanan 2023 taxonomy)

Flag ANY of these if detected:
- L1.1: No proper test set (same data for training and evaluation)
- L1.2: Preprocessing on combined train+test data before splitting
- L1.3: Feature selection on combined data before splitting
- L1.4: Duplicate samples across train/test splits
- L2: Illegitimate features (post-index variables, target proxies)
- L3.1: Temporal leakage (future information in training data)
- L3.2: Patient-level non-independence (same patient in multiple splits)

## Output Format

Return a JSON object with this EXACT structure:
{
  "overall_score": <sum of 12 dimension scores, max 24>,
  "grade": "<Publication-grade / Solid / Major issues / Not publishable>",
  "dimensions": {
    "data_integrity": {"score": 0-2, "issues": [...], "evidence": "..."},
    "leakage_prevention": {"score": 0-2, "issues": [...], "evidence": "..."},
    "pipeline_isolation": {"score": 0-2, "issues": [...], "evidence": "..."},
    "model_selection": {"score": 0-2, "issues": [...], "evidence": "..."},
    "statistical_validity": {"score": 0-2, "issues": [...], "evidence": "..."},
    "generalization": {"score": 0-2, "issues": [...], "evidence": "..."},
    "clinical_completeness": {"score": 0-2, "issues": [...], "evidence": "..."},
    "reporting_standards": {"score": 0-2, "issues": [...], "evidence": "..."},
    "reproducibility": {"score": 0-2, "issues": [...], "evidence": "..."},
    "security_provenance": {"score": 0-2, "issues": [...], "evidence": "..."},
    "fairness_equity": {"score": 0-2, "issues": [...], "evidence": "..."},
    "sample_size": {"score": 0-2, "issues": [...], "evidence": "..."}
  },
  "leakage_flags": ["L1.2", ...],
  "top_concerns": ["concern1", "concern2", "concern3"],
  "summary": "One paragraph overall assessment"
}

IMPORTANT: Output ONLY the JSON object, no other text."""


# ---------------------------------------------------------------------------
# PMC Methods extraction
# ---------------------------------------------------------------------------

def fetch_pmc_methods(pmcid: str) -> Optional[str]:
    """Fetch Methods section from PMC full text."""
    numeric = pmcid.replace("PMC", "")
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={numeric}&retmode=xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MLGG-Review/1.0"})
        xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception as e:
        print(f"  Failed to fetch {pmcid}: {e}", file=sys.stderr)
        return None

    # Extract methods section from XML
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    methods_text = []
    for sec in root.iter("sec"):
        title_el = sec.find("title")
        if title_el is not None and title_el.text:
            title = title_el.text.lower()
            if any(kw in title for kw in ["method", "material", "study design",
                                           "statistical", "data collection",
                                           "model development", "experimental"]):
                # Extract all text from this section
                texts = []
                for p in sec.iter("p"):
                    if p.text:
                        texts.append(p.text)
                    for child in p:
                        if child.text:
                            texts.append(child.text)
                        if child.tail:
                            texts.append(child.tail)
                methods_text.append(" ".join(texts))

    if not methods_text:
        # Fallback: get abstract
        for abstract in root.iter("abstract"):
            for p in abstract.iter("p"):
                if p.text:
                    methods_text.append(p.text)

    return "\n\n".join(methods_text) if methods_text else None


# ---------------------------------------------------------------------------
# Qwen API
# ---------------------------------------------------------------------------

def call_qwen(methods_text: str, api_key: str, model: str = "qwen-plus") -> Optional[Dict]:
    """Send Methods text to Qwen for structured review."""
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    # Truncate to ~6000 chars to stay within context
    if len(methods_text) > 6000:
        methods_text = methods_text[:6000] + "\n\n[... truncated ...]"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": MLGG_REVIEW_PROMPT},
            {"role": "user", "content": f"## Methods Section\n\n{methods_text}"},
        ],
        "max_tokens": 2000,
        "temperature": 0.1,  # Low temperature for consistent structured output
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]

        # Parse JSON from response
        # Sometimes LLM wraps in ```json ... ```
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]

        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}", file=sys.stderr)
        print(f"  Raw: {content[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Review pipeline
# ---------------------------------------------------------------------------

def review_paper(pmcid: str, api_key: str, model: str = "qwen-plus") -> Dict[str, Any]:
    """Full review pipeline for one paper."""
    result = {"pmcid": pmcid, "status": "pending"}

    # Step 1: Fetch methods
    methods = fetch_pmc_methods(pmcid)
    if not methods:
        result["status"] = "no_methods"
        result["error"] = "Could not extract Methods section"
        return result

    result["methods_length"] = len(methods)

    # Step 2: Send to Qwen
    review = call_qwen(methods, api_key, model)
    if not review:
        result["status"] = "api_error"
        return result

    result["status"] = "reviewed"
    result["review"] = review
    result["overall_score"] = review.get("overall_score", 0)
    result["grade"] = review.get("grade", "Unknown")
    result["leakage_flags"] = review.get("leakage_flags", [])
    result["top_concerns"] = review.get("top_concerns", [])

    return result


def batch_review(
    pmcids: List[str],
    api_key: str,
    output_dir: Path,
    model: str = "qwen-plus",
    delay: float = 1.0,
) -> Dict[str, Any]:
    """Review multiple papers."""
    results = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, pmcid in enumerate(pmcids, 1):
        print(f"[{i}/{len(pmcids)}] {pmcid}...", end="", flush=True)

        # Check cache
        cached = output_dir / f"{pmcid}.json"
        if cached.exists():
            with cached.open() as f:
                result = json.load(f)
            results.append(result)
            print(f" cached ({result.get('grade', '?')})")
            continue

        result = review_paper(pmcid, api_key, model)

        # Save individual result
        with cached.open("w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        status = result.get("status", "?")
        grade = result.get("grade", "")
        score = result.get("overall_score", "")
        print(f" {status} | {grade} | score={score}")

        results.append(result)
        time.sleep(delay)

    # Aggregate
    reviewed = [r for r in results if r["status"] == "reviewed"]
    return aggregate(reviewed, results)


def aggregate(reviewed: List[Dict], all_results: List[Dict]) -> Dict[str, Any]:
    """Compute aggregate statistics."""
    if not reviewed:
        return {"total": len(all_results), "reviewed": 0}

    scores = [r["overall_score"] for r in reviewed]
    import statistics

    # Per-dimension means
    dim_scores: Dict[str, List[int]] = {}
    for r in reviewed:
        dims = r.get("review", {}).get("dimensions", {})
        for dim_name, dim_data in dims.items():
            dim_scores.setdefault(dim_name, []).append(dim_data.get("score", 0))

    # Leakage prevalence
    has_leakage = sum(1 for r in reviewed if r.get("leakage_flags"))

    # Grade distribution
    grades = {}
    for r in reviewed:
        g = r.get("grade", "Unknown")
        grades[g] = grades.get(g, 0) + 1

    return {
        "total": len(all_results),
        "reviewed": len(reviewed),
        "failed": len(all_results) - len(reviewed),
        "score_summary": {
            "mean": round(statistics.mean(scores), 1),
            "median": round(statistics.median(scores), 1),
            "std": round(statistics.stdev(scores), 1) if len(scores) > 1 else 0,
            "min": min(scores),
            "max": max(scores),
        },
        "grade_distribution": grades,
        "leakage_prevalence": {
            "papers_with_flags": has_leakage,
            "prevalence_pct": round(has_leakage / len(reviewed) * 100, 1),
        },
        "dimension_means": {
            dim: round(statistics.mean(vals), 2)
            for dim, vals in sorted(dim_scores.items())
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-based methodology review.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pmcid", help="Single PMC ID to review.")
    mode.add_argument("--pmcid-list", help="File with one PMC ID per line.")

    parser.add_argument("--output", help="Output JSON (single mode).")
    parser.add_argument("--output-dir", default="experiments/paper/output/llm_reviews",
                        help="Output directory (batch mode).")
    parser.add_argument("--model", default="qwen-plus", help="Qwen model name.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between API calls.")
    parser.add_argument("--max-papers", type=int, help="Limit papers to review.")

    args = parser.parse_args()

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not set.", file=sys.stderr)
        return 2

    if args.pmcid:
        result = review_paper(args.pmcid, api_key, args.model)
        out = args.output or f"review_{args.pmcid}.json"
        with open(out, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Score: {result.get('overall_score', '?')}/24")
        print(f"Grade: {result.get('grade', '?')}")
        if result.get("leakage_flags"):
            print(f"Leakage: {result['leakage_flags']}")
        print(f"Output: {out}")
    else:
        with open(args.pmcid_list) as f:
            pmcids = [line.strip() for line in f if line.strip()]
        if args.max_papers:
            pmcids = pmcids[:args.max_papers]
        agg = batch_review(pmcids, api_key, Path(args.output_dir), args.model, args.delay)

        out = Path(args.output_dir) / "aggregate.json"
        with out.open("w") as f:
            json.dump(agg, f, indent=2, ensure_ascii=False)

        print(f"\n{'='*50}")
        print(f"Reviewed: {agg['reviewed']}/{agg['total']}")
        print(f"Mean score: {agg['score_summary']['mean']}/24")
        print(f"Leakage prevalence: {agg['leakage_prevalence']['prevalence_pct']}%")
        print(f"Output: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
