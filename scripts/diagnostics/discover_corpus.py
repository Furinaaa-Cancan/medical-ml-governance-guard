#!/usr/bin/env python3
"""Discover candidate medical-ML papers in 3 transparent-peer-review journals.

Sources:
  - Nature Communications      (S64187185) - 87990 works
  - npj Digital Medicine        (S4210195431) - 2676 works
  - Communications Medicine     (S4210167893) - 1612 works

Strategy: query OpenAlex with multiple medical-ML queries per journal,
union all results, dedup by DOI, exclude DOIs already in our KB.

Writes:
  paper/discovery-candidates.json — all candidate DOIs + metadata, no
  downloads yet. Inspect before fetching peer review PDFs.

Note on copyright: outputs only factual metadata (DOI, title, year,
authors, abstract snippet). Title and abstract are factual citations
of published works, allowed under fair use for bibliography purposes.
We do not store or redistribute paper full text or peer review content
in this script — that's a downstream step.

Usage:
  python3 scripts/diagnostics/discover_corpus.py
"""
from __future__ import annotations
import json, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
OUT_JSON = ROOT / "paper" / "discovery-candidates.json"

UA = "mlgg-discovery/1.0 (mailto:cancansauce@163.com)"

JOURNALS = {
    "Nature Communications":    "S64187185",
    "npj Digital Medicine":     "S4210195431",
    "Communications Medicine":  "S4210167893",
}

# Medical ML queries — diverse phrasings to catch papers that didn't
# match a single query. Each gets a separate search per journal.
QUERIES = [
    "machine learning clinical prediction",
    "deep learning medical diagnosis",
    "machine learning EHR cohort",
    "risk prediction model patient",
    "AI clinical decision support",
    "neural network disease prediction",
    "machine learning prognosis",
    "cohort study prediction model",
]

YEAR_FROM = 2020  # filter to recent papers only


def openalex_search(source_id: str, query: str, year_from: int = YEAR_FROM,
                    per_page: int = 200) -> list[dict]:
    """Search OpenAlex; return list of work dicts with DOI, title, year."""
    import urllib.parse
    q = urllib.parse.quote(query)
    url = (f"https://api.openalex.org/works"
           f"?filter=primary_location.source.id:{source_id},"
           f"publication_year:{year_from}-2026"
           f"&search={q}"
           f"&per-page={per_page}")
    try:
        r = subprocess.run(["curl","-sSL","-A",UA,url],
                          capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout)
        return d.get("results", [])
    except Exception as e:
        print(f"  query failed ({query[:30]}): {e}", file=sys.stderr)
        return []


def main() -> int:
    # Load existing KB DOIs to exclude
    kb = json.loads(KB_PATH.read_text())
    existing_dois = {e['paper_doi'].lower() for e in kb['entries']
                     if e.get('paper_doi')}
    print(f"Existing KB DOIs to exclude: {len(existing_dois)}", file=sys.stderr)

    all_candidates: dict[str, dict] = {}  # doi -> work metadata

    for jname, jid in JOURNALS.items():
        print(f"\n=== Searching {jname} ({jid}) ===", file=sys.stderr)
        for q in QUERIES:
            results = openalex_search(jid, q)
            new_count = 0
            for r in results:
                doi = (r.get('doi') or '').replace('https://doi.org/','').lower().strip()
                if not doi or doi in existing_dois or doi in all_candidates:
                    continue
                # Reconstruct minimal record (factual metadata only)
                title = r.get('title', '') or ''
                # Title-based filter: must mention something medical+ML
                title_lc = title.lower()
                ml_words = ['machine learning','deep learning','neural network',
                           'artificial intelligence','random forest','gradient boost',
                           'xgboost','transformer','model','prediction','prognostic',
                           'algorithm','classifier','classification']
                med_words = ['patient','clinical','disease','cohort','hospital',
                            'diagnosis','prognosis','health','medical','EHR',
                            'electronic health','outcome','mortality','survival',
                            'risk','therapy','treatment','treatment','therapy',
                            'ICU','sepsis','cancer','diabetes','heart','kidney',
                            'cardiovascular','prediction']
                has_ml = any(w in title_lc for w in ml_words)
                has_med = any(w in title_lc for w in med_words)
                if not (has_ml and has_med):
                    continue
                all_candidates[doi] = {
                    "doi": doi,
                    "title": title,
                    "year": r.get('publication_year'),
                    "journal": jname,
                    "openalex_id": r.get('id'),
                    "matched_query": q,
                    "is_oa": r.get('open_access',{}).get('is_oa', False),
                    "type": r.get('type'),
                    "cited_by_count": r.get('cited_by_count', 0),
                }
                new_count += 1
            print(f"  query \"{q[:40]}\": {len(results)} hits, {new_count} new candidates",
                  file=sys.stderr)
            time.sleep(0.5)  # polite to OpenAlex

    # Save
    candidates = sorted(all_candidates.values(),
                       key=lambda x: (x['journal'], -(x['year'] or 0), x['doi']))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "OpenAlex search across 3 journals × 8 queries; title-keyword filter for ML+medical",
        "journals": list(JOURNALS.keys()),
        "queries": QUERIES,
        "year_from": YEAR_FROM,
        "existing_kb_dois_excluded": len(existing_dois),
        "total_candidates": len(candidates),
        "candidates": candidates,
    }, indent=2, ensure_ascii=False))

    # Stats
    from collections import Counter
    by_journal = Counter(c['journal'] for c in candidates)
    by_year = Counter(c['year'] for c in candidates)
    print(f"\n=== Discovery summary ===")
    print(f"  Existing KB DOIs: {len(existing_dois)}")
    print(f"  New candidates discovered: {len(candidates)}")
    print(f"\n  By journal:")
    for j, n in by_journal.most_common():
        print(f"    {j}: {n}")
    print(f"\n  By year:")
    for y, n in sorted(by_year.items(), key=lambda x: -(x[0] or 0)):
        print(f"    {y}: {n}")
    print(f"\n  Output: {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
