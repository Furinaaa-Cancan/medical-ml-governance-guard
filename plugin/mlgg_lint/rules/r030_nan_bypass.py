"""R030: Verdict-path NaN bypass via bare ``float(...)`` in comparisons.

W15-A3 finding: gate verdict paths use ``float(metric) > float(threshold)``
in pass/fail decisions. When ``metric`` is NaN, ``float(nan) > x`` evaluates
to ``False``, so the failure branch is skipped — the gate silently passes
garbage rather than failing closed.

This rule flags any ``Compare`` node in a gate-verdict file where the LHS
or any comparator is a bare ``float(...)`` call on a non-constant
expression. The fix is to wrap through ``to_float()`` (which guards with
``math.isfinite``) or to add an explicit ``math.isfinite`` check before
the comparison.

**Scope — INTERNAL / SELF-AUDIT ONLY.** R030 fires *only* on files whose
path lies under ``scripts/gates/`` (see ``_is_in_gate_scope`` and the
early ``return []`` in ``check``). Those files are MLGG's *own* gate
implementations, so R030 is a self-audit rule that polices this project's
verdict code — it can NEVER fire on external/user-supplied code, which by
definition does not live under our ``scripts/gates/`` tree.

Rule-count framing note: R030 is included in the user-facing "30 rules
(R001–R030)" count even though, for an external user linting their own
code, it is structurally inert (always returns ``[]``). The count is the
size of the registered ruleset, not the set of rules reachable on
arbitrary input; R030 is honestly described here as internal-only so the
advertised number is not mistaken for "30 rules that can fire on your
code." Verdict logic is concentrated under ``scripts/gates/``;
serialization/reporting sites elsewhere (e.g. ``scripts/diagnostics/``)
legitimately use ``float()`` to coerce values into JSON-safe form and do
NOT take pass/fail decisions on the result. This scoping future-proofs
ALL of *our* gates without forcing a churny refactor of the serialization
surface — and is deliberately NOT broadened to user code, where bare
``float()`` in a comparison carries no verdict-bypass guarantee.

**Out of scope (W15-A3 acknowledged gaps).** ``int(x)``, ``np.float64(x)``,
and multi-step coercion (``y = float(x); if y > t``) are not flagged.
A1 covers the dominant pattern (inline ``float(...)`` in verdict
comparisons) — extending coverage is a future-rule concern.
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


# Comparison operators that participate in verdict logic. Identity ops
# (Is, IsNot) and membership ops (In, NotIn) are not numeric comparisons
# and are skipped.
_VERDICT_OPS = (
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
)


def _is_in_gate_scope(file_path: str) -> bool:
    """Return True iff ``file_path`` is under ``scripts/gates/``.

    Accepts both POSIX and Windows separators so the rule works on the
    display paths emitted by the engine on either platform.
    """
    # Normalise to forward-slash form for substring matching.
    pure = PurePosixPath(file_path.replace("\\", "/"))
    parts = pure.parts
    for i in range(len(parts) - 1):
        if parts[i] == "scripts" and parts[i + 1] == "gates":
            return True
    # Also accept absolute paths that include the segment.
    return "/scripts/gates/" in str(pure) or str(pure).startswith("scripts/gates/")


def _is_bare_float_call(node: ast.AST) -> bool:
    """Return True iff ``node`` is ``float(<non-constant>)``.

    Excludes:
      * ``float(<Constant>)`` — parse-time literal, cannot be NaN unless
        the literal itself is NaN (which would be intentional).
      * Calls with keyword arguments or ``*args`` (not the verdict
        pattern we're hunting).
      * Method calls like ``np.float64(x)`` — by design (out-of-scope
        per the rule's docstring).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Name) and func.id == "float"):
        return False
    if len(node.args) != 1 or node.keywords:
        return False
    arg = node.args[0]
    # Skip literal-constant args: float(0.5), float("0.5"), float(None) etc.
    # These cannot silently bypass at runtime — either they're safe or they
    # raise at parse-equivalent time.
    if isinstance(arg, ast.Constant):
        return False
    return True


def _contains_bare_float_call(node: ast.AST, _depth: int = 0) -> bool:
    """Return True iff ``node`` contains a bare ``float(<non-constant>)``
    that can plausibly drive a verdict bypass.

    Recurses through ``BinOp`` (e.g. ``float(max) - float(min) > eps``),
    ``UnaryOp`` (e.g. ``-float(x) > t``), and ``Call(abs, ...)`` so that
    the W15-A3-style ``abs(float(x)) > thresh`` and ``float(a) - float(b)
    > eps`` get caught.  Hard depth cap prevents pathological recursion
    on adversarial input.
    """
    if _depth > 8:
        return False
    if _is_bare_float_call(node):
        return True
    if isinstance(node, ast.BinOp):
        return _contains_bare_float_call(node.left, _depth + 1) or (
            _contains_bare_float_call(node.right, _depth + 1)
        )
    if isinstance(node, ast.UnaryOp):
        return _contains_bare_float_call(node.operand, _depth + 1)
    if isinstance(node, ast.Call):
        # ``abs(float(x))`` — only descend one arg into well-known passthroughs
        # so we don't false-positive on functions that themselves NaN-guard.
        if isinstance(node.func, ast.Name) and node.func.id in {"abs", "round"}:
            if len(node.args) >= 1:
                return _contains_bare_float_call(node.args[0], _depth + 1)
    return False


@register
class NanBypassInVerdict(BaseRule):
    """Flag ``float(x) <op> y`` in gate verdict comparisons (R030).

    Internal/self-audit-only rule: fires solely on ``scripts/gates/`` paths
    (MLGG's own gate code) and returns ``[]`` for all other files, so it
    cannot fire on external user code. See module docstring for how this
    relates to the user-facing "30 rules" count.
    """

    id = "R030"
    name = "nan-bypass-in-verdict"
    severity = Severity.ERROR
    description = (
        "Verdict-path comparison wraps an operand in bare float(...) — "
        "if the operand is NaN, the comparison silently returns False and "
        "the gate's failure branch is skipped, letting garbage pass."
    )
    remediation = (
        "Wrap the operand in to_float() (which guards with math.isfinite) "
        "or add an explicit `if not math.isfinite(value): fail` check "
        "before the comparison. Verdict gates must fail closed on NaN."
    )
    tags = ("governance", "verdict", "nan-safety")

    def check(self, tree: ast.Module) -> list:
        # Scope-gate: only run inside scripts/gates/. Cheaper than
        # walking the tree just to discard every diagnostic.
        if not _is_in_gate_scope(self.file_path):
            return []
        return super().check(tree)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        # Only fire on numeric/equality ops that drive verdict branches.
        if not any(isinstance(op, _VERDICT_OPS) for op in node.ops):
            self.generic_visit(node)
            return

        flagged: list[ast.AST] = []
        # LHS — also catches ``abs(float(x))`` and ``float(a) - float(b)``.
        if _contains_bare_float_call(node.left):
            flagged.append(node.left)
        # Comparators (chained comparisons like ``lo < float(x) < hi``)
        for comparator in node.comparators:
            if _contains_bare_float_call(comparator):
                flagged.append(comparator)

        if flagged:
            # Single diagnostic per Compare node — we don't multi-report
            # on the same comparison even when both sides are wrapped.
            self.report(
                node,
                (
                    f"Comparison at line {node.lineno} wraps {len(flagged)} "
                    "operand(s) in bare float(...); a NaN value will silently "
                    "evaluate the comparison to False and bypass the verdict "
                    "branch. Use to_float() (math.isfinite-guarded) or add "
                    "an explicit finiteness check before comparing."
                ),
                operand_count=len(flagged),
            )
        self.generic_visit(node)
