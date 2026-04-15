#!/usr/bin/env python3
"""Download UK Biobank Data Showcase schema files (public, no login required).

Downloads field definitions, encoding dictionaries, category hierarchy, and
instance metadata from the UKB Data Showcase bulk download endpoint.

Produces:
  references/codebooks/ukb/field.txt          (~12K fields)
  references/codebooks/ukb/encoding.txt       (encoding metadata)
  references/codebooks/ukb/catbrowse.txt      (category tree)
  references/codebooks/ukb/esimpint.txt       (integer encoding values)
  references/codebooks/ukb/esimpstring.txt    (string encoding values)
  references/codebooks/ukb/esimpreal.txt      (real encoding values)
  references/codebooks/ukb/esimpdate.txt      (date encoding values)
  references/codebooks/ukb/ehierint.txt       (hierarchical int values, e.g. ICD-10)
  references/codebooks/ukb/ehierstring.txt    (hierarchical string values)
  references/codebooks/ukb/insvalue.txt       (instance definitions)
  references/codebooks/ukb/category.txt       (category definitions)

Usage:
  python3 scripts/codebooks/fetch_ukb_showcase.py
  python3 scripts/codebooks/fetch_ukb_showcase.py --output-dir /tmp/ukb_raw
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "references" / "codebooks" / "ukb"

BASE_URL = "https://biobank.ndph.ox.ac.uk/ukb/scdown.cgi"

# Schema ID → local filename, description
SCHEMAS = {
    1:  ("field.txt",         "Field definitions"),
    2:  ("encoding.txt",      "Encoding metadata"),
    3:  ("category.txt",      "Category definitions"),
    5:  ("esimpint.txt",      "Integer encoding values"),
    6:  ("esimpstring.txt",   "String encoding values"),
    7:  ("esimpreal.txt",     "Real encoding values"),
    8:  ("esimpdate.txt",     "Date encoding values"),
    9:  ("insvalue.txt",      "Instance definitions"),
    11: ("ehierint.txt",      "Hierarchical integer values"),
    12: ("ehierstring.txt",   "Hierarchical string values"),
    13: ("catbrowse.txt",     "Category browse tree"),
}


def download_schema(schema_id: int, filename: str, output_dir: Path) -> int:
    """Download a single schema file. Returns byte count."""
    url = f"{BASE_URL}?fmt=txt&id={schema_id}"
    dest = output_dir / filename
    req = Request(url, headers={"User-Agent": "mlgg-ukb-codebook/1.0"})

    try:
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
    except (URLError, HTTPError) as exc:
        print(f"  [FAIL] Schema {schema_id} ({filename}): {exc}", file=sys.stderr)
        return 0

    dest.write_bytes(data)
    return len(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download UKB Data Showcase schema files")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Directory to save schema files")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading UKB Data Showcase schemas to {args.output_dir}")
    print(f"Source: {BASE_URL}")
    print()

    total_bytes = 0
    failed = []
    for schema_id, (filename, desc) in sorted(SCHEMAS.items()):
        print(f"  Schema {schema_id:2d}: {desc:40s} → {filename} ...", end=" ", flush=True)
        nbytes = download_schema(schema_id, filename, args.output_dir)
        if nbytes == 0:
            failed.append(filename)
            print("FAILED")
        else:
            total_bytes += nbytes
            print(f"{nbytes:,} bytes")
        time.sleep(0.5)  # polite rate limit

    print()
    print(f"{'='*50}")
    print(f"Downloaded {len(SCHEMAS) - len(failed)}/{len(SCHEMAS)} schemas")
    print(f"Total size: {total_bytes / (1024*1024):.1f} MB")
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
