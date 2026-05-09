#!/usr/bin/env python3
"""Download peer review PDFs for KB entries that have no peer_review_pdf_path yet.

Reads:
  references/case-studies/peer-review-kb.json (entries without PDF)

Per missing entry:
  1. Fetch Nature article page (with on-disk HTML cache + UA + retry)
  2. Locate the supplementary URL labelled "peer review file"
     (matches anchor tag with data-track-label="peer review file")
  3. Download that PDF to nature_communications/<paper_id>_peer_review.pdf
  4. Verify file is a valid PDF (magic bytes %PDF-)

Does NOT extract text. Does NOT update the KB. Does NOT run lint.
Just downloads PDFs.

Usage:
  python3 scripts/diagnostics/download_missing_pdfs.py            # dry-run
  python3 scripts/diagnostics/download_missing_pdfs.py --apply    # actually download
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
PDF_DIR = ROOT / "references" / "case-studies" / "nature_communications"
HTML_CACHE = ROOT / ".cache" / "nature_html"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"


def fetch_html(url: str) -> str:
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    cf = HTML_CACHE / f"{key}.html"
    if cf.exists() and cf.stat().st_size > 50000:
        return cf.read_text()
    for attempt in range(3):
        try:
            r = subprocess.run(["curl","-sSL","-A",UA,url],
                              capture_output=True, text=True, timeout=30)
            if len(r.stdout) > 50000:
                cf.write_text(r.stdout)
                time.sleep(2)
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5*(attempt+1))
    return ""


def find_peer_review_url(html: str) -> str | None:
    """Find the Nature 'Peer Review File' supplementary URL.

    Anchor tag pattern:
        <a class="..." data-track-label="peer review file" href="https://static-content..."
    """
    # Primary: data-track-label
    m = re.search(r'data-track-label="peer review file"\s+href="([^"]+)"', html, re.I)
    if m:
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://www.nature.com" + url
        return url
    # Alt: scan all MOESM URLs and find the one preceded/followed by "peer review"
    for m in re.finditer(r'(https://static-content\.springer\.com/[^"\s]+MOESM[^"\s]+\.pdf)', html):
        url = m.group(1)
        # context window 200 chars before and after
        idx = m.start()
        before = html[max(0, idx-200):idx]
        after = html[m.end():m.end()+300]
        if re.search(r'peer review', before+after, re.I):
            return url
    return None


def slugify(title: str, max_len: int = 40) -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '_', title.lower()).strip('_')
    return s[:max_len]


def download_pdf(url: str, dest: Path, timeout: int = 60) -> tuple[bool, str]:
    if dest.exists() and dest.stat().st_size > 10000:
        # check magic bytes
        with open(dest, "rb") as f:
            head = f.read(8)
        if head.startswith(b"%PDF-"):
            return True, "already_present_valid"
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
            # File downloaded but not a PDF (Cloudflare HTML challenge etc.)
            preview = head[:200] if len(head) >= 200 else head
            dest.unlink()
            return False, f"not_pdf: {preview!r}"
        size_kb = dest.stat().st_size // 1024
        return True, f"downloaded_{size_kb}kb"
    except subprocess.TimeoutExpired:
        return False, "download_timeout"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually download files (default dry-run)")
    args = ap.parse_args()

    kb = json.loads(KB_PATH.read_text())
    missing = [e for e in kb['entries'] if not e.get('peer_review_pdf_path')]
    print(f"Missing PDF for {len(missing)} entries\n")

    results = []
    for i, e in enumerate(missing, 1):
        eid = e['id']
        doi = e['paper_doi']
        doi_short = doi.replace("10.1038/", "")
        url = f"https://www.nature.com/articles/{doi_short}"
        slug = slugify(e['paper_title'])
        target = PDF_DIR / f"{eid}_{slug}_peer_review.pdf"

        print(f"[{i}/{len(missing)}] {eid} {doi}")
        html = fetch_html(url)
        if len(html) < 50000:
            print(f"  ✗ article page fetch failed ({len(html)} bytes)")
            results.append({"id": eid, "status": "fetch_failed", "url": url})
            continue

        pr_url = find_peer_review_url(html)
        if not pr_url:
            print(f"  ✗ no Peer Review File link found in article page")
            results.append({"id": eid, "status": "no_peer_review_link", "url": url})
            continue

        if not args.apply:
            print(f"  → would download: {pr_url[:90]}")
            print(f"     to: {target.relative_to(ROOT)}")
            results.append({"id": eid, "status": "dryrun", "pr_url": pr_url,
                          "target": str(target.relative_to(ROOT))})
            continue

        ok, msg = download_pdf(pr_url, target)
        status = "✓ " + msg if ok else "✗ " + msg
        print(f"  {status}")
        results.append({"id": eid, "status": "ok" if ok else "failed",
                       "pr_url": pr_url, "target": str(target.relative_to(ROOT)),
                       "msg": msg})

    # Stats
    ok_n = sum(1 for r in results if r['status'] == 'ok')
    drylinks = sum(1 for r in results if r['status'] == 'dryrun')
    no_link = sum(1 for r in results if r['status'] == 'no_peer_review_link')
    fetch_fail = sum(1 for r in results if r['status'] == 'fetch_failed')
    fail = sum(1 for r in results if r['status'] == 'failed')

    print(f"\n=== Summary ===")
    print(f"  Total entries to download: {len(missing)}")
    if not args.apply:
        print(f"  Peer review URL found: {drylinks}")
    else:
        print(f"  Successfully downloaded: {ok_n}")
        print(f"  Download failed: {fail}")
    print(f"  No peer review link in article: {no_link}")
    print(f"  Article page fetch failed: {fetch_fail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
