#!/usr/bin/env python3
"""For each PR-EXP cohort-retrospective-binary KB entry, find its primary code repo.

Reuses the proven extraction logic from find_code_repos.py (regex anchored on the
"Code availability" heading + curl-with-cache fetcher).  Differences:

  - Corpus is the 125 ``is_cohort_retrospective_binary == true`` PR-EXP-* entries
    (full set, not the strict-inscope subset used by find_code_repos.py).
  - Output path: paper/code-repos-cohort-binary.{json,md}.
  - Picks one ``primary_repo`` per paper using a host-priority + path-depth rule
    (see PRIMARY_HOST_RANK).  Records ``primary_repo_method`` for transparency.
  - Code section paragraph is capped at 600 chars (per task spec).

Usage::

    python scripts/diagnostics/find_code_repos_cohort_binary.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
OUT_JSON = ROOT / "paper" / "code-repos-cohort-binary.json"
OUT_MD = ROOT / "paper" / "code-repos-cohort-binary.md"
CACHE_DIR = ROOT / ".cache" / "nature_html"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "Version/17.0 Safari/605.1.15"
)

URL_RE = re.compile(
    r"https?://(?:"
    r"github\.com|gitlab\.com|zenodo\.org|figshare\.com|osf\.io|codeocean\.com|"
    r"bitbucket\.org|huggingface\.co|data\.mendeley\.com|"
    # DOI form: zenodo (5281), codeocean (24433), figshare (6084), OSF (17605),
    # mendeley data (17632)
    r"(?:dx\.)?doi\.org/10\.(?:5281|24433|6084|17605|17632)/"
    r")[A-Za-z0-9\-_./?=&%~+#]+",
    re.I,
)

# Bare hostname pattern (no protocol).  Matches things like
# ``github.com/user/repo`` and ``zenodo.org/record/12345`` that appear inline in
# author-written paragraphs without an https:// prefix.
BARE_URL_RE = re.compile(
    r"(?<![A-Za-z0-9/.-])"  # left boundary: not part of an existing URL
    r"(?:"
    r"github\.com|gitlab\.com|zenodo\.org|figshare\.com|osf\.io|codeocean\.com|"
    r"bitbucket\.org"
    r")/[A-Za-z0-9\-_./?=&%~+#]+",
    re.I,
)

# Higher rank = preferred as primary.
PRIMARY_HOST_RANK: dict[str, int] = {
    "github.com": 100,
    "gitlab.com": 90,
    "bitbucket.org": 85,
    "zenodo.org": 70,
    "doi.org/10.5281": 70,  # zenodo via DOI
    "codeocean.com": 60,
    "doi.org/10.24433": 60,  # codeocean via DOI
    "figshare.com": 50,
    "doi.org/10.6084": 50,  # figshare via DOI
    "osf.io": 40,
    "doi.org/10.17605": 40,  # OSF via DOI
    "data.mendeley.com": 35,
    "doi.org/10.17632": 35,  # Mendeley Data via DOI
    "huggingface.co": 30,
}


def fetch_html(url: str) -> str:
    """Fetch with on-disk cache + retry.  Polite 2 s sleep between fresh GETs."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.html"
    if cache_file.exists() and cache_file.stat().st_size > 50000:
        return cache_file.read_text()
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["curl", "-sSL", "-A", UA, url],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if len(r.stdout) > 50000:
                cache_file.write_text(r.stdout)
                time.sleep(2)  # polite delay only on fresh fetches
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5 * (attempt + 1))
    return ""


def extract_section(html: str, heading: str) -> tuple[str, str]:
    """Return (raw_html, plain_text) of first <p> after the given section heading."""
    m = re.search(
        rf"(?i)(?:>|\b){heading}[<>:][^<]{{0,50}}.*?<p[^>]*>(.*?)</p>",
        html,
        re.DOTALL,
    )
    if not m:
        return "", ""
    raw_html = m.group(1)
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return raw_html, re.sub(r"\s+", " ", text).strip()


