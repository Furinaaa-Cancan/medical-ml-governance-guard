"""R028: Omics/genomic feature prefix detected — out of scope for MLGG."""

from __future__ import annotations

import ast
import re

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_OMICS_PATTERNS = (
    re.compile(r"^gene_", re.IGNORECASE),
    re.compile(r"^probe_", re.IGNORECASE),
    re.compile(r"^snp_", re.IGNORECASE),
    re.compile(r"^cpg_", re.IGNORECASE),
    re.compile(r"^rs\d+$", re.IGNORECASE),
    re.compile(r"^ENSG\d+", re.IGNORECASE),
    re.compile(r"^ENST\d+", re.IGNORECASE),
)

_MIN_COUNT = 3


@register
class OmicsFeaturePrefix(BaseRule):
    id = "R028"
    name = "omics-feature-prefix"
    severity = Severity.ERROR
    description = (
        "Feature names match omics modality patterns (gene_/probe_/snp_/cpg_/rs#/ENSG). "
        "MLGG is calibrated for retrospective-cohort EHR tabular data; omics "
        "modalities need governance MLGG does not cover (batch effects, "
        "donor-vs-cell split, 5e-8 GWAS threshold, population stratification)."
    )
    remediation = (
        "Use an omics-native toolchain: Scanpy/scVI (scRNA-seq), "
        "TCGAbiolinks + limma/DESeq2 (TCGA bulk), PLINK + GCTA (GWAS). "
        "If you must predict clinical outcomes from signatures, aggregate to a "
        "handful of scores (PRS, PAM50, risk index) before feeding MLGG."
    )
    tags = ("modality", "scope")

    def visit_List(self, node: ast.List) -> None:  # noqa: N802
        omics_names: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                if self._matches_omics(elt.value):
                    omics_names.append(elt.value)
        if len(omics_names) >= _MIN_COUNT:
            sample = ", ".join(f"'{n}'" for n in omics_names[:3])
            self.report(
                node,
                f"Feature list contains {len(omics_names)} omics-pattern names "
                f"(e.g., {sample}) — MLGG scope is retrospective-cohort EHR "
                f"tabular data. Use a native omics toolchain instead.",
            )
        self.generic_visit(node)

    @staticmethod
    def _matches_omics(name: str) -> bool:
        return any(p.match(name) for p in _OMICS_PATTERNS)
