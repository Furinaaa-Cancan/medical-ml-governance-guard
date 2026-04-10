#!/usr/bin/env python3
"""
NHANES Codebook RAG — Retrieval-Augmented variable validation.

Loads Harvard CCB-HMS NHANES metadata (58K+ variables, 200K+ codebook entries)
and provides lookup/validation for any NHANES variable by code or friendly name.

Usage as library:
    from nhanes_codebook_lookup import NHANESCodebook
    cb = NHANESCodebook("references/nhanes_codebook")
    info = cb.lookup("DIQ172", cycle="2017-2018")
    issues = cb.validate_columns(df, target_col="y")

Usage as CLI:
    python3 scripts/tools/nhanes_codebook_lookup.py \
        --data examples/nhanes_diabetes.csv \
        --codebook-dir references/nhanes_codebook \
        --cycle 2017-2018 \
        --report /tmp/nhanes_rag_report.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Cycle → table suffix mapping ─────────────────────────
_CYCLE_SUFFIX = {
    "2017-2018": "_J",
    "2019-2020": "P_",  # P_ prefix, not suffix
    "2015-2016": "_I",
    "2013-2014": "_H",
    "2011-2012": "_G",
}


class NHANESCodebook:
    """In-memory index of NHANES variable metadata from Harvard CCB-HMS TSVs."""

    def __init__(self, codebook_dir: str, cycle: str = "2017-2018") -> None:
        self.codebook_dir = Path(codebook_dir)
        self.cycle = cycle
        self._variables: Dict[str, Dict[str, Any]] = {}
        self._codebooks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        vars_path = self.codebook_dir / "nhanes_variables.tsv"
        cb_path = self.codebook_dir / "nhanes_variables_codebooks.tsv"
        if not vars_path.exists() or not cb_path.exists():
            return
        self._load_variables(vars_path)
        self._load_codebooks(cb_path)
        self._loaded = True

    def _match_cycle(self, table: str) -> bool:
        """Check if a table name belongs to the configured cycle."""
        suffix = _CYCLE_SUFFIX.get(self.cycle, "_J")
        if self.cycle == "2019-2020":
            return table.startswith("P_")
        return table.endswith(suffix)

    def _load_variables(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                table = row.get("Table", "")
                if not self._match_cycle(table):
                    continue
                var = row["Variable"]
                if var not in self._variables:
                    self._variables[var] = {
                        "variable": var,
                        "table": table,
                        "sas_label": row.get("SASLabel", ""),
                        "english_text": row.get("EnglishText", ""),
                        "english_instructions": row.get("EnglishInstructions", ""),
                        "target_population": row.get("Target", ""),
                    }

    def _load_codebooks(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                table = (row.get("Table") or "").strip('"')
                if not self._match_cycle(table):
                    continue
                var = (row.get("Variable") or "").strip('"')
                self._codebooks[var].append({
                    "value": (row.get("CodeOrValue") or "").strip('"'),
                    "description": (row.get("ValueDescription") or "").strip('"'),
                    "count": int((row.get("Count") or "0").strip('"') or 0),
                    "cumulative": int((row.get("Cumulative") or "0").strip('"') or 0),
                    "skip_to": (row.get("SkipToItem") or "").strip('"'),
                })

    @property
    def variable_count(self) -> int:
        self._ensure_loaded()
        return len(self._variables)

    def lookup(self, var_code: str) -> Optional[Dict[str, Any]]:
        """Look up a single variable by its NHANES code. Returns enriched info."""
        self._ensure_loaded()
        base = self._variables.get(var_code)
        if base is None:
            return None
        result = dict(base)
        cb_entries = self._codebooks.get(var_code, [])
        result["codebook"] = cb_entries

        # Derive skip patterns
        skip_map = {}
        for entry in cb_entries:
            if entry["skip_to"]:
                skip_map[entry["value"]] = entry["skip_to"]
        result["skip_pattern"] = skip_map if skip_map else None
        result["has_skip_pattern"] = bool(skip_map)

        # Derive missing rate
        total = 0
        missing = 0
        for entry in cb_entries:
            if entry["description"] == "Missing":
                missing = entry["count"]
            total = max(total, entry["cumulative"])
        result["missing_count"] = missing
        result["total_count"] = total
        result["missing_rate"] = round(missing / total, 3) if total > 0 else 0.0

        # Infer variable type from codebook values
        result["inferred_type"] = self._infer_type(cb_entries)

        return result

    def _infer_type(self, cb_entries: List[Dict[str, Any]]) -> str:
        """Infer variable type from codebook value descriptions."""
        descriptions = [e["description"] for e in cb_entries if e["description"] != "Missing"]
        values = [e["value"] for e in cb_entries if e["description"] != "Missing"]

        if any("Range of Values" in d for d in descriptions):
            return "continuous"
        if set(descriptions) - {"Missing"} <= {"Yes", "No", "Refused", "Don't know"}:
            return "binary"
        if len(descriptions) <= 2:
            return "binary"
        # Check if values are pure numeric codes
        non_special = [v for v in values if v not in (".", "7", "9", "77", "99", "777", "999")]
        if len(non_special) <= 10:
            return "categorical"
        return "continuous"

    def validate_columns(
        self,
        column_names: List[str],
        target_col: str = "y",
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate a list of column names against the NHANES codebook.

        Returns a list of issue dicts compatible with gate framework.
        """
        self._ensure_loaded()
        issues: List[Dict[str, Any]] = []

        for col in column_names:
            if col == target_col:
                continue

            # Try exact match first
            info = self.lookup(col)

            # Skip if already in manual registry (manual has priority)
            if manual_registry and col in manual_registry:
                continue

            if info is None:
                # Try reverse lookup from friendly name
                info = self._reverse_lookup(col)

            if info is None:
                continue

            var_code = info["variable"]

            # Check 1: Gated missingness (skip pattern + high missing)
            if info["has_skip_pattern"] and info["missing_rate"] > 0.10:
                issues.append({
                    "code": "CODEBOOK_GATED_MISSINGNESS",
                    "message": (
                        f"Column '{col}' maps to NHANES variable '{var_code}' "
                        f"({info['sas_label']}). This variable has skip patterns "
                        f"(skip_to: {info['skip_pattern']}) and "
                        f"{info['missing_rate']:.0%} missing values. "
                        f"NaN likely means 'question not asked' (gated), "
                        f"not 'value unknown'."
                    ),
                    "details": {
                        "column": col,
                        "var_code": var_code,
                        "sas_label": info["sas_label"],
                        "skip_pattern": info["skip_pattern"],
                        "missing_rate": info["missing_rate"],
                        "source": "nhanes_rag_auto",
                    },
                })

            # Check 2: Categorical variable type
            if info["inferred_type"] == "categorical":
                issues.append({
                    "code": "CODEBOOK_ENCODING_CHECK",
                    "message": (
                        f"Column '{col}' maps to NHANES '{var_code}' "
                        f"({info['sas_label']}), inferred as categorical. "
                        f"Verify encoding: if nominal, use one-hot; "
                        f"if ordinal, document the ordering rationale."
                    ),
                    "details": {
                        "column": col,
                        "var_code": var_code,
                        "inferred_type": "categorical",
                        "codebook_values": [
                            {"value": e["value"], "description": e["description"]}
                            for e in info["codebook"]
                            if e["description"] not in ("Missing", "Range of Values")
                        ][:10],
                        "source": "nhanes_rag_auto",
                    },
                })

        return issues

    def _reverse_lookup(self, friendly_name: str) -> Optional[Dict[str, Any]]:
        """Try to find a variable by its SAS label.

        Uses strict matching: the full friendly name (with underscores→spaces)
        must exactly equal the SAS label. Substring matching produces too many
        false positives (e.g. 'ever_smoked' → 'Ever smoked a cigar').
        """
        fn_lower = friendly_name.lower().replace("_", " ")
        for var_code, info in self._variables.items():
            label_lower = info["sas_label"].lower()
            if fn_lower == label_lower:
                return self.lookup(var_code)
        return None

    def summarize(self) -> Dict[str, Any]:
        """Return summary statistics about the loaded codebook."""
        self._ensure_loaded()
        skip_count = sum(1 for v in self._variables if self._codebooks.get(v) and
                         any(e.get("skip_to") for e in self._codebooks[v]))
        return {
            "cycle": self.cycle,
            "total_variables": len(self._variables),
            "with_codebook_entries": len(self._codebooks),
            "with_skip_patterns": skip_count,
            "loaded": self._loaded,
        }