def extract_urls_with_context(raw_html: str) -> list[str]:
    """Extract URLs from a Code-availability paragraph.

    Captures three sources, in order:
      1. https?:// URLs in the paragraph text (URL_RE on stripped text).
      2. Bare hostnames like ``github.com/foo/bar`` (BARE_URL_RE on stripped text).
      3. URLs inside citation tooltip attributes (``title="..."``, ``aria-label``)
         that the paragraph numerically references.  These typically carry the
         Zenodo DOI behind a numbered citation like ``GitHub<sup>31</sup>``.
    """
    urls: list[str] = []
    plain = re.sub(r"<[^>]+>", " ", raw_html)
    plain = re.sub(r"\s+", " ", plain)

    for m in URL_RE.finditer(plain):
        urls.append(m.group(0))

    for m in BARE_URL_RE.finditer(plain):
        u = m.group(0).rstrip(".,;)")
        urls.append("https://" + u)

    # URLs inside citation reference attributes
    for attr in re.findall(r'(?:title|aria-label)="([^"]*)"', raw_html):
        for m in URL_RE.finditer(attr):
            urls.append(m.group(0))

    # Clean HTML-entity cruft (e.g. ``&#xA`` newline entity that appears at
    # the tail of URLs lifted from citation ``title="..."`` attributes) and
    # deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u_clean = re.split(r"&#[xX]?\w+;?", u, maxsplit=1)[0]
        u_clean = u_clean.rstrip(".,;)  ").rstrip("/")
        if not u_clean:
            continue
        if u_clean.lower() in seen:
            continue
        seen.add(u_clean.lower())
        out.append(u_clean)
    return out


def host_key(url: str) -> str:
    """Map URL to a key in PRIMARY_HOST_RANK."""
    m = re.match(r"https?://([^/]+)(/[^?#]*)?", url, re.I)
    if not m:
        return ""
    host = m.group(1).lower().replace("www.", "")
    path = (m.group(2) or "").lower()
    if host in ("doi.org", "dx.doi.org"):
        for prefix in ("/10.5281", "/10.24433", "/10.6084", "/10.17605", "/10.17632"):
            if path.startswith(prefix):
                return f"doi.org{prefix}"
        return "doi.org"
    return host


