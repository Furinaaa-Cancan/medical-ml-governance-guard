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

    # A literal list/tuple/set of ≥3 omics names (the original form).
    def visit_List(self, node: ast.List) -> None:  # noqa: N802
        self._check_sequence(node)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:  # noqa: N802
        self._check_sequence(node)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:  # noqa: N802
        self._check_sequence(node)
        self.generic_visit(node)

    # The common bypass: build the omics columns programmatically, e.g.
    # ``[f"gene_{i}" for i in range(1000)]``. A single such comprehension can
    # generate thousands of omics features, so one omics-pattern element fires.
    def visit_ListComp(self, node: ast.ListComp) -> None:  # noqa: N802
        self._check_comprehension(node)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:  # noqa: N802
        self._check_comprehension(node)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:  # noqa: N802
        self._check_comprehension(node)
        self.generic_visit(node)

    # Dict comprehensions are the same bypass via the KEY expression, e.g.
    # ``{f"gene_{i}": 0 for i in range(1000)}`` builds thousands of omics
    # column names. DictComp has no ``.elt`` — check ``.key`` instead.
    def visit_DictComp(self, node: ast.DictComp) -> None:  # noqa: N802
        name = self._omics_str(node.key)
        if name:
            self.report(
                node,
                f"Dict comprehension generates omics-pattern feature names (e.g., '{name}') — "
                f"a single comprehension can build thousands of omics columns. MLGG scope "
                f"is retrospective-cohort EHR tabular data; use a native omics toolchain.",
            )
        self.generic_visit(node)

    def _check_sequence(self, node) -> None:
        omics_names = [n for n in (self._omics_str(e) for e in node.elts) if n]
        if len(omics_names) >= _MIN_COUNT:
            sample = ", ".join(f"'{n}'" for n in omics_names[:3])
            self.report(
                node,
                f"Feature collection contains {len(omics_names)} omics-pattern names "
                f"(e.g., {sample}) — MLGG scope is retrospective-cohort EHR "
                f"tabular data. Use a native omics toolchain instead.",
            )

    def _check_comprehension(self, node) -> None:
        name = self._omics_str(node.elt)
        if name:
            self.report(
                node,
                f"Comprehension generates omics-pattern feature names (e.g., '{name}') — "
                f"a single comprehension can build thousands of omics columns. MLGG scope "
                f"is retrospective-cohort EHR tabular data; use a native omics toolchain.",
            )

    @classmethod
    def _omics_str(cls, node) -> "str | None":
        """Omics name for a string constant, or an f-string whose literal PREFIX is omics.

        ``f"gene_{i}"`` parses to ``JoinedStr([Constant("gene_"), FormattedValue(...)])`` —
        the leading literal ``"gene_"`` matches ``^gene_``. A dynamic prefix
        (``f"{x}gene_"``) is intentionally NOT matched (conservative: avoids false
        positives where the omics token is not actually the column-name prefix).
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value if cls._matches_omics(node.value) else None
        if isinstance(node, ast.JoinedStr) and node.values:
            lead = node.values[0]
            if isinstance(lead, ast.Constant) and isinstance(lead.value, str) and cls._matches_omics(lead.value):
                return lead.value + "{…}"
        return None

    @staticmethod
    def _matches_omics(name: str) -> bool:
        return any(p.match(name) for p in _OMICS_PATTERNS)
