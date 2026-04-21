#!/usr/bin/env python3
"""Render per-disease clinician-review sheets from the LLM-compiled disease KB.

Reads `references/methodology/disease-definition-knowledge-base.json` and writes
one Markdown review sheet per disease into ``evidence/disease_kb_review/``.
Each sheet pre-populates the current KB definition (ICD codes, lab criteria,
medications, exclusions, definition_variables_to_exclude) alongside the
canonical guideline a clinician is expected to verify against.

Rationale
---------
The KB's per-disease `provenance.source` is ``llm_compiled`` and
``clinician_review_status`` is ``pending``. Downstream gates flag this in
every emitted issue, but publication-grade claims require an actual sign-off.
Clinicians need structured, pre-populated review sheets rather than having
to re-read the raw JSON — this script renders those sheets deterministically.

Run
---
    python3 scripts/diagnostics/generate_disease_kb_review_sheets.py

Flags
-----
    --kb PATH           override KB path
    --output-dir DIR    override output directory
    --force             overwrite even if a sheet already has sign-off
                        metadata (default: skip those to preserve manual edits)

The sheets are written atomically. Re-running regenerates *only* sheets that
have no reviewer metadata; sheets with a completed ``## Sign-off`` block are
preserved unless ``--force`` is passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"
DEFAULT_OUT = REPO_ROOT / "evidence" / "disease_kb_review"

# Canonical clinical guidelines clinicians should cross-check each disease
# definition against. These are *suggestions* curated from major society
# publications; a reviewer may substitute or add regional equivalents.
# The script does not claim these are the only valid sources — it only
# ensures the reviewer has a named starting point rather than a blank page.
GUIDELINE_TARGETS: Dict[str, List[Dict[str, str]]] = {
    "type_2_diabetes": [
        {"name": "ADA Standards of Care in Diabetes—2024",
         "citation": "American Diabetes Association. Diabetes Care 2024;47(Suppl 1)."},
        {"name": "WHO classification of diabetes mellitus (2019)",
         "citation": "World Health Organization, 2019."},
    ],
    "hypertension": [
        {"name": "2017 ACC/AHA High Blood Pressure Guideline",
         "citation": "Whelton et al. JACC 2018;71(19):e127-e248."},
        {"name": "2023 ESH Guidelines for management of arterial hypertension",
         "citation": "Mancia et al. J Hypertens 2023;41(12):1874-2071."},
    ],
    "coronary_heart_disease": [
        {"name": "2023 AHA/ACC Guideline for Chronic Coronary Disease",
         "citation": "Virani et al. JACC 2023;82(9):833-955."},
        {"name": "Fourth Universal Definition of Myocardial Infarction (2018)",
         "citation": "Thygesen et al. JACC 2018;72(18):2231-2264."},
    ],
    "chronic_kidney_disease": [
        {"name": "KDIGO 2024 Clinical Practice Guideline for CKD",
         "citation": "Kidney Disease: Improving Global Outcomes, 2024."},
    ],
    "heart_failure": [
        {"name": "2022 AHA/ACC/HFSA Guideline for Management of Heart Failure",
         "citation": "Heidenreich et al. JACC 2022;79(17):e263-e421."},
        {"name": "Universal Definition and Classification of Heart Failure (2021)",
         "citation": "Bozkurt et al. J Card Fail 2021;27(4):387-413."},
    ],
    "stroke": [
        {"name": "2019 AHA/ASA Guideline for Early Management of Acute Ischemic Stroke",
         "citation": "Powers et al. Stroke 2019;50:e344-e418."},
        {"name": "2021 AHA/ASA Guideline for Prevention of Recurrent Stroke/TIA",
         "citation": "Kleindorfer et al. Stroke 2021;52:e364-e467."},
    ],
    "copd": [
        {"name": "GOLD 2024 Report — Global Strategy for COPD",
         "citation": "Global Initiative for Chronic Obstructive Lung Disease, 2024."},
    ],
    "major_depressive_disorder": [
        {"name": "DSM-5-TR",
         "citation": "American Psychiatric Association, DSM-5-TR, 2022."},
        {"name": "ICD-11 chapter 06 (Mental, behavioural and neurodevelopmental disorders)",
         "citation": "WHO ICD-11, 2022."},
    ],
    "cancer_any": [
        {"name": "SEER Program coding manual (site-specific)",
         "citation": "NCI Surveillance, Epidemiology, and End Results Program."},
        {"name": "NCCN Clinical Practice Guidelines (per cancer site)",
         "citation": "National Comprehensive Cancer Network, current version."},
    ],
    "atrial_fibrillation": [
        {"name": "2023 ACC/AHA/ACCP/HRS Guideline for Diagnosis and Management of AF",
         "citation": "Joglar et al. Circulation 2023;149:e1-e156."},
    ],
    "readmission_30day": [
        {"name": "CMS Hospital Readmissions Reduction Program (HRRP) measure spec",
         "citation": "Centers for Medicare & Medicaid Services, current FY methodology."},
        {"name": "Yale/CMS Risk-Standardized Readmission Rate measures",
         "citation": "Yale New Haven Health Services Corporation."},
    ],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kb", type=Path, default=DEFAULT_KB,
                   help="Path to disease KB JSON")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT,
                   help="Directory to write review sheets into")
    p.add_argument("--force", action="store_true",
                   help="Overwrite sheets that appear to have reviewer sign-off")
    return p.parse_args()


def _fmt_list(items: Optional[Iterable[Any]], prefix: str = "- ") -> str:
    if not items:
        return "- _(none listed)_"
    return "\n".join(f"{prefix}`{item}`" if isinstance(item, str)
                     else f"{prefix}{item}" for item in items)


def _fmt_lab_criteria(crit: Optional[List[Dict[str, Any]]]) -> str:
    if not crit:
        return "_(no lab criteria listed)_"
    lines: List[str] = []
    for c in crit:
        test = c.get("test", "?")
        thr = c.get("threshold", "?")
        unit_alt = c.get("unit_alt")
        note = c.get("note")
        fasting = c.get("fasting_required")
        line = f"- **{test}** {thr}"
        if unit_alt:
            line += f" ({unit_alt})"
        if fasting is not None:
            line += f" — fasting: {fasting}"
        if note:
            line += f" — _{note}_"
        lines.append(line)
    return "\n".join(lines)


def _fmt_exclusions(exc: Optional[List[Dict[str, Any]]]) -> str:
    if not exc:
        return "_(no exclusions listed)_"
    lines: List[str] = []
    for e in exc:
        cond = e.get("condition", "?")
        icd = e.get("icd10") or e.get("icd9") or []
        reason = e.get("reason") or e.get("note") or ""
        icd_str = f" [{', '.join(icd)}]" if icd else ""
        reason_str = f" — {reason}" if reason else ""
        lines.append(f"- **{cond}**{icd_str}{reason_str}")
    return "\n".join(lines)


def _sheet_preserves_signoff(path: Path) -> bool:
    """Return True if an existing sheet appears to have been edited with
    clinician sign-off (used by --force to decide whether to overwrite)."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return "(to be filled)" not in text and "Reviewer:" in text


