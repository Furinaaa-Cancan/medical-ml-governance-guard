"""Guard against drift between SKILL.md 12-dimension scoring table and
agents/reviewer.yaml system_prompt. P0-1 fix (see plans/list-eager-beacon.md).

SKILL.md is the authoritative source; reviewer.yaml must mirror it exactly.
Any dimension/weight change in SKILL.md without the same change in reviewer.yaml
(or vice versa) fails CI — preventing the specific drift where reviewer.yaml
had no "Leakage Prevention" dimension at all.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = PROJECT_ROOT / "SKILL.md"
REVIEWER_YAML = PROJECT_ROOT / "agents" / "reviewer.yaml"

EXPECTED_DIMENSIONS = [
    ("Data Integrity", 12),
    ("Leakage Prevention", 15),
    ("Pipeline Isolation", 12),
    ("Model Selection Rigor", 10),
    ("Statistical Validity", 12),
    ("Generalization Evidence", 10),
    ("Clinical Completeness", 7),
    ("Reporting Standards", 7),
    ("Reproducibility", 6),
    ("Security & Provenance", 3),
    ("Fairness", 3),
    ("Sample Size", 3),
]


def _parse_skill_md_table() -> list[tuple[str, int]]:
    """Parse the `## 12 维评分` table in SKILL.md → [(zh_name, weight), ...]."""
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.search(
        r"## 12 维评分.*?\n(\|.*?\n)(?=\n[^|])",
        text,
        flags=re.DOTALL,
    )
    assert match, "SKILL.md §'12 维评分' table not found"
    rows = []
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in {"#", "---"} or cells[0].startswith(":"):
            continue
        if not cells[0].isdigit():
            continue
        zh_name = cells[1]
        try:
            weight = int(cells[2])
        except ValueError:
            continue
        rows.append((zh_name, weight))
    return rows


def _parse_reviewer_yaml_weights() -> list[tuple[str, int]]:
    """Parse the numbered '1.  Dimension Name (weight N)' lines in reviewer.yaml."""
    text = REVIEWER_YAML.read_text(encoding="utf-8")
    pattern = re.compile(r"^\s*(\d+)\.\s+([^\(]+?)\s*\(weight\s+(\d+)\)", re.MULTILINE)
    rows = []
    for m in pattern.finditer(text):
        idx = int(m.group(1))
        name = m.group(2).strip()
        weight = int(m.group(3))
        rows.append((idx, name, weight))
    rows.sort(key=lambda r: r[0])
    return [(name, weight) for _, name, weight in rows]


def test_skill_md_has_twelve_dimensions_summing_to_100():
    rows = _parse_skill_md_table()
    assert len(rows) == 12, f"Expected 12 dimensions in SKILL.md, got {len(rows)}"
    total = sum(w for _, w in rows)
    assert total == 100, f"SKILL.md dimension weights sum to {total}, expected 100"


def test_reviewer_yaml_weights_match_expected():
    rows = _parse_reviewer_yaml_weights()
    assert rows == EXPECTED_DIMENSIONS, (
        "reviewer.yaml 12-dimension list has drifted from the canonical scheme.\n"
        f"Found:    {rows}\n"
        f"Expected: {EXPECTED_DIMENSIONS}\n"
        "Update agents/reviewer.yaml system_prompt OR update EXPECTED_DIMENSIONS "
        "here and SKILL.md §'12 维评分' together."
    )


def test_reviewer_yaml_contains_leakage_prevention_dimension():
    """Explicit regression guard for the exact bug P0-1 fixed:
    reviewer.yaml previously had no leakage dimension at all."""
    rows = _parse_reviewer_yaml_weights()
    names = [n for n, _ in rows]
    assert "Leakage Prevention" in names, (
        "reviewer.yaml must contain a 'Leakage Prevention' dimension — "
        "this is the tool's namesake and highest-weight criterion."
    )
    leakage_weight = dict(rows)["Leakage Prevention"]
    assert leakage_weight == 15, (
        f"Leakage Prevention weight should be 15, got {leakage_weight}"
    )


def test_reviewer_yaml_and_skill_md_weight_totals_agree():
    skill_total = sum(w for _, w in _parse_skill_md_table())
    reviewer_total = sum(w for _, w in _parse_reviewer_yaml_weights())
    assert skill_total == reviewer_total == 100


def test_docs_consistency_script_passes():
    """P1-6: the diagnostics script must confirm SKILL.md / reviewer.yaml /
    README.md / README_EN.md agree on the 12-dim weights and names."""
    import subprocess
    script = PROJECT_ROOT / "scripts" / "diagnostics" / "check_docs_consistency.py"
    result = subprocess.run(
        ["python3", str(script)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, (
        f"check_docs_consistency.py failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
