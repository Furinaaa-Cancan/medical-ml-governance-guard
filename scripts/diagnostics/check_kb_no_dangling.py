#!/usr/bin/env python3
"""Detect dangling concern_id references outside peer-review-kb.json (W20-C3).

Why
---
W17-C5 surfaced ``PR-040-C01`` as a dangling reference: still listed in
``rag-eval-set.yaml`` but absent from ``peer-review-kb.json`` because the
concern was hard-deleted without flagging external refs. The fix is the
soft-deprecate contract in ``scripts/core/_kb_schema.py``; this checker is
the runtime enforcement that catches the next regression.

Scope
-----
External artifacts scanned for concern_ids:

* ``references/case-studies/rag-eval-set.yaml``
* ``references/retrieval_eval/scenarios.json``

(Test fixtures under ``tests/`` are intentionally **not** scanned — they can
embed synthetic concern_ids that are meant not to exist in the KB. If you
hardcode a real concern_id in a test, prefer a fixture loaded from the KB
file instead.)

Exit codes
----------
* ``0`` — no dangling references.
* ``2`` — at least one external reference points to a concern_id absent from
  the KB. The output names every offender and recommends a fix
  (soft-deprecate or drop the external ref).

Usage
-----
.. code-block:: bash

   python3 scripts/diagnostics/check_kb_no_dangling.py
   python3 scripts/diagnostics/check_kb_no_dangling.py --kb path/to/kb.json \
       --eval-set path/to/rag-eval-set.yaml \
       --scenarios path/to/scenarios.json \
       --report dangling.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"
DEFAULT_EVAL_SET = REPO_ROOT / "references" / "case-studies" / "rag-eval-set.yaml"
DEFAULT_SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"

# Permissive concern_id pattern. Real KB uses ``PR-###-C##`` but we accept any
# digit length so future expansions (PR-1000+, C100+) don't silently slip past.
_CONCERN_ID_RE = re.compile(r"PR-\d+-C\d+")


def load_kb_concern_ids(kb_path: Path) -> Set[str]:
    """Return the set of concern_ids currently defined in the KB.

    Includes soft-deprecated concerns (``deprecated: true``) — those still
    exist in the KB and external refs to them are valid by design.
    """
    if not kb_path.exists():
        raise FileNotFoundError(f"KB not found: {kb_path}")
    kb = json.loads(kb_path.read_text())
    ids: Set[str] = set()
    for entry in kb.get("entries", []):
        if not isinstance(entry, dict):
            continue
        for concern in entry.get("reviewer_concerns", []) or []:
            if not isinstance(concern, dict):
                continue
            cid = concern.get("concern_id")
            if isinstance(cid, str) and cid:
                ids.add(cid)
    return ids


def collect_external_refs(
    eval_set_path: Optional[Path] = None,
    scenarios_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Scan external artifacts for concern_id references.

    Returns a mapping ``{concern_id: [source_path, ...]}``. Sources are
    repo-relative posix paths so messages stay stable across machines.
    """
    refs: Dict[str, List[str]] = {}

    def _record(text: str, source: Path) -> None:
        for match in _CONCERN_ID_RE.findall(text):
            try:
                rel = str(source.resolve().relative_to(REPO_ROOT))
            except ValueError:
                rel = str(source)
            refs.setdefault(match, []).append(rel)

    if eval_set_path and eval_set_path.exists():
        # rag-eval-set.yaml uses inline ``[PR-001-C01, ...]`` list syntax
        # which regex-scans cleanly. Avoid a hard PyYAML dependency.
        _record(eval_set_path.read_text(), eval_set_path)

    if scenarios_path and scenarios_path.exists():
        _record(scenarios_path.read_text(), scenarios_path)

    # De-duplicate source paths per concern_id while preserving order.
    for cid, sources in refs.items():
        seen: Set[str] = set()
        deduped: List[str] = []
        for s in sources:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        refs[cid] = deduped

    return refs


def find_dangling(
    kb_ids: Set[str],
    external_refs: Dict[str, List[str]],
) -> List[Tuple[str, List[str]]]:
    """Return ``[(concern_id, [source_paths]), ...]`` for refs not in the KB.

    Sorted by concern_id for deterministic output.
    """
    dangling = [
        (cid, sources) for cid, sources in external_refs.items() if cid not in kb_ids
    ]
    return sorted(dangling, key=lambda x: x[0])


def _suggest_fix(concern_id: str, sources: Iterable[str]) -> str:
    """One-line remediation suggestion shown alongside each dangling ref."""
    src_list = ", ".join(sources)
    return (
        f"  -> options:\n"
        f"     (a) soft-deprecate {concern_id} in peer-review-kb.json "
        f"(set deprecated=true + deprecated_reason + deprecated_at), or\n"
        f"     (b) remove the reference from: {src_list}"
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Detect dangling concern_id refs in eval-set / scenarios.",
    )
    p.add_argument("--kb", type=Path, default=DEFAULT_KB,
                   help=f"Path to peer-review-kb.json (default: {DEFAULT_KB})")
    p.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET,
                   help="Path to rag-eval-set.yaml (default: project)")
    p.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS,
                   help="Path to scenarios.json (default: project)")
    p.add_argument("--report", type=Path, default=None,
                   help="Optional JSON report path.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress human-readable output (still writes report).")
    return p.parse_args(argv)


def _write_report(report_path: Path, payload: Dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    try:
        kb_ids = load_kb_concern_ids(args.kb)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: KB is not valid JSON: {exc}", file=sys.stderr)
        return 2

    external_refs = collect_external_refs(
        eval_set_path=args.eval_set,
        scenarios_path=args.scenarios,
    )
    dangling = find_dangling(kb_ids, external_refs)

    payload = {
        "kb_path": str(args.kb),
        "kb_concern_count": len(kb_ids),
        "external_ref_count": len(external_refs),
        "dangling_count": len(dangling),
        "dangling": [
            {"concern_id": cid, "sources": sources} for cid, sources in dangling
        ],
    }

    if args.report:
        _write_report(args.report, payload)

    if not args.quiet:
        if dangling:
            print(
                f"FAIL: {len(dangling)} dangling concern_id reference(s) found "
                f"(KB has {len(kb_ids)} concern_ids; external artifacts "
                f"reference {len(external_refs)})."
            )
            for cid, sources in dangling:
                print(f"\n  {cid}  referenced from: {', '.join(sources)}")
                print(_suggest_fix(cid, sources))
            print(
                "\nFix: prefer soft-deprecate (keeps the tombstone so external "
                "pointers stay valid). See scripts/core/_kb_schema.py for the "
                "contract."
            )
        else:
            print(
                f"OK: {len(external_refs)} external concern_id reference(s) "
                f"all resolve to KB entries ({len(kb_ids)} concern_ids)."
            )

    return 2 if dangling else 0


if __name__ == "__main__":
    raise SystemExit(main())