# ── CLI ──────────────────────────────────────────────────

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="NHANES Codebook RAG lookup.")
    parser.add_argument("--data", help="Path to CSV — validate all columns.")
    parser.add_argument("--var", help="Look up a single variable by code.")
    parser.add_argument("--codebook-dir", default="references/nhanes_codebook",
                        help="Path to directory containing Harvard TSV files.")
    parser.add_argument("--cycle", default="2017-2018", help="NHANES cycle.")
    parser.add_argument("--report", help="Write JSON report to this path.")
    parser.add_argument("--registry", default="",
                        help="Path to manual codebook registry (for priority lookup).")
    args = parser.parse_args()

    cb = NHANESCodebook(args.codebook_dir, cycle=args.cycle)

    if not cb._loaded and not (Path(args.codebook_dir) / "nhanes_variables.tsv").exists():
        print(f"[ERROR] Codebook TSV files not found in {args.codebook_dir}.", file=sys.stderr)
        print("Run: curl -sL -o references/nhanes_codebook/nhanes_variables.tsv "
              '"https://raw.githubusercontent.com/ccb-hms/NHANES-metadata/master/metadata/nhanes_variables.tsv"',
              file=sys.stderr)
        return 1

    # Single variable lookup
    if args.var:
        info = cb.lookup(args.var)
        if info is None:
            print(f"Variable '{args.var}' not found in {args.cycle} cycle.")
            return 1
        print(json.dumps(info, indent=2, default=str))
        return 0

    # CSV column validation
    if args.data:
        import pandas as pd
        df = pd.read_csv(args.data, nrows=0)
        columns = list(df.columns)

        manual_reg = None
        if args.registry:
            reg_path = Path(args.registry)
            if reg_path.exists():
                with reg_path.open() as f:
                    reg = json.load(f)
                ds = reg.get("datasets", {}).get("nhanes_2017_2020", {})
                manual_reg = ds.get("variables", {})

        issues = cb.validate_columns(columns, manual_registry=manual_reg)

        summary = cb.summarize()
        summary["csv"] = str(args.data)
        summary["columns_checked"] = len(columns)
        summary["issues_found"] = len(issues)

        result = {"summary": summary, "issues": issues}

        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            with open(args.report, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Report written to {args.report}")

        # Print summary
        print(f"NHANES Codebook RAG ({args.cycle}): {summary['total_variables']} variables loaded")
        print(f"Checked {len(columns)} columns → {len(issues)} issues found")
        for issue in issues:
            print(f"  [{issue['code']}] {issue['message'][:120]}...")

        return 0

    # Default: print codebook summary
    summary = cb.summarize()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
