#!/usr/bin/env python3
"""For each paper in the verified-cohort corpus, find its public code repository.

Reads:
  - references/case-studies/peer-review-kb.json (verified entries with high-confidence PDF)

Strategy per paper:
  1. Curl nature.com article page
  2. Regex-extract GitHub / GitLab / Zenodo / Figshare / OSF / CodeOcean URLs
  3. Heuristically extract "Code availability" paragraph (skip if not found)
  4. Tag each URL by source (Code availability / Data availability / inline)

Writes:
  - paper/code-repos-corpus.json (machine-readable)
  - paper/code-repos-corpus.md (human-readable)

Reproducibility: same UA, same regex, same paper subset → identical output.
"""
from __future__ import annotations
import json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
OUT_JSON = ROOT / "paper" / "code-repos-corpus.json"
OUT_MD = ROOT / "paper" / "code-repos-corpus.md"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"
# Manual override for cases where the "longest URL" heuristic picks a cited
# library rather than the paper's own code. Each entry visually verified
# from the Code availability section context (sentences like "the source
# code of <PaperName> is publicly available at:" are the canonical signal).
MANUAL_PRIMARY_REPO: dict[str, str] = {
    "PR-070": "https://github.com/ncbi-nlp/Clinical-Tool-Learning",
    # Add more here when manually verified.
}

URL_RE = re.compile(
    r'https://(?:'
    r'github\.com|gitlab\.com|zenodo\.org|figshare\.com|osf\.io|codeocean\.com|bitbucket\.org|'
    r'(?:dx\.)?doi\.org/10\.(?:5281|24433|6084|17605)/'  # DOI-form: zenodo, codeocean, figshare, OSF
    r')[A-Za-z0-9\-_./?=&%~+#]+',
    re.I,
)


def strict_inscope(entry):
    dt = entry.get('data_type', '').lower()
    task = entry.get('prediction_task', '').lower()
    if any(t in dt for t in ['_imaging','wsi','echocard','dermoscopy','retinal','ultrasound','microscopy','photography','mri','ct_','breast_mri','cardiac_mri','anterior_segment','ecg_image']):
        return False
    if any(t in dt for t in ['gwas','proteomics','metabolom','transcriptom','microbiome','cfrna','cfdna','genotype','genomic','lncrna','spatial_','olink','nmr_meta','biobank_genotype','molecular','biopsy','biomarker','serology','immunological']):
        return False
    if 'wearable' in dt or 'oximetry' in dt or 'ecg' in dt or 'ppg' in dt or 'echocardiogram' in dt: return False
    if 'notes' in dt and 'plus' not in dt: return False
    if 'survival' in task or 'time-to-event' in task or 'time-to-' in task: return False
    if not dt: return False
    return True


CACHE_DIR = ROOT / ".cache" / "nature_html"


def fetch_html(url: str) -> str:
    """Fetch with on-disk cache + retry/backoff for Nature rate limits."""
    import hashlib, time
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.html"
    if cache_file.exists() and cache_file.stat().st_size > 50000:
        return cache_file.read_text()
    for attempt in range(3):
        try:
            r = subprocess.run(["curl", "-sSL", "-A", UA, url],
                              capture_output=True, text=True, timeout=30)
            if len(r.stdout) > 50000:
                cache_file.write_text(r.stdout)
                time.sleep(2)  # be polite to Nature
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5 * (attempt + 1))  # exponential backoff
    return ""


def extract_section(html: str, heading: str) -> str:
    """Extract first <p> following the heading, strip HTML, return plain text."""
    m = re.search(rf'(?i)(?:>|\b){heading}[<>:][^<]{{0,50}}.*?<p[^>]*>(.*?)</p>', html, re.DOTALL)
    if not m:
        return ""
    text = re.sub(r'<[^>]+>', ' ', m.group(1))
    return re.sub(r'\s+', ' ', text).strip()


def classify_urls(urls: list[str]) -> dict[str, list[str]]:
    """Group URLs by host."""
    out: dict[str, list[str]] = {}
    for u in urls:
        host = re.match(r'https://([^/]+)/', u).group(1).lower().replace('www.','')
        out.setdefault(host, []).append(u)
    return out