def pick_primary(urls: list[str]) -> tuple[str | None, str]:
    """Pick the one URL most likely to be *this paper's* code.

    Returns (url_or_none, method_label).  Method labels:
      - auto_github / auto_gitlab / auto_zenodo / auto_codeocean / auto_figshare /
        auto_osf / auto_huggingface
      - manual_review_needed (URLs found but none in our trusted host set)
      - no_public (no URLs found at all)
    """
    if not urls:
        return None, "no_public"
    ranked: list[tuple[int, int, str]] = []
    for u in urls:
        key = host_key(u)
        rank = PRIMARY_HOST_RANK.get(key, 0)
        # Tie-break by path length (longer = more specific = more likely the
        # paper's own repo, not a top-level org page).
        path_len = len(re.sub(r"^https://[^/]+", "", u))
        ranked.append((rank, path_len, u))
    ranked.sort(reverse=True)
    top_rank, _, top_url = ranked[0]
    if top_rank == 0:
        return top_url, "manual_review_needed"
    key = host_key(top_url)
    if "github.com" in key:
        return top_url, "auto_github"
    if "gitlab.com" in key:
        return top_url, "auto_gitlab"
    if "zenodo" in key or key == "doi.org/10.5281":
        return top_url, "auto_zenodo"
    if "codeocean" in key or key == "doi.org/10.24433":
        return top_url, "auto_codeocean"
    if "figshare" in key or key == "doi.org/10.6084":
        return top_url, "auto_figshare"
    if "osf" in key or key == "doi.org/10.17605":
        return top_url, "auto_osf"
    if "huggingface" in key:
        return top_url, "auto_huggingface"
    if "bitbucket" in key:
        return top_url, "auto_bitbucket"
    if "mendeley" in key or key == "doi.org/10.17632":
        return top_url, "auto_mendeley"
    return top_url, "manual_review_needed"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    kb = json.loads(KB_PATH.read_text())
    corpus = [
        e
        for e in kb["entries"]
        if e["id"].startswith("PR-EXP-") and e.get("is_cohort_retrospective_binary") is True
    ]
    print(f"Processing {len(corpus)} cohort-binary papers...", file=sys.stderr)

    results: list[dict[str, Any]] = []
    for i, p in enumerate(corpus):
        doi = p["paper_doi"]
        doi_short = doi.replace("10.1038/", "")
        url = f"https://www.nature.com/articles/{doi_short}"
        title_preview = (p.get("paper_title") or "")[:50]
        print(f"  {i + 1}/{len(corpus)} {p['id']}: {title_preview}...", file=sys.stderr)

        html = fetch_html(url)
        if len(html) < 5000:
            results.append(
                {
                    "id": p["id"],
                    "doi": doi,
                    "journal": p.get("journal"),
                    "year": p.get("year"),
                    "fetch_status": "failed_or_too_small",
                    "primary_repo": None,
                    "primary_repo_method": "fetch_failed",
                    "all_urls_in_section": [],
                    "code_section_first_600_chars": "",
                }
            )
            continue

        raw_html_section, code_section = extract_section(html, "Code availability")
        urls_in_code = extract_urls_with_context(raw_html_section)

        primary, method = pick_primary(urls_in_code)
        if not code_section and not urls_in_code:
            method = "no_public"
            section_snippet = ""
        else:
            section_snippet = code_section[:600]

        results.append(
            {
                "id": p["id"],
                "doi": doi,
                "journal": p.get("journal"),
                "year": p.get("year"),
                "fetch_status": "ok",
                "primary_repo": primary,
                "primary_repo_method": method,
                "all_urls_in_section": urls_in_code,
                "code_section_first_600_chars": section_snippet,
            }
        )

    # Stats over the full corpus
    def has_host(r: dict[str, Any], hosts: tuple[str, ...]) -> bool:
        return any(any(h in u for h in hosts) for u in r["all_urls_in_section"])

    with_github = sum(1 for r in results if has_host(r, ("github.com",)))
    with_zenodo_or_doi = sum(
        1
        for r in results
        if has_host(r, ("zenodo.org", "doi.org/10.5281"))
    )
    with_figshare_or_osf = sum(
        1
        for r in results
        if has_host(
            r, ("figshare.com", "osf.io", "doi.org/10.6084", "doi.org/10.17605")
        )
    )
    with_any_public_code = sum(1 for r in results if r["primary_repo"])
    no_public_repo = sum(
        1 for r in results if r["primary_repo_method"] in ("no_public", "fetch_failed")
    )

    stats = {
        "with_github": with_github,
        "with_zenodo_or_doi": with_zenodo_or_doi,
        "with_figshare_or_osf": with_figshare_or_osf,
        "with_any_public_code": with_any_public_code,
        "no_public_repo": no_public_repo,
    }

    print("\nDone. Stats:", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "corpus_size": len(corpus),
                "stats": stats,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    md = [
        f"# Code repositories for cohort-binary corpus (N={len(corpus)})",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Subset: `is_cohort_retrospective_binary == true` from peer-review-kb.json.",
        "Primary repo picked from URLs found inside the article's "
        "*Code availability* paragraph only (full HTML is excluded to avoid "
        "cited-library false positives).",
        "",
        "## Stats",
        "",
        f"- with_github: **{with_github}** / {len(corpus)}",
        f"- with_zenodo_or_doi: **{with_zenodo_or_doi}** / {len(corpus)}",
        f"- with_figshare_or_osf: **{with_figshare_or_osf}** / {len(corpus)}",
        f"- with_any_public_code: **{with_any_public_code}** / {len(corpus)}",
        f"- no_public_repo: **{no_public_repo}** / {len(corpus)}",
        "",
        "## Results",
        "",
        "| ID | Year | Journal | Method | Primary repo |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        primary = r["primary_repo"] or "—"
        if isinstance(primary, str) and len(primary) > 90:
            primary_disp = primary[:87] + "..."
        else:
            primary_disp = primary
        journal_short = (r.get("journal") or "")[:24]
        md.append(
            f"| {r['id']} | {r.get('year', '')} | {journal_short} | "
            f"{r['primary_repo_method']} | {primary_disp} |"
        )
    md.append("")
    OUT_MD.write_text("\n".join(md))

    print("\nReports written:", file=sys.stderr)
    print(f"  {OUT_JSON.relative_to(ROOT)}", file=sys.stderr)
    print(f"  {OUT_MD.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