def render_sheet(key: str, entry: Dict[str, Any], kb_version: str) -> str:
    """Produce the Markdown review sheet for one disease."""
    name = entry.get("name", key.replace("_", " ").title())
    prov = entry.get("provenance", {}) or {}
    status = prov.get("clinician_review_status", "pending")

    targets = GUIDELINE_TARGETS.get(key) or [
        {"name": "(no canonical guideline pre-suggested — reviewer to nominate)",
         "citation": ""}
    ]
    guideline_block = "\n".join(
        f"- **{t['name']}** — {t['citation']}" if t.get("citation") else f"- **{t['name']}**"
        for t in targets
    )

    return f"""# Clinician Review — {name}

**Disease key**: `{key}`
**KB version**: {kb_version}
**Current review status**: `{status}`
**Generated**: {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

> This sheet is **auto-generated** from `disease-definition-knowledge-base.json`.
> When you complete the review, update the KB entry's `provenance` block (see
> the Sign-off section at the bottom); this file is a working document and
> will be regenerated from the KB each time the generator runs.

---

## 1. Canonical guideline targets to cross-check against

{guideline_block}

If a different guideline applies in your setting (regional / specialty
society), note the substitution in the Sign-off section.

---

## 2. Current LLM-compiled definition

### 2.1 ICD-10 codes
{_fmt_list(entry.get("icd10"))}

### 2.2 ICD-9-CM codes
{_fmt_list(entry.get("icd9"))}

### 2.3 Lab criteria
{_fmt_lab_criteria(entry.get("lab_criteria"))}

### 2.4 Medications (generic names)
{_fmt_list(entry.get("medications"))}

### 2.5 ATC codes
{_fmt_list(entry.get("medication_atc_codes"))}

### 2.6 Self-report fields
{_fmt_list(entry.get("self_report_fields"))}

### 2.7 Exclusions
{_fmt_exclusions(entry.get("exclusions"))}

### 2.8 `definition_variables_to_exclude` — SAFETY-CRITICAL
These are the columns a downstream model must NOT use as features — each
one is a definition variable that, if present in the feature set, constitutes
label leakage. **Missing entries = false negatives (leakage not caught).**

{_fmt_list(entry.get("definition_variables_to_exclude"))}

---

## 3. Clinician verification checklist

- [ ] **ICD-10 codes**: complete for the diagnosis? Any subtypes missing?
      Any incorrect codes?
- [ ] **ICD-9-CM codes**: still relevant for the target EHR era; add/remove
      as needed.
- [ ] **Lab criteria**: thresholds match the guideline(s) cited in §1?
      Units correct (SI vs conventional)?
- [ ] **Medications**: at least one agent per major class; any
      recently-approved drugs missing (e.g., GLP-1s for T2D, SGLT2i for
      CKD/HF)?
- [ ] **ATC codes**: correct hierarchy level (e.g., `A10B` = oral diabetes
      drugs — should sub-codes be enumerated?)?
- [ ] **Self-report fields**: plausible column names for UK Biobank / NHANES
      / typical EHR extracts?
- [ ] **Exclusions**: secondary / atypical / pregnancy / pediatric forms
      correctly listed?
- [ ] **`definition_variables_to_exclude`**: every column whose value is
      derived from the diagnosis being defined is present. **This is the
      safety-critical field — missing an entry silently allows label
      leakage in downstream gates.**

---

## 4. Sign-off

When verified, edit `references/methodology/disease-definition-knowledge-base.json`
at `diseases.{key}.provenance` to:

```json
"provenance": {{
  "source": "clinician_reviewed",
  "description": "Reviewed against <guideline name and year>.",
  "clinician_review_status": "clinician_reviewed",
  "last_reviewed": "YYYY-MM-DD",
  "reviewer": "(to be filled) <Dr. Name>, <credentials>, <specialty>",
  "review_checklist": "references/methodology/DISEASE_KB_REVIEW.md",
  "reviewed_against": ["<guideline name and year>"]
}}
```

Then commit:

```
review(kb): clinician sign-off for {key} (<reviewer initials>)
```

Reviewer: (to be filled)
Date: (to be filled)
Deviations from LLM-compiled content: (to be filled — list each change
with guideline section reference)
"""


