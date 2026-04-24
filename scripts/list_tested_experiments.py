#!/usr/bin/env python3
"""List every directory in this repo that looks like a tested experiment.

"Tested experiment" = has an ``evidence/`` directory and either ``data/`` or
``configs/``. The scanner extracts identity, attestation state, entry code
(best-guess), and the last-updated timestamp, then renders a compact table.

The companion manifest ``references/operations/tested-experiments.json`` is
a static snapshot. Regenerate after adding / removing experiments:

    python3 scripts/list_tested_experiments.py --regenerate

This is an *index*, not a contract — entries whose ``entry_code`` field is
``null`` are projects that ran attestation once but left no reproducible
run script behind. Treat those as "needs a run.py before rerunning."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "references" / "operations" / "tested-experiments.json"
BENCHMARK_REGISTRY = REPO_ROOT / "references" / "operations" / "benchmark-registry.json"

_EXCLUDE_FRAGMENTS = (
    "/.venv/", "/__pycache__/", "/audit_repos/", "/repos/",
    "/tests/", "/references/", "/.git/", "/node_modules/",
)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _find_entry_code(proj: Path) -> Optional[str]:
    """Best-guess entry script for this experiment.

    Search order: local run_*.py → local run_*.sh → parent run_*.py that
    mentions this project's name → benchmark-registry entry.
    """
    # Local scripts
    for p in sorted(proj.glob("run_*.py")) + sorted(proj.glob("run_*.sh")):
        return str(p.relative_to(REPO_ROOT))
    # Parent orchestrator that names this case
    parent = proj.parent
    for p in sorted(parent.glob("run_*.py")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")[:20_000]
        except OSError:
            continue
        if proj.name in text:
            return f"{p.relative_to(REPO_ROOT)}  (case={proj.name})"
    # benchmark-registry.json
    if BENCHMARK_REGISTRY.exists():
        try:
            reg = json.loads(BENCHMARK_REGISTRY.read_text(encoding="utf-8"))
            if proj.name in reg.get("cases", {}):
                return f"benchmark-registry.json:cases.{proj.name}"
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _extract_targets(proj: Path) -> List[str]:
    phen = proj / "configs" / "phenotype_definitions.json"
    if not phen.exists():
        return []
    try:
        data = json.loads(phen.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    targets = data.get("targets", {})
    return list(targets.keys()) if isinstance(targets, dict) else []


def _attestation_time(proj: Path) -> Optional[str]:
    payload = proj / "evidence" / "attestation_payload.json"
    if not payload.exists():
        return None
    try:
        data = json.loads(payload.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _iso(payload.stat().st_mtime)
    # Try common timestamp keys; fall back to mtime
    for key in ("attested_at", "timestamp", "created_at", "attestation_time"):
        if key in data and isinstance(data[key], str):
            return data[key]
    return _iso(payload.stat().st_mtime)


def scan() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ev in REPO_ROOT.rglob("evidence"):
        if not ev.is_dir():
            continue
        path_str = str(ev)
        if any(frag in path_str for frag in _EXCLUDE_FRAGMENTS):
            continue
        proj = ev.parent
        has_data = (proj / "data").is_dir()
        has_cfg = (proj / "configs").is_dir()
        if not (has_data or has_cfg):
            continue

        data_csv = len(list((proj / "data").glob("*.csv"))) if has_data else 0
        evidence_files = sum(1 for _ in ev.iterdir())
        attested = (ev / "attestation_payload.json").exists()
        rows.append({
            "id": str(proj.relative_to(REPO_ROOT)),
            "data_csv": data_csv,
            "evidence_files": evidence_files,
            "attested": attested,
            "attestation_time": _attestation_time(proj) if attested else None,
            "targets": _extract_targets(proj),
            "entry_code": _find_entry_code(proj),
            "last_updated": _iso(ev.stat().st_mtime),
        })
    # Sort: attested first, more data first, alpha id
    rows.sort(key=lambda r: (not r["attested"], -r["data_csv"], r["id"]))
    return rows


def render_table(rows: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append(
        f"{'ID':<50} {'CSV':>3}  {'EV':>3}  {'ATT':>3}  entry_code"
    )
    lines.append("─" * 140)
    for r in rows:
        entry = r["entry_code"] or "(none — no run script)"
        att = "✓" if r["attested"] else "—"
        lines.append(
            f"{r['id']:<50} {r['data_csv']:>3}  {r['evidence_files']:>3}  {att:>3}  {entry}"
        )
    lines.append("")
    lines.append(f"Total: {len(rows)} projects  "
                 f"(attested: {sum(1 for r in rows if r['attested'])}  "
                 f"with-data: {sum(1 for r in rows if r['data_csv'])}  "
                 f"no-entry: {sum(1 for r in rows if not r['entry_code'])})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--regenerate", action="store_true",
        help=f"Overwrite {MANIFEST.relative_to(REPO_ROOT)} with the current scan."
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON to stdout instead of the table.")
    args = ap.parse_args()

    rows = scan()

    if args.json:
        json.dump({"generated_at": _iso(datetime.now(timezone.utc).timestamp()),
                   "count": len(rows), "experiments": rows},
                  sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    print(render_table(rows))

    if args.regenerate:
        payload = {
            "generated_at": _iso(datetime.now(timezone.utc).timestamp()),
            "description": (
                "Index of every directory in the repo shaped like a tested "
                "experiment (has evidence/ + configs/ or data/). Regenerated by "
                "scripts/list_tested_experiments.py --regenerate."
            ),
            "count": len(rows),
            "experiments": rows,
        }
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nWrote {MANIFEST.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
