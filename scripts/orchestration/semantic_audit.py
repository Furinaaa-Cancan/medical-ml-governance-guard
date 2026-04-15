"""
Semantic audit: LLM-powered review layer that runs after rule-based gates.

Catches issues that rules miss — semantic leakage, implicit temporal
information in feature names, clinical plausibility problems, etc.

Does NOT modify existing gate results. Produces a separate advisory report.
Can be run standalone or integrated via --diagnose in the pipeline.

Usage:
    python semantic_audit.py --evidence-dir evidence/ --request request.json
    python semantic_audit.py --columns "age,bmi,hba1c_3mo_post,creatinine,death_flag"
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_columns_from_split(split_path: str, max_rows: int = 5) -> tuple[list[str], list[dict]]:
    """Read column names and a few sample rows (values only, no PHI) from a CSV."""
    path = Path(split_path)
    if not path.exists():
        return [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        # Read a few rows to get data type hints (not actual values)
        sample_types: list[dict] = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            types = {}
            for col in columns:
                val = row.get(col, "")
                if val == "":
                    types[col] = "missing"
                elif val.replace(".", "", 1).replace("-", "", 1).isdigit():
                    types[col] = "numeric"
                elif val.lower() in ("true", "false", "0", "1", "yes", "no"):
                    types[col] = "binary"
                else:
                    types[col] = "categorical"
            sample_types.append(types)
    return list(columns), sample_types


def audit_feature_semantics(
    columns: List[str],
    target_name: str = "",
    target_col: str = "",
    index_time_col: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Use LLM to detect semantic leakage and clinical plausibility issues.

    Args:
        columns: List of feature column names.
        target_name: Clinical outcome being predicted (e.g., "diabetes").
        target_col: Label column name.
        index_time_col: Index time column name.
        context: Optional project context dict.

    Returns:
        Audit result dict with findings, or None if audit failed.
    """
    if not columns:
        return None

    # Redact: only send column names, never values
    prompt = f"""You are a medical ML data leakage expert. Analyze these feature column names
for a binary classification model predicting: {target_name or 'unknown outcome'}.

Label column: {target_col or 'not specified'}
Index time column: {index_time_col or 'not specified'}

Feature columns ({len(columns)} total):
{json.dumps(columns, indent=2)}

Check for:
1. **Temporal leakage**: columns that encode information from AFTER the prediction
   time point (e.g., "outcome_date", "post_treatment_response", "3mo_followup_hba1c")
2. **Target leakage**: columns that are direct transformations or proxies of the
   label (e.g., if predicting mortality, a column named "survival_days")
3. **Information leakage**: columns that wouldn't be available at prediction time
   in a real clinical workflow (e.g., "discharge_summary", "final_diagnosis")
4. **Clinical plausibility**: columns that are medically nonsensical as predictors
   for this outcome

For EACH suspicious column, output a JSON object:
{{"column": "name", "risk": "temporal|target|information|plausibility",
  "severity": "critical|high|medium", "reason": "one sentence"}}

Output a JSON object with:
{{"findings": [...], "clean_count": N, "summary": "one sentence"}}

If no issues found, output: {{"findings": [], "clean_count": {len(columns)}, "summary": "No semantic leakage detected."}}

Output ONLY valid JSON."""

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--max-budget-usd", "0.15",
                "--system-prompt",
                "You are a medical ML leakage detection expert. Output only valid JSON. "
                "Be conservative: only flag columns where leakage risk is clear from the name. "
                "Do not flag legitimate clinical features.",
                prompt,
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return None

        raw = result.stdout.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[SEMANTIC] Audit failed: {exc}", file=sys.stderr)
        return None


def audit_from_evidence(
    evidence_dir: Path,
    request_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Run semantic audit using evidence from a pipeline run."""
    # Try to load request info
    target_name = ""
    target_col = ""
    index_time_col = ""
    columns: List[str] = []

    # Load from request contract report
    contract_report = evidence_dir / "request_contract_report.json"
    if contract_report.exists():
        try:
            with open(contract_report) as f:
                report = json.load(f)
            normalized = report.get("normalized_request", {})
            target_name = normalized.get("target_name", "")
            target_col = normalized.get("label_col", "")
            index_time_col = normalized.get("index_time_col", "")

            # Get columns from train split
            split_paths = normalized.get("split_paths", {})
            train_path = split_paths.get("train", "")
            if train_path:
                columns, _ = _read_columns_from_split(train_path)
        except (json.JSONDecodeError, OSError):
            pass

    # Fall back to cohort definition report for columns
    if not columns:
        cohort_report = evidence_dir / "cohort_definition_report.json"
        if cohort_report.exists():
            try:
                with open(cohort_report) as f:
                    report = json.load(f)
                columns = report.get("columns", [])
                if not columns:
                    columns = list(report.get("column_types", {}).keys())
            except (json.JSONDecodeError, OSError):
                pass

    if not columns:
        print("[SEMANTIC] No columns found in evidence. Provide --columns manually.", file=sys.stderr)
        return None

    # Filter out known non-feature columns
    non_features = {target_col, index_time_col, "patient_id", "subject_id", "id"}
    feature_cols = [c for c in columns if c.lower() not in {n.lower() for n in non_features if n}]

    result = audit_feature_semantics(
        feature_cols,
        target_name=target_name,
        target_col=target_col,
        index_time_col=index_time_col,
    )

    if result:
        # Save report
        out_path = evidence_dir / "semantic_audit_report.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[SEMANTIC] Report saved to {out_path}", file=sys.stderr)

        findings = result.get("findings", [])
        if findings:
            print(f"\n[SEMANTIC] {len(findings)} potential issue(s) found:", file=sys.stderr)
            for finding in findings:
                sev = finding.get("severity", "?").upper()
                col = finding.get("column", "?")
                risk = finding.get("risk", "?")
                reason = finding.get("reason", "")
                print(f"  [{sev}] {col} ({risk}): {reason}", file=sys.stderr)
        else:
            print(f"[SEMANTIC] All {result.get('clean_count', '?')} features look clean.", file=sys.stderr)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Semantic audit: LLM-powered review of feature columns for leakage.",
    )
    parser.add_argument("--evidence-dir", help="Evidence directory from a pipeline run.")
    parser.add_argument("--columns", help="Comma-separated list of column names (standalone mode).")
    parser.add_argument("--target", default="", help="Prediction target name (e.g., 'diabetes').")
    parser.add_argument("--target-col", default="", help="Label column name.")
    parser.add_argument("--time-col", default="", help="Index time column name.")
    args = parser.parse_args()

    if args.evidence_dir:
        result = audit_from_evidence(Path(args.evidence_dir))
    elif args.columns:
        cols = [c.strip() for c in args.columns.split(",")]
        result = audit_feature_semantics(
            cols,
            target_name=args.target,
            target_col=args.target_col,
            index_time_col=args.time_col,
        )
        if result:
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        return 1

    if result is None:
        return 2
    return 0 if not result.get("findings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