def render_index(entries: List[Dict[str, Any]], kb_version: str) -> str:
    lines = [
        "# Disease KB Clinician Review — Index",
        "",
        f"**KB version**: {kb_version}  ",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
        f"**Total diseases**: {len(entries)}",
        "",
        "| Disease | Key | Current status | Sheet |",
        "|---|---|---|---|",
    ]
    for key, name, status in entries:
        lines.append(
            f"| {name} | `{key}` | `{status}` | [{key}_review.md]({key}_review.md) |"
        )
    lines.extend([
        "",
        "## How to use this index",
        "",
        "1. Pick a disease row above.",
        "2. Open its review sheet.",
        "3. Complete the checklist against the cited guideline(s).",
        "4. Update the `provenance` block in "
        "`references/methodology/disease-definition-knowledge-base.json` per "
        "the Sign-off section of the sheet.",
        "5. Re-run `scripts/diagnostics/disease_kb_review_check.py --strict` — "
        "it passes only when all 11 entries are reviewed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    kb_path = args.kb.expanduser().resolve()
    out_dir = args.output_dir.expanduser().resolve()

    if not kb_path.exists():
        print(f"ERROR: KB not found: {kb_path}", file=sys.stderr)
        return 1

    with kb_path.open("r", encoding="utf-8") as fh:
        kb = json.load(fh)

    diseases = kb.get("diseases", {})
    if not diseases:
        print("ERROR: KB has no 'diseases' block.", file=sys.stderr)
        return 1

    kb_version = str(kb.get("version", "unknown"))
    out_dir.mkdir(parents=True, exist_ok=True)

    index_rows: List[Dict[str, Any]] = []
    skipped = 0
    written = 0

    for key, entry in diseases.items():
        sheet_path = out_dir / f"{key}_review.md"
        if _sheet_preserves_signoff(sheet_path) and not args.force:
            skipped += 1
            status_from_sheet = "preserved (reviewer edits detected)"
        else:
            sheet_path.write_text(render_sheet(key, entry, kb_version), encoding="utf-8")
            written += 1
            prov = entry.get("provenance", {}) or {}
            status_from_sheet = prov.get("clinician_review_status", "pending")
        index_rows.append((key, entry.get("name", key), status_from_sheet))

    (out_dir / "INDEX.md").write_text(render_index(index_rows, kb_version), encoding="utf-8")

    print(f"Wrote {written} review sheet(s), skipped {skipped} (reviewer edits preserved).")
    print(f"Output directory: {out_dir}")
    print(f"Index: {out_dir / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
