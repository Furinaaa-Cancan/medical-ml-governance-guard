"""Base rule class — all rules inherit from this."""

from __future__ import annotations

import ast
from typing import List

from mlgg_lint.ast_utils import ImportMap, TaintTracker
from mlgg_lint.models import Diagnostic, Location, Severity


class BaseRule(ast.NodeVisitor):
    """Abstract base for all lint rules.

    Subclasses must set class-level ``id``, ``name``, ``severity``,
    ``description``, and ``remediation``.  Override ``visit_*`` methods
    to inspect AST nodes.
    """

    id: str = ""
    name: str = ""
    severity: Severity = Severity.ERROR
    description: str = ""
    remediation: str = ""
    tags: tuple[str, ...] = ()

    def __init__(
        self,
        file_path: str,
        import_map: ImportMap,
        taint_tracker: TaintTracker,
    ) -> None:
        self.file_path = file_path
        self.import_map = import_map
        self.taint = taint_tracker
        self._diagnostics: List[Diagnostic] = []

    @property
    def diagnostics(self) -> List[Diagnostic]:
        return self._diagnostics

    def report(
        self,
        node: ast.AST,
        message: str,
        *,
        end_node: ast.AST | None = None,
        **details: object,
    ) -> None:
        """Record a diagnostic at the given AST node."""
        loc = Location(
            file=self.file_path,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
            end_line=getattr(end_node or node, "end_lineno", None),
            end_col=getattr(end_node or node, "end_col_offset", None),
        )
        self._diagnostics.append(
            Diagnostic(
                rule_id=self.id,
                rule_name=self.name,
                severity=self.severity,
                message=message,
                location=loc,
                remediation=self.remediation,
                details=dict(details) if details else {},
            )
        )

    def check(self, tree: ast.Module) -> List[Diagnostic]:
        """Run this rule on the AST and return diagnostics."""
        self._diagnostics = []  # reset to prevent accumulation across calls
        self._tree = tree
        self.visit(tree)
        self.finalize()
        return self._diagnostics

    def finalize(self) -> None:
        """Post-traversal hook. Override for two-pass rules."""
