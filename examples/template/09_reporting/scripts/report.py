"""
Phase 9: Reporting

Checkpoint (MLGG):
  - TRIPOD+AI 2024 checklist completed? (MLGG-T01)
  - Limitations discussed?
  - External validation recommended if not performed?

Input:  All previous phase results
Output: 09_reporting/results/, outputs/tables/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import pandas as pd


TRIPOD_AI_ITEMS = [
    ("1", "Title", "Identify as prediction model study; specify development/validation"),
    ("2", "Abstract", "Structured summary including objective, data, methods, results"),
    ("3a", "Background", "Explain medical context and rationale"),
    ("3b", "Objectives", "Specify study objective (development, validation, or both)"),
    ("4a", "Source of data", "Describe data sources, settings, dates"),
    ("4b", "Prediction time point", "Define index date and prediction horizon"),
    ("5", "Participants", "Describe eligibility criteria and cohort"),
    ("6a", "Outcome", "Define outcome and how it was measured"),
    ("6b", "Predictors", "List all candidate predictors"),
    ("7a", "Sample size", "Explain sample size and EPV"),
    ("7b", "Missing data", "Describe how missing data was handled"),
    ("8", "Statistical methods", "Describe modeling approach, validation, metrics"),
    ("9", "Risk groups", "Describe any risk group categorization"),
    ("10a", "Participants flow", "Number at each stage, with exclusions"),
    ("10b", "Demographics", "Summary of participant characteristics"),
    ("11", "Model development", "Present full model specification"),
    ("12", "Model performance", "Report discrimination and calibration"),
    ("13", "Updating", "Report any model updating if applicable"),
    ("14", "Discussion", "Key findings, limitations, implications"),
    ("15a", "Limitations", "Discuss limitations"),
    ("15b", "Interpretation", "Give overall interpretation"),
    ("16", "Implications", "Discuss clinical implications"),
    ("17", "Supplementary", "Provide supplementary information"),
    ("18", "Registration", "Registration information if applicable"),
    ("19", "Data/code sharing", "Source of data and code availability"),
]


def generate_checklist():
    """Generate TRIPOD+AI 2024 checklist with status."""
    rows = []
    for item_id, item_name, description in TRIPOD_AI_ITEMS:
        rows.append({
            "Item": item_id,
            "Name": item_name,
            "Description": description,
            "Status": "TODO",
            "Location": "",
        })
    return pd.DataFrame(rows)


def collect_limitations():
    """Collect known limitations from the analysis."""
    limitations = [
        "Single-center / single-dataset study — external validation not performed",
        "Retrospective data — subject to selection and information bias",
        "Missing data handled via imputation — results may differ under alternative strategies",
        "Threshold selected on validation set — may not generalize to different populations",
        "SHAP values may spread importance across correlated features",
    ]
    # TODO: Add dataset-specific limitations
    return pd.DataFrame({"limitation": limitations})


def main():
    cfg.REPORTING_RESULTS.mkdir(parents=True, exist_ok=True)
    cfg.OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)

    # TRIPOD+AI checklist
    checklist = generate_checklist()
    checklist.to_csv(cfg.OUTPUT_TABLES / "tripod_ai_checklist.csv", index=False)
    print(f"TRIPOD+AI checklist: {len(checklist)} items")

    # Limitations
    limitations = collect_limitations()
    limitations.to_csv(cfg.OUTPUT_TABLES / "limitations.csv", index=False)

    print(f"\nPhase 9 complete. Results in {cfg.REPORTING_RESULTS}/")
    print("--- Checkpoint ---")
    print("[ ] TRIPOD+AI 2024 checklist completed? (MLGG-T01)")
    print("[ ] All limitations discussed?")
    print("[ ] External validation status documented?")
    print("[ ] DCA clinical utility honestly reported?")


if __name__ == "__main__":
    main()