def main() -> int:
    kb = json.loads(KB_PATH.read_text())
    e = kb["entries"]
    corpus = [p for p in e if strict_inscope(p) and p.get('pdf_verification', {}).get('confidence') == 'high']
    print(f"Processing {len(corpus)} papers...", file=sys.stderr)

    results = []
    for i, p in enumerate(corpus):
        doi = p["paper_doi"]
        doi_short = doi.replace("10.1038/", "")
        url = f"https://www.nature.com/articles/{doi_short}"
        print(f"  {i+1}/{len(corpus)} {p['id']}: {p['paper_title'][:50]}...", file=sys.stderr)

        html = fetch_html(url)
        if len(html) < 5000:
            results.append({
                "id": p["id"], "doi": doi, "title": p["paper_title"],
                "fetch_status": "failed_or_too_small",
                "html_bytes": len(html),
                "code_section": "",
                "data_section": "",
                "urls_by_host": {},
                "all_urls": [],
            })
            continue

        code_section = extract_section(html, "Code availability")
        data_section = extract_section(html, "Data availability")
        code_section = code_section[:1500]
        data_section = data_section[:1500]

        # Extract URLs ONLY from code/data section text. URLs from elsewhere
        # in the HTML (references, related-articles) are noise and lead to
        # false positives where mlgg would attribute cited libraries
        # (e.g., PheWAS/PheWAS, mimic3-benchmarks) as the paper's own code.
        urls_in_code = sorted(set(m.group(0) for m in URL_RE.finditer(code_section)))
        urls_in_data = sorted(set(m.group(0) for m in URL_RE.finditer(data_section)))
        urls_full = sorted(set(urls_in_code + urls_in_data))

        results.append({
            "id": p["id"],
            "doi": doi,
            "title": p["paper_title"],
            "fetch_status": "ok",
            "html_bytes": len(html),
            "code_section": code_section,
            "data_section": data_section,
            "urls_in_code_section": urls_in_code,
            "urls_in_data_section": urls_in_data,
            "urls_by_host": classify_urls(urls_full),
            "all_urls": urls_full,
        })

    # Stats
    ok = [r for r in results if r["fetch_status"] == "ok"]
    has_github = sum(1 for r in ok if any('github.com' in u for u in r["all_urls"]))
    has_zenodo = sum(1 for r in ok if any('zenodo.org' in u for u in r["all_urls"]))
    has_any_code = sum(1 for r in ok if any(re.search(r'github|gitlab|zenodo|figshare|osf|codeocean|bitbucket', u) for u in r["all_urls"]))
    has_code_section = sum(1 for r in ok if r["code_section"])

    print("\nDone. Stats:")
    print(f"  Total processed: {len(results)}")
    print(f"  Successful fetch: {len(ok)}")
    print(f"  Has GitHub link: {has_github}")
    print(f"  Has Zenodo link: {has_zenodo}")
    print(f"  Has any code/data hosting link: {has_any_code}")
    print(f"  Has Code availability section text: {has_code_section}")

    # Write outputs
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_size": len(corpus),
        "stats": {
            "fetch_ok": len(ok),
            "has_github": has_github,
            "has_zenodo": has_zenodo,
            "has_any_code_host": has_any_code,
            "has_code_availability_section": has_code_section,
        },
        "results": results,
    }, indent=2, ensure_ascii=False))

    md = [
        f"# Code repositories for verified-cohort corpus (N={len(corpus)})",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| ID | Title | GitHub | Zenodo | Other | Code section |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        gh = ", ".join([u for u in r["all_urls"] if 'github.com' in u][:2])[:80] or "—"
        zn = ", ".join([u for u in r["all_urls"] if 'zenodo.org' in u][:2])[:80] or "—"
        other = ", ".join([u for u in r["all_urls"] if not any(h in u for h in ['github.com','zenodo.org'])][:2])[:60] or "—"
        has_sec = "✓" if r["code_section"] else "—"
        title = r["title"][:50].replace("|"," ")
        md.append(f"| {r['id']} | {title} | {gh} | {zn} | {other} | {has_sec} |")
    md.append("")
    OUT_MD.write_text("\n".join(md))
    print("\nReports:")
    print(f"  {OUT_JSON.relative_to(ROOT)}")
    print(f"  {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
