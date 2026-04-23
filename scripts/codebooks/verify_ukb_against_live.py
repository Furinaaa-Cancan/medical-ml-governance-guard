#!/usr/bin/env python3
"""L4 — external authority cross-check.

Our L1/L2/L3 verify the local SQLite + .txt files are self-consistent.
This script goes further: fetches UKB's live public pages and compares
with our DB to catch any drift between what we ingested and what UKB
now publishes.

Two levels of check:

  1. Schema drift: re-download all 11 Showcase .txt files, compare
     sha256 to our committed source_manifest.json. Detects upstream
     UKB releases since our last fetch.

  2. Field-page cross-check: fetch UKB's field.cgi?id=<fid> for a
     sample of golden-seed field_ids, parse the Description and
     Category rows from the HTML, compare to our DB. Detects any
     build-time metadata loss (title truncation, category-id
     confusion, hierarchy corruption).

Network-bound — not run by default tests. Operator runs this before
publication-grade claims or when they suspect drift.

Usage:
  python3 scripts/codebooks/verify_ukb_against_live.py
  python3 scripts/codebooks/verify_ukb_against_live.py --probes 50
  python3 scripts/codebooks/verify_ukb_against_live.py --schema-only
  python3 scripts/codebooks/verify_ukb_against_live.py --field-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UKB_DIR = REPO_ROOT / "references" / "codebooks" / "ukb"
DEFAULT_DB = UKB_DIR / "ukb_codebook.sqlite"
DEFAULT_MANIFEST = UKB_DIR / "source_manifest.json"

BASE_URL = "https://biobank.ndph.ox.ac.uk/ukb"
SCHEMAS = {
    1:  "field.txt",        2:  "encoding.txt",
    3:  "category.txt",     5:  "esimpint.txt",
    6:  "esimpstring.txt",  7:  "esimpreal.txt",
    8:  "esimpdate.txt",    9:  "insvalue.txt",
    11: "ehierint.txt",     12: "ehierstring.txt",
    13: "catbrowse.txt",
}

# Encodings to cross-check row counts against UKB's `codown.cgi` dump.
# Covers the three big clinical code systems (ICD-10, ICD-9, OPCS-4)
# plus two tiny sanity checks (Sex, Pass/Fail) to detect total ingest
# failure even when a large system happens to round-match.
LIVE_ENCODING_PROBES = [19, 87, 240, 9, 100]

# Golden-seed fields used for live cross-check. Mix of baseline,
# biochem, PHI, first-occurrence, and imaging to catch category-
# specific regressions.
DEFAULT_PROBE_FIELDS = [
    # Demographics (cat 100094)
    31, 33, 34, 52,
    # Anthropometry / blood pressure
    21001, 21002, 4080, 4079, 50,
    # Serum biochem
    30750, 30740, 30690, 30760, 30780, 30870, 30700,
    # Nightingale NMR
    23439, 23440, 23480,
    # Visit / lifestyle
    21003, 1558, 20160,
    # Algorithmic outcomes
    42000, 42006, 42008,
    # First-occurrence
    131286, 131298, 131494, 131350, 132032,
    # Home location PHI
    20074, 22704,
    # Death / cancer registry
    40000, 40005,
    # Cognitive
    20191,
    # Activity
    22037,
]


def _http(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": "mlgg-ukb-audit/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_schema_drift(manifest_path: Path) -> List[str]:
    """Re-download every .txt file from UKB and diff sha256."""
    issues = []
    if not manifest_path.exists():
        return [f"manifest missing at {manifest_path}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print("\n── Schema drift check (live UKB Showcase vs local manifest) ──")
    print(f"{'file':<22} {'local bytes':>13} {'live bytes':>13} {'match':>8}")
    for sid, fname in sorted(SCHEMAS.items()):
        url = f"{BASE_URL}/scdown.cgi?fmt=txt&id={sid}"
        try:
            data = _http(url, timeout=60)
        except (URLError, HTTPError, TimeoutError) as exc:
            issues.append(f"{fname}: fetch failed ({exc})")
            print(f"{fname:<22} FAIL: {exc}")
            continue
        live_sha = hashlib.sha256(data).hexdigest()
        local = manifest.get("files", {}).get(fname, {})
        local_sha = local.get("sha256", "")
        local_bytes = local.get("bytes", 0)
        match = live_sha == local_sha
        if not match:
            issues.append(f"{fname}: sha drift "
                          f"({local_sha[:16]} local vs {live_sha[:16]} live)")
        print(f"{fname:<22} {local_bytes:>13,} {len(data):>13,} "
              f"{'match' if match else 'DRIFT':>8}")
        time.sleep(0.4)
    return issues


_DESC_RE = re.compile(r"<tr><td>Description:</td><td>([^<]+)</td>")
_CAT_ROW_RE = re.compile(r"<tr><td>Category:</td><td>(.*?)</td></tr>", re.DOTALL)
_CAT_ID_RE = re.compile(r"label\.cgi\?id=(\d+)")


def fetch_field_meta(fid: int, timeout: int = 30) -> Tuple[str, Optional[int]]:
    url = f"{BASE_URL}/field.cgi?id={fid}"
    html = _http(url, timeout=timeout).decode("utf-8", errors="replace")
    title_m = _DESC_RE.search(html)
    title = title_m.group(1).strip() if title_m else ""
    cat_row = _CAT_ROW_RE.search(html)
    cat_id = None
    if cat_row:
        ids = _CAT_ID_RE.findall(cat_row.group(1))
        if ids:
            cat_id = int(ids[-1])  # most specific = last on the path
    return title, cat_id


def check_encoding_counts(
    conn: sqlite3.Connection, encodings: List[int], pause: float = 0.4,
) -> List[str]:
    """For each encoding, fetch UKB's codown.cgi and diff row count."""
    issues = []
    print(f"\n── Encoding row-count cross-check ({len(encodings)} encodings) ──")
    print(f"{'enc':>6}  {'title':<30} {'live':>8} {'db':>8}  {'OK':>3}")
    for enc_id in encodings:
        url = f"{BASE_URL}/codown.cgi?id={enc_id}"
        try:
            data = _http(url, timeout=90).decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as exc:
            issues.append(f"encoding {enc_id}: fetch failed ({exc})")
            continue
        # UKB codown.cgi returns TSV with header; non-empty data lines
        # are the actual rows. Skip blank lines and comments defensively.
        live_rows = [l for l in data.splitlines() if l.strip() and not l.startswith("#")]
        live_count = max(0, len(live_rows) - 1)  # minus header
        row = conn.execute(
            "SELECT e.title, (SELECT COUNT(*) FROM encoding_values ev WHERE ev.encoding_id=e.encoding_id) "
            "FROM encodings e WHERE e.encoding_id=?", (enc_id,),
        ).fetchone()
        if row is None:
            issues.append(f"encoding {enc_id}: not in local DB")
            continue
        title, db_count = row
        ok = live_count == db_count
        if not ok:
            issues.append(f"encoding {enc_id} ({title}): live={live_count} db={db_count}")
        print(f"{enc_id:>6}  {(title or '')[:30]:<30} {live_count:>8} {db_count:>8}  "
              f"{'✓' if ok else '✗':>3}")
        time.sleep(pause)
    return issues


