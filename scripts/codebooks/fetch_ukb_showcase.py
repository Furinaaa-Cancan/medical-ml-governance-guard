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
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "references" / "codebooks" / "ukb"
MANIFEST_FILE = "source_manifest.json"

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


def download_schema(schema_id: int, filename: str, output_dir: Path) -> tuple[int, str, int]:
    """Download a single schema file. Returns (byte count, sha256, line count).
    Returns (0, "", 0) on failure so caller can skip.
    """
    url = f"{BASE_URL}?fmt=txt&id={schema_id}"
    dest = output_dir / filename
    req = Request(url, headers={"User-Agent": "mlgg-ukb-codebook/1.0"})

    try:
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
    except (URLError, HTTPError) as exc:
        print(f"  [FAIL] Schema {schema_id} ({filename}): {exc}", file=sys.stderr)
        return 0, "", 0

    # Atomic write: tmpfile + rename. Prevents half-written file if we
    # ctrl-C mid-download.
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)

    sha = hashlib.sha256(data).hexdigest()
    lines = data.count(b"\n")
    return len(data), sha, lines


def load_reference_manifest(output_dir: Path) -> dict:
    """Load the committed source_manifest.json if present."""
    path = output_dir / MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def verify_against_manifest(
    filename: str,
    nbytes: int,
    sha: str,
    lines: int,
    reference: dict,
) -> list[str]:
    """Compare downloaded bytes to the committed manifest.

    Returns list of issues. Empty list = this file matches the
    reference exactly. Non-empty = UKB changed something OR the
    download corrupted OR our reference is stale.
    """
    issues = []
    entry = reference.get("files", {}).get(filename)
    if entry is None:
        return ["not in reference manifest (new file?)"]
    if entry.get("sha256") != sha:
        issues.append(
            f"sha256 drift: ref={entry.get('sha256', '?')[:16]}... "
            f"got={sha[:16]}..."
        )
    if entry.get("bytes") != nbytes:
        issues.append(f"byte count: ref={entry.get('bytes')} got={nbytes}")
    if entry.get("lines") != lines:
        issues.append(f"line count: ref={entry.get('lines')} got={lines}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Download UKB Data Showcase schema files")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Directory to save schema files")
    parser.add_argument(
        "--update-manifest", action="store_true",
        help=("Re-write source_manifest.json with the newly-downloaded "
              "sha256s instead of comparing against the committed one. "
              "Use only when you have INTENTIONALLY accepted upstream UKB "
              "changes (new showcase release, new fields)."),
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 2 if any file drifts from the reference manifest.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading UKB Data Showcase schemas to {args.output_dir}")
    print(f"Source: {BASE_URL}")
    print()

    reference = {} if args.update_manifest else load_reference_manifest(args.output_dir)
    total_bytes = 0
    failed: list[str] = []
    drift: dict[str, list[str]] = {}
    new_manifest: dict = {
        "schema_version": time.strftime("%Y-%m-%d", time.gmtime()),
        "source": BASE_URL,
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {},
    }

    for schema_id, (filename, desc) in sorted(SCHEMAS.items()):
        print(f"  Schema {schema_id:2d}: {desc:40s} → {filename} ...", end=" ", flush=True)
        nbytes, sha, lines = download_schema(schema_id, filename, args.output_dir)
        if nbytes == 0:
            failed.append(filename)
            print("FAILED")
            time.sleep(0.5)
            continue
        total_bytes += nbytes
        new_manifest["files"][filename] = {
            "sha256": sha, "bytes": nbytes, "lines": lines,
        }
        # L1 defense: compare against committed reference (unless
        # --update-manifest explicitly accepts new upstream data).
        if reference:
            issues = verify_against_manifest(filename, nbytes, sha, lines, reference)
            if issues:
                drift[filename] = issues
                print(f"{nbytes:,} bytes [DRIFT: {'; '.join(issues)}]")
            else:
                print(f"{nbytes:,} bytes [match]")
        else:
            print(f"{nbytes:,} bytes")
        time.sleep(0.5)  # polite rate limit

    print()
    print(f"{'='*50}")
    print(f"Downloaded {len(SCHEMAS) - len(failed)}/{len(SCHEMAS)} schemas")
    print(f"Total size: {total_bytes / (1024*1024):.1f} MB")
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1

    if args.update_manifest:
        manifest_path = args.output_dir / MANIFEST_FILE
        manifest_path.write_text(json.dumps(new_manifest, indent=2) + "\n")
        print(f"Manifest updated: {manifest_path}")
    elif drift:
        print(f"\nDRIFT DETECTED ({len(drift)} file(s)):", file=sys.stderr)
        for fn, issues in drift.items():
            print(f"  {fn}:", file=sys.stderr)
            for issue in issues:
                print(f"    - {issue}", file=sys.stderr)
        print(
            "\nThis means UKB Showcase changed, OR the download was "
            "tampered / truncated.\n"
            "After manual review:\n"
            "  - If upstream release is expected → run with --update-manifest\n"
            "  - If not expected → investigate before trusting the codebook.",
            file=sys.stderr,
        )
        if args.strict:
            return 2

    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
