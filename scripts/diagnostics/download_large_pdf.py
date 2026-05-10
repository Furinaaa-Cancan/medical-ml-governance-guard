#!/usr/bin/env python3
"""Download a large peer-review PDF from Nature's static-content CDN.

Why this exists
---------------
For papers in Nature portfolio journals (Communications Medicine, etc.) the
peer-review file is hosted at ``static-content.springer.com``. Most files are
small enough that a single ``curl`` call works, but a handful of files >8 MB
are consistently truncated when downloaded directly to slow disks (e.g. a
USB-attached external drive). The HTTP/2 stream from the upstream Google
Cloud Storage origin is closed early or partially written before the disk
catches up, leaving a partial PDF that fails ``pypdf`` parsing with::

    Stream has ended unexpectedly

Headers from the CDN show ``accept-ranges: bytes`` is supported, so the fix
is to use ``wget -c`` (resume) into ``/tmp`` (fast local disk) and then move
the validated file to its final destination on the slow disk.

Strategy
--------
1. Resolve the article page ``https://www.nature.com/articles/<doi-shorthand>``
2. Parse out the ``data-track-label="peer review file"`` href (the
   ``MOESMxx_ESM.pdf`` URL on ``static-content.springer.com``).
3. ``wget -c`` into ``/tmp`` with retries and resume (Range requests).
4. Verify magic bytes (``%PDF-``), full Content-Length, and pypdf page count.
5. Move atomically to the destination on the (potentially slow) target disk.

Usage
-----
::

    python3 scripts/diagnostics/download_large_pdf.py \
        --doi 10.1038/s43856-024-00464-4 \
        --dest references/case-studies/communications_medicine/s43856-024-00464-4_peer_review.pdf

The script is idempotent: if ``--dest`` already contains a valid PDF
matching the upstream ``Content-Length``, it exits 0 without redownloading.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ARTICLE_TPL = "https://www.nature.com/articles/{slug}"


def _doi_to_slug(doi: str) -> str:
    """``10.1038/s43856-024-00464-4`` -> ``s43856-024-00464-4``."""
    return doi.split("/", 1)[-1] if "/" in doi else doi


def _fetch_article_html(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_peer_review_url(html: str) -> Optional[str]:
    """Extract the ``data-track-label='peer review file'`` href, if present."""
    m = re.search(
        r'data-track-label="peer review file"\s+href="([^"]+)"', html, re.I
    )
    if m:
        return m.group(1)
    # Fallback: look for any MOESM URL near the phrase "peer review"
    for m in re.finditer(
        r'(https://static-content\.springer\.com/[^"\s]+MOESM[^"\s]+\.pdf)',
        html,
    ):
        url = m.group(1)
        ctx = html[max(0, m.start() - 200) : m.end() + 200]
        if re.search(r"peer review", ctx, re.I):
            return url
    return None


def remote_content_length(url: str, timeout: int = 30) -> Optional[int]:
    """HEAD the URL and return Content-Length, or ``None`` if unavailable."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:
        return None


def _is_valid_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    with open(path, "rb") as f:
        head = f.read(8)
    return head.startswith(b"%PDF-")


def _pypdf_pages(path: Path) -> Optional[int]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def wget_resume(
    url: str,
    dest: Path,
    *,
    tries: int = 5,
    timeout: int = 180,
    waitretry: int = 5,
) -> tuple[bool, str]:
    """``wget -c`` with retries. Resumes via Range requests on partial data.

    Returns (ok, message). ok=True iff wget exited 0 *and* the file ends up
    on disk with magic bytes ``%PDF-``.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget",
        "-c",  # resume partial downloads
        f"--tries={tries}",
        f"--timeout={timeout}",
        f"--waitretry={waitretry}",
        "--retry-connrefused",
        "-U",
        UA,
        "-O",
        str(dest),
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "wget_not_installed"
    if proc.returncode != 0:
        return False, f"wget_failed_rc{proc.returncode}: {proc.stderr.strip()[-200:]}"
    if not _is_valid_pdf(dest):
        return False, "not_a_pdf_after_download"
    return True, f"downloaded_{dest.stat().st_size}b"


def download_to_dest(
    doi: str,
    dest: Path,
    *,
    pr_url: Optional[str] = None,
    tmp_dir: Path = Path("/tmp"),
    force: bool = False,
) -> dict:
    """Download the peer-review PDF for ``doi`` to ``dest``.

    Returns a result dict with at least:

    * ``status`` -- one of ``already_present``, ``downloaded``,
      ``no_peer_review_file``, ``download_failed``, ``invalid_pdf``.
    * ``pr_url`` -- the resolved peer-review URL (if any).
    * ``size_bytes`` -- size on disk if successful.
    * ``page_count`` -- pypdf page count if pypdf is available.
    """
    out: dict = {"doi": doi, "dest": str(dest), "status": None, "pr_url": pr_url}

    # Resolve URL via the article page (cached if caller passed one).
    if not pr_url:
        slug = _doi_to_slug(doi)
        article_url = ARTICLE_TPL.format(slug=slug)
        out["article_url"] = article_url
        try:
            html = _fetch_article_html(article_url)
        except Exception as exc:
            out["status"] = "article_fetch_failed"
            out["error"] = str(exc)
            return out
        pr_url = find_peer_review_url(html)
        if not pr_url:
            out["status"] = "no_peer_review_file"
            return out
        out["pr_url"] = pr_url

    expected_size = remote_content_length(pr_url)
    out["expected_size"] = expected_size

    # Idempotent skip: dest already valid and matches expected size.
    if (
        not force
        and dest.exists()
        and _is_valid_pdf(dest)
        and (expected_size is None or dest.stat().st_size == expected_size)
    ):
        out["status"] = "already_present"
        out["size_bytes"] = dest.stat().st_size
        out["page_count"] = _pypdf_pages(dest)
        return out

    # Download to /tmp first (fast local disk), then atomically move.
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{_doi_to_slug(doi)}_peer_review.pdf"

    # If a previous partial sits in /tmp, wget -c will resume it.
    ok, msg = wget_resume(pr_url, tmp_path)
    out["wget_msg"] = msg
    if not ok:
        out["status"] = "download_failed"
        return out

    actual_size = tmp_path.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        out["status"] = "size_mismatch"
        out["size_bytes"] = actual_size
        return out

    pages = _pypdf_pages(tmp_path)
    if pages is None or pages < 1:
        out["status"] = "invalid_pdf"
        out["size_bytes"] = actual_size
        return out

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_path), str(dest))

    out["status"] = "downloaded"
    out["size_bytes"] = dest.stat().st_size
    out["page_count"] = pages
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--doi",
        required=True,
        help="Springer Nature DOI, e.g. 10.1038/s43856-024-00464-4",
    )
    ap.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="Destination path for the peer-review PDF",
    )
    ap.add_argument(
        "--pr-url",
        default=None,
        help="Optional explicit peer-review PDF URL (skip article-page lookup)",
    )
    ap.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("/tmp"),
        help="Local fast-disk staging dir (default /tmp)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Redownload even if dest already looks valid",
    )
    args = ap.parse_args()

    res = download_to_dest(
        args.doi,
        args.dest,
        pr_url=args.pr_url,
        tmp_dir=args.tmp_dir,
        force=args.force,
    )

    import json as _json

    print(_json.dumps(res, indent=2))
    ok_states = {"already_present", "downloaded"}
    return 0 if res.get("status") in ok_states else 2


if __name__ == "__main__":
    sys.exit(main())
