"""Codebook factory — unified dispatch for dataset-specific codebook validation.

Resolves the appropriate codebook class based on survey source:
  NHANES  → NHANESCodebook (Harvard TSV + BM25 + skip-chain MNAR)
  UKB     → UKBCodebook (SQLite + instance-participation MNAR)
  BRFSS/MIMIC/other → RegistryCodebook (JSON registry only)

Usage:
    from scripts.codebooks.codebook_factory import get_codebook

    cb = get_codebook("ukb")
    issues = cb.validate_columns_for_gate(columns, target_col="p2443_i0")
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_DS_KEY_MAP = {
    "nhanes": "nhanes_2017_2020",
    "brfss": "brfss_2022",
    "nhis": "nhis_2022",
    "mimic": "mimic_iv",
    "ukb": "ukb",
    "ukbiobank": "ukb",
    "biobank": "ukb",
}


_DATASET_KEY_TO_CYCLE = {
    "nhanes_2017_2020": "2017-2018",
    "nhanes_2019_2020": "2019-2020",
    "nhanes_2021_2023": "2021-2022",
    "nhanes_2015_2016": "2015-2016",
    "nhanes_2013_2014": "2013-2014",
}


def get_codebook(
    survey_source: str,
    registry_path: str = "",
    nhanes_codebook_dir: str = "",
    ukb_codebook_db: str = "",
    nhanes_cycle: str = "",
) -> Optional[Any]:
    """Factory: return the appropriate codebook for a dataset.

    All returned codebook objects support:
      - validate_columns_for_gate(columns, target_col, manual_registry) → List[Dict]
      - task_aware_validate(column_names, target_col, target_disease, disease_kb_path, manual_registry) → List[Dict]
      - variable_count (property) → int

    Args:
        nhanes_cycle: Explicit NHANES cycle (e.g., "2017-2018", "2019-2020").
            If empty, auto-detects from dataset_key or defaults to "2017-2018".
    """
    if not registry_path:
        registry_path = str(REPO_ROOT / "references" / "codebooks" / "dataset-codebook-registry.json")
    if not nhanes_codebook_dir:
        nhanes_codebook_dir = str(REPO_ROOT / "references" / "codebooks" / "nhanes")
    if not ukb_codebook_db:
        ukb_codebook_db = str(REPO_ROOT / "references" / "codebooks" / "ukb" / "ukb_codebook.sqlite")

    source_lower = survey_source.lower().strip()
    dataset_key = _DS_KEY_MAP.get(source_lower, "")
    if not dataset_key:
        return None

    # ── NHANES ──────────────────────────────────────────────────────
    if source_lower == "nhanes":
        nhanes_dir = Path(nhanes_codebook_dir)
        cycle = nhanes_cycle or _DATASET_KEY_TO_CYCLE.get(dataset_key, "2017-2018")
        if (nhanes_dir / "nhanes_variables.tsv").exists():
            try:
                from scripts.codebooks.nhanes_codebook_lookup import NHANESCodebook
                return NHANESCodebook(str(nhanes_dir), cycle=cycle)
            except ImportError:
                pass
        # Fallback to registry
        try:
            from scripts.codebooks.nhanes_codebook_lookup import RegistryCodebook
            return RegistryCodebook(registry_path, dataset_key)
        except ImportError:
            return None

    # ── UK Biobank ──────────────────────────────────────────────────
    if source_lower in ("ukb", "ukbiobank", "biobank"):
        ukb_db = Path(ukb_codebook_db)
        if ukb_db.exists():
            try:
                from scripts.codebooks.ukb_codebook_lookup import UKBCodebook
                return UKBCodebook(ukb_db)
            except ImportError:
                pass
        return None

    # ── Other (BRFSS, MIMIC, etc.) ──────────────────────────────────
    try:
        from scripts.codebooks.nhanes_codebook_lookup import RegistryCodebook
        return RegistryCodebook(registry_path, dataset_key)
    except ImportError:
        return None
