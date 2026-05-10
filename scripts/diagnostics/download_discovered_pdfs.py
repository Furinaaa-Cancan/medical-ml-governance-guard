#!/usr/bin/env python3
"""Download peer review PDFs for candidates from discover_corpus.py.

Reads:
  paper/discovery-candidates.json (614 candidates from 3 journals)

Per candidate:
  1. Fetch article page (cached HTML in .cache/nature_html/)
  2. Locate peer review file via data-track-label="peer review file"
  3. Download PDF to references/case-studies/<journal_dir>/
  4. Verify %PDF- magic; drop invalids
  5. Track status (downloaded / no_pr_link / fetch_failed / opt_out)

Rate-limited: 2s sleep between fetches, exponential backoff on retries.
Resumable: skips already-downloaded files.

Naming: PDFs saved as <doi_short>_peer_review.pdf
        e.g., s41746-024-01234-5_peer_review.pdf

Writes:
  paper/expanded-corpus-status.json — per-DOI status report
  References to successfully-downloaded PDFs (will be linked to KB later)

Usage:
  python3 scripts/diagnostics/download_discovered_pdfs.py [--limit N]
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CAND_JSON = ROOT / "paper" / "discovery-candidates.json"
STATUS_JSON = ROOT / "paper" / "expanded-corpus-status.json"
HTML_CACHE = ROOT / ".cache" / "nature_html"

# Per-journal target dir
JOURNAL_DIRS = {
    "Nature Communications":   ROOT / "references" / "case-studies" / "nature_communications",
    "npj Digital Medicine":    ROOT / "references" / "case-studies" / "npj_digital_medicine",
    "Communications Medicine": ROOT / "references" / "case-studies" / "communications_medicine",
}

# DOI-based URL prefix for each journal (Nature Communications uses
# nature.com/articles/<doi_short>; npjDM and CommMed use the same pattern
# since all three are Springer Nature journals).
def article_url(doi: str) -> str:
    short = doi.replace("10.1038/", "")
    return f"https://www.nature.com/articles/{short}"


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"


def fetch_html(url: str, cache_only: bool = False) -> str:
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    cf = HTML_CACHE / f"{key}.html"
    if cf.exists() and cf.stat().st_size > 50000:
        return cf.read_text()
    if cache_only:
        return ""
    for attempt in range(3):
        try:
            r = subprocess.run(["curl","-sSL","-A",UA,url],
                              capture_output=True, text=True, timeout=30)
            if len(r.stdout) > 50000:
                cf.write_text(r.stdout)
                time.sleep(2)  # polite to Nature
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5*(attempt+1))
    return ""


def find_peer_review_url(html: str) -> str | None:
    m = re.search(r'data-track-label="peer review file"\s+href="([^"]+)"', html, re.I)
    if m:
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://www.nature.com" + url
        return url
    # Alt: any MOESM URL near "peer review" text
    for m in re.finditer(r'(https://static-content\.springer\.com/[^"\s]+MOESM[^"\s]+\.pdf)', html):
        url = m.group(1)
        idx = m.start()
        ctx = html[max(0,idx-200):m.end()+300].lower()
        if 'peer review' in ctx:
            return url
    return None


def download_pdf(url: str, dest: Path, timeout: int = 60) -> tuple[bool, str]:
    if dest.exists() and dest.stat().st_size > 10000:
        with open(dest, "rb") as f:
            head = f.read(8)
        if head.startswith(b"%PDF-"):
            return True, "already_present"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["curl","-sSL","-A",UA,url,"-o",str(dest)],
                          capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return False, f"curl_failed: {r.stderr.strip()[:120]}"
        if not dest.exists():
            return False, "no_output_file"
        with open(dest, "rb") as f:
            head = f.read(8)
        if not head.startswith(b"%PDF-"):
            dest.unlink()
            return False, "not_pdf_html_challenge"
        size_kb = dest.stat().st_size // 1024
        return True, f"downloaded_{size_kb}kb"
    except subprocess.TimeoutExpired:
        return False, "download_timeout"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                   help="Only process first N candidates (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cands = json.loads(CAND_JSON.read_text())["candidates"]
    if args.limit:
        cands = cands[:args.limit]
    print(f"Processing {len(cands)} candidates...", file=sys.stderr)

    results = []
    for i, c in enumerate(cands, 1):
        doi = c["doi"]
        journal = c["journal"]
        target_dir = JOURNAL_DIRS.get(journal)
        if not target_dir:
            results.append({"doi": doi, "journal": journal, "status": "unknown_journal"})
            continue
        doi_short = doi.replace("10.1038/", "")
        target = target_dir / f"{doi_short}_peer_review.pdf"

        # Already downloaded? Skip
        if target.exists() and target.stat().st_size > 10000:
            with open(target,'rb') as f: head=f.read(8)
            if head.startswith(b"%PDF-"):
                results.append({"doi":doi,"journal":journal,"status":"already_downloaded",
                              "pdf_path":str(target.relative_to(ROOT))})
                if i % 50 == 0:
                    print(f"  [{i}/{len(cands)}] {journal[:20]} ✓ already", file=sys.stderr)
                continue

        if i % 25 == 0 or args.limit:
            print(f"  [{i}/{len(cands)}] {journal[:20]} {doi_short[:25]}", file=sys.stderr)

        # Fetch article page
        url = article_url(doi)
        html = fetch_html(url)
        if len(html) < 50000:
            results.append({"doi":doi,"journal":journal,"status":"article_fetch_failed"})
            continue

        # Find peer review URL
        pr_url = find_peer_review_url(html)
        if not pr_url:
            results.append({"doi":doi,"journal":journal,"status":"no_peer_review_file"})
            continue

        if args.dry_run:
            results.append({"doi":doi,"journal":journal,"status":"dryrun_would_download",
                          "pr_url":pr_url})
            continue

        # Download
        ok, msg = download_pdf(pr_url, target)
        results.append({
            "doi": doi, "journal": journal,
            "status": "downloaded" if ok else "download_failed",
            "msg": msg,
            "pr_url": pr_url,
            "pdf_path": str(target.relative_to(ROOT)) if ok else None,
        })

    # Summarize
    from collections import Counter
    statuses = Counter(r["status"] for r in results)
    by_journal_status = {}
    for r in results:
        key = (r["journal"], r["status"])
        by_journal_status[key] = by_journal_status.get(key, 0) + 1

    print(f"\n=== Status counts ===")
    for s, n in statuses.most_common():
        print(f"  {s}: {n}")

    print(f"\n=== By journal ===")
    journals = sorted(set(r["journal"] for r in results))
    for j in journals:
        statuses_j = {s: by_journal_status.get((j,s),0)
                     for s in ['downloaded','already_downloaded','no_peer_review_file','article_fetch_failed','download_failed']}
        total_j = sum(statuses_j.values())
        success = statuses_j['downloaded'] + statuses_j['already_downloaded']
        print(f"  {j}: total={total_j} success={success}/{total_j}={success/max(total_j,1)*100:.0f}%")
        for s, n in statuses_j.items():
            if n: print(f"    {s}: {n}")

    STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidates_processed": len(cands),
        "status_counts": dict(statuses),
        "results": results,
    }, indent=2, ensure_ascii=False))
    print(f"\n  Output: {STATUS_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