def check_field_pages(
    conn: sqlite3.Connection, probes: List[int], pause: float = 0.4,
) -> List[str]:
    issues = []
    print(f"\n── Field-page cross-check ({len(probes)} fields) ──")
    print(f"{'fid':>7}  {'OK':>3}  live title [cat]")
    ok = 0
    for fid in probes:
        try:
            live_title, live_cat = fetch_field_meta(fid)
        except (URLError, HTTPError, TimeoutError) as exc:
            issues.append(f"field {fid}: fetch failed ({exc})")
            continue
        row = conn.execute(
            "SELECT title, main_category FROM fields WHERE field_id=?", (fid,),
        ).fetchone()
        if row is None:
            issues.append(f"field {fid}: not in local DB (live says '{live_title}')")
            print(f"{fid:>7}  {'?':>3}  NOT IN LOCAL DB")
            continue
        local_title, local_cat = row
        title_ok = live_title == local_title
        cat_ok = live_cat is None or live_cat == local_cat
        if title_ok and cat_ok:
            ok += 1
            print(f"{fid:>7}  {'✓':>3}  {live_title[:45]} [{live_cat}]")
        else:
            flags = []
            if not title_ok:
                flags.append(f"title: '{live_title}' vs '{local_title}'")
            if not cat_ok:
                flags.append(f"cat: {live_cat} vs {local_cat}")
            msg = f"field {fid}: " + "; ".join(flags)
            issues.append(msg)
            print(f"{fid:>7}  {'✗':>3}  {live_title[:45]} [{live_cat}]  "
                  f"(local: '{local_title[:30]}' cat={local_cat})")
        time.sleep(pause)
    print(f"\n  → {ok}/{len(probes)} exact match")
    return issues


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--schema-only", action="store_true",
                   help="Skip field-page and encoding-count cross-check (schema drift only).")
    p.add_argument("--field-only", action="store_true",
                   help="Skip schema and encoding checks (field-page only).")
    p.add_argument("--skip-encodings", action="store_true",
                   help="Skip encoding row-count cross-check.")
    p.add_argument("--probes", type=int, default=0,
                   help="Number of RANDOM additional fields to probe beyond "
                        "the golden-seed defaults.")
    p.add_argument("--seed", type=int, default=42,
                   help="RNG seed for --probes random selection.")
    p.add_argument("--pause", type=float, default=0.4,
                   help="Sleep between requests (polite to UKB).")
    args = p.parse_args()

    if not args.db.exists():
        print(f"ERROR: {args.db} missing", file=sys.stderr)
        return 2

    all_issues: List[str] = []

    if not args.field_only:
        all_issues.extend(check_schema_drift(args.manifest))

    if not args.schema_only and not args.field_only and not args.skip_encodings:
        with sqlite3.connect(str(args.db)) as conn:
            all_issues.extend(check_encoding_counts(
                conn, LIVE_ENCODING_PROBES, args.pause,
            ))

    if not args.schema_only:
        probes = list(DEFAULT_PROBE_FIELDS)
        if args.probes > 0:
            conn = sqlite3.connect(str(args.db))
            all_fids = [r[0] for r in conn.execute(
                "SELECT field_id FROM fields WHERE field_id NOT IN "
                "(SELECT value FROM json_each(?)) "
                "AND main_category NOT IN (1000)",  # skip EMBARGOED placeholder
                (json.dumps(DEFAULT_PROBE_FIELDS),),
            )]
            conn.close()
            rng = random.Random(args.seed)
            extra = rng.sample(all_fids, min(args.probes, len(all_fids)))
            probes = DEFAULT_PROBE_FIELDS + extra
        with sqlite3.connect(str(args.db)) as conn:
            all_issues.extend(check_field_pages(conn, probes, args.pause))

    print(f"\n{'='*60}")
    if all_issues:
        print(f"❌ {len(all_issues)} issue(s):")
        for i in all_issues:
            print(f"  - {i}")
        return 2
    print("✅ Live UKB Showcase cross-check clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
