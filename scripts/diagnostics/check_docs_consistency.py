"""P1-6: Validate that the 12-dimension scoring scheme is consistent across
SKILL.md (authoritative), agents/reviewer.yaml, README.md, README_EN.md.

SKILL.md §"12 维评分" is the single source of truth for dimension weights.
Any downstream doc or config that maintains its own 12-dim table must
match the weights position-by-position.

Exit 0 on success, 2 on inconsistency. Intended for CI/pre-commit.

Usage:
    python3 scripts/diagnostics/check_docs_consistency.py
    python3 scripts/diagnostics/check_docs_consistency.py --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Parsers for each doc's 12-dim table ──────────────────────────────────────


def _parse_skill_md() -> list[tuple[int, str, int]]:
    """SKILL.md §'12 维评分' → [(index, zh_name, weight), ...]."""
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"## 12 维评分.*?\n(\|.*?\n)(?=\n[^|])", text, flags=re.DOTALL)
    if not match:
        raise SystemExit("SKILL.md §'12 维评分' table not found")
    rows = []
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        rows.append((int(cells[0]), cells[1], int(cells[2])))
    return rows


def _parse_reviewer_yaml() -> list[tuple[int, str, int]]:
    """agents/reviewer.yaml numbered dimensions → [(index, en_name, weight), ...]."""
    text = (ROOT / "agents" / "reviewer.yaml").read_text(encoding="utf-8")
    pattern = re.compile(r"^\s*(\d+)\.\s+([^\(]+?)\s*\(weight\s+(\d+)\)", re.MULTILINE)
    rows = []
    for m in pattern.finditer(text):
        rows.append((int(m.group(1)), m.group(2).strip(), int(m.group(3))))
    rows.sort(key=lambda r: r[0])
    return rows


def _parse_readme_table(path: Path, header_pattern: str) -> list[tuple[int, str, int]] | None:
    """Generic parser for the 12-dim table in README(_EN).md.

    Looks for a markdown table whose header row matches `header_pattern`.
    Returns None if the doc has no such table (acceptable).
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # Locate the header line
    header_re = re.compile(header_pattern, re.MULTILINE)
    m = header_re.search(text)
    if not m:
        return None
    # Collect subsequent table rows until a non-pipe, non-empty line
    rows: list[tuple[int, str, int]] = []
    lines = text[m.end():].splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            # The very first line after the header is the regex tail; skip blanks.
            continue
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3:
            break
        idx_cell = cells[0]
        if not idx_cell.isdigit():
            # alignment row like |:--|:--|
            continue
        try:
            idx = int(idx_cell)
            name = cells[1]
            weight = int(cells[2])
        except ValueError:
            continue
        rows.append((idx, name, weight))
    return rows or None


def _parse_readme_zh() -> list[tuple[int, str, int]] | None:
    return _parse_readme_table(
        ROOT / "README.md",
        r"^\|\s*#\s*\|\s*维度\s*\|\s*权重\s*\|[^\n]*$",
    )


def _parse_readme_en() -> list[tuple[int, str, int]] | None:
    return _parse_readme_table(
        ROOT / "README_EN.md",
        r"^\|\s*#\s*\|\s*Dimension\s*\|\s*Weight\s*\|[^\n]*$",
    )


# ── Validation ────────────────────────────────────────────────────────────────


def _check(
    authoritative: list[tuple[int, str, int]],
    other: list[tuple[int, str, int]] | None,
    other_name: str,
    name_check: bool,
) -> list[str]:
    """Compare `other` vs `authoritative`. Returns a list of error strings."""
    errors: list[str] = []
    if other is None:
        return [f"[{other_name}] 12-dim table not found (expected)"]
    if len(other) != len(authoritative):
        errors.append(
            f"[{other_name}] has {len(other)} dimensions, expected {len(authoritative)}"
        )
        return errors
    for (ai, an, aw), (oi, on, ow) in zip(authoritative, other):
        if ai != oi:
            errors.append(f"[{other_name}] index {oi} at position of {ai}")
        if aw != ow:
            errors.append(
                f"[{other_name}] dim #{ai} weight={ow} but SKILL.md says {aw}"
            )
        if name_check and an != on:
            errors.append(
                f"[{other_name}] dim #{ai} name='{on}' but SKILL.md says '{an}'"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    skill = _parse_skill_md()
    if len(skill) != 12 or sum(w for _, _, w in skill) != 100:
        print(
            f"FAIL: SKILL.md scoring table is malformed (got {len(skill)} dims, "
            f"weight sum {sum(w for _, _, w in skill)})"
        )
        return 2

    if args.verbose:
        print("SKILL.md (authoritative):")
        for idx, name, w in skill:
            print(f"  {idx:2d}. {name} ({w})")

    all_errors: list[str] = []

    # reviewer.yaml — weights must match; names are English so no name check
    reviewer = _parse_reviewer_yaml()
    all_errors += _check(skill, reviewer, "agents/reviewer.yaml", name_check=False)

    # README.md — Chinese names must match exactly (same language as SKILL.md)
    all_errors += _check(skill, _parse_readme_zh(), "README.md", name_check=True)

    # README_EN.md — weights only (English names, separate concern)
    all_errors += _check(skill, _parse_readme_en(), "README_EN.md", name_check=False)

    # reviewer.yaml English names must match README_EN.md English names
    reviewer_en = _parse_reviewer_yaml()
    readme_en = _parse_readme_en()
    if reviewer_en and readme_en and len(reviewer_en) == len(readme_en):
        for (ri, rn, _), (ei, en, _) in zip(reviewer_en, readme_en):
            if ri == ei and rn.lower() != en.lower():
                all_errors.append(
                    f"[name drift] reviewer.yaml '{rn}' vs README_EN.md '{en}' (dim #{ri})"
                )

    if all_errors:
        print("FAIL — 12-dim scoring is inconsistent:")
        for e in all_errors:
            print(f"  - {e}")
        return 2
    print("OK — 12-dim scoring consistent across SKILL.md / reviewer.yaml / README.md / README_EN.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
