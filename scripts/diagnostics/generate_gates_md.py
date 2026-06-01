#!/usr/bin/env python3
"""Auto-generate ``docs/reference/GATES.md`` from the gate registry.

The hand-maintained ``GATES.md`` (W12-B1) drifted from ``_gate_registry.py``
immediately after creation (README_EN listed ``ci_matrix_gate`` in Layer 6
while the registry has it in Layer 5). To prevent that class of drift from
re-occurring every time a gate is added, moved, or renamed, this script
regenerates ``GATES.md`` deterministically from three sources of truth:

1. ``scripts/core/_gate_registry.py`` — gate name, layer, dependencies,
   report basename, ``rag_optional`` flag, ``aggregation_flag``.
2. The gate module docstring — first non-empty line becomes the one-liner
   description column.
3. AST scan of the gate module — list of failure codes passed as the second
   positional argument to ``add_issue(...)``, plus detection of the
   ``--strict`` CLI flag.

The script reads its static intro (title, CLI contract, rule-code mapping)
from ``docs/reference/_gates_md_preamble.md`` so the human-curated text is
preserved and reviewable, while every per-layer table and per-gate row is
mechanically derived from the registry and gate sources.

CLI:

    python3 scripts/diagnostics/generate_gates_md.py
        # Regenerate docs/reference/GATES.md in place.

    python3 scripts/diagnostics/generate_gates_md.py --check
        # Exit 0 if the committed GATES.md matches the freshly generated
        # output; exit 1 (with a unified diff on stderr) if it has drifted.
        # Intended for CI / pre-commit. Same spirit as ``terraform fmt -check``.

    python3 scripts/diagnostics/generate_gates_md.py --stdout
        # Print to stdout instead of writing the file (useful for diffing
        # by hand).

Exit codes:
    0 — success (write mode) or no drift (check mode).
    1 — drift detected (check mode), or unrecoverable error.

This script intentionally has no third-party dependencies; the stdlib's
``ast`` module is sufficient for the heuristic failure-code scan.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = ROOT / "scripts"
GATES_DIR = SCRIPTS_DIR / "gates"
PREAMBLE_PATH = ROOT / "docs" / "reference" / "_gates_md_preamble.md"
OUTPUT_PATH = ROOT / "docs" / "reference" / "GATES.md"

# Ensure scripts/core is importable for _gate_registry.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Imported after sys.path manipulation; the registry is a pure-data module
# that does not import any gate code, so this is safe.
from core._gate_registry import GATE_REGISTRY, GateLayer, get_execution_layers  # noqa: E402


# ---------------------------------------------------------------------------
# Gate-source extraction (docstrings, failure codes, --strict flag)
# ---------------------------------------------------------------------------


def _gate_source_path(gate_name: str) -> Optional[Path]:
    """Resolve the on-disk path for a gate module from its registry entry."""
    spec = GATE_REGISTRY.get(gate_name)
    if spec is None:
        return None
    # spec.script is e.g. "gates/leakage_gate.py", relative to scripts/.
    candidate = SCRIPTS_DIR / spec.script
    return candidate if candidate.exists() else None


def _extract_one_liner(module_source: str) -> str:
    """Return the first non-empty line of the module-level docstring."""
    try:
        tree = ast.parse(module_source)
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_failure_codes(module_source: str) -> List[str]:
    """Heuristically extract failure codes emitted by the gate.

    Strategy: walk the AST for calls of the form ``add_issue(<bucket>,
    "<code>", ...)`` — the shared helper from ``scripts/core/_gate_utils``
    that every gate uses to register a finding. The second positional
    argument is the failure code by convention. Also picks up
    ``register_remediations({"<code>": "..."})`` keys, which document the
    full set of codes the gate may emit even when only a subset are
    triggered on a given run.

    Returns a sorted, deduplicated list. Empty list is fine — a few gates
    delegate to subroutines that issue codes indirectly; the gate source
    remains the authoritative reference.
    """
    try:
        tree = ast.parse(module_source)
    except SyntaxError:
        return []

    codes: set[str] = set()

    for node in ast.walk(tree):
        # add_issue(bucket, "code_string", ...)
        if isinstance(node, ast.Call):
            func = node.func
            func_name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if func_name == "add_issue" and len(node.args) >= 2:
                second = node.args[1]
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    codes.add(second.value)
            elif func_name == "register_remediations" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Dict):
                    for key in first.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            codes.add(key.value)

    return sorted(codes)


def _has_strict_flag(module_source: str) -> bool:
    """Detect whether the gate accepts a ``--strict`` CLI flag.

    A simple substring scan is sufficient: every MLGG gate that supports
    strict mode literally writes ``"--strict"`` in an ``argparse``
    ``add_argument`` call. A handful of helper modules mention ``strict``
    in prose; the literal ``"--strict"`` (with surrounding quotes) is far
    more specific and produces no false positives across the 33 gates.
    """
    return '"--strict"' in module_source or "'--strict'" in module_source


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _md_escape_cell(text: str) -> str:
    """Make a string safe to drop into a Markdown table cell."""
    if not text:
        return "—"
    # Escape pipe characters that would break the column.
    return text.replace("|", "\\|").replace("\n", " ")


#: Cap the per-gate failure-codes column at this many entries before
#: truncating; gates like ``request_contract_gate`` can emit 80+ codes and
#: an unbounded list makes the Markdown table unreadable. The full set is
#: still available in the gate source (linked from the Module column).
_FAILURE_CODES_DISPLAY_CAP = 8


def _render_failure_codes_cell(codes: List[str]) -> str:
    """Render the failure-codes list as ``inline code, comma-separated``.

    Caps the visible list at ``_FAILURE_CODES_DISPLAY_CAP`` codes and
    appends a ``(+N more)`` annotation when truncated so reviewers know to
    consult the gate source for the complete enumeration.
    """
    if not codes:
        return "—"
    if len(codes) <= _FAILURE_CODES_DISPLAY_CAP:
        return ", ".join(f"`{c}`" for c in codes)
    head = codes[:_FAILURE_CODES_DISPLAY_CAP]
    extra = len(codes) - _FAILURE_CODES_DISPLAY_CAP
    return ", ".join(f"`{c}`" for c in head) + f" (+{extra} more)"


def _depends_cell(deps: frozenset) -> str:
    if not deps:
        return "—"
    return ", ".join(f"`{d}`" for d in sorted(deps))


def _layer_table(layer_value: int, gate_names: List[str]) -> str:
    """Render one Markdown subsection (heading + table) for a layer."""
    layer_enum = GateLayer(layer_value)
    layer_label = layer_enum.name
    parallel_count = sum(
        1 for n in gate_names if GATE_REGISTRY[n].parallelizable
    )
    # Show a "(N parallel)" hint only when the layer has multiple gates AND
    # at least one of them is marked parallelizable. Layers like FINAL hold
    # serialized aggregation gates whose count is informative on its own.
    if len(gate_names) > 1 and parallel_count > 0:
        suffix = f" ({parallel_count} parallel)"
    elif len(gate_names) > 1:
        suffix = f" ({len(gate_names)} serial)"
    else:
        suffix = ""

    lines: List[str] = []
    lines.append(f"### Layer {layer_value} — `{layer_label}`{suffix}")
    lines.append("")
    lines.append(
        "| Gate | Module | Description | Depends on | Report | Failure codes | `--strict` | `rag_optional` |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|"
    )
    for name in gate_names:
        spec = GATE_REGISTRY[name]
        source_path = _gate_source_path(name)
        if source_path is None:
            one_liner = ""
            codes: List[str] = []
            strict = False
            module_link = f"`{spec.script}`"
        else:
            src = source_path.read_text(encoding="utf-8")
            one_liner = _extract_one_liner(src)
            codes = _extract_failure_codes(src)
            strict = _has_strict_flag(src)
            module_link = (
                f"[{source_path.name}](../../{source_path.relative_to(ROOT).as_posix()})"
            )

        report_cell = f"`{spec.report_output}`" if spec.report_output else "—"
        rag_cell = "True" if spec.rag_optional else "False"
        strict_cell = "Yes" if strict else "No"

        row = (
            f"| `{name}` | {module_link} | {_md_escape_cell(one_liner)} | "
            f"{_depends_cell(spec.depends_on)} | {report_cell} | "
            f"{_render_failure_codes_cell(codes)} | {strict_cell} | {rag_cell} |"
        )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Static appendix (post-tables) — registry-aware blurbs + how-to-run section
# ---------------------------------------------------------------------------


def _render_rag_optional_list() -> str:
    rag_gates = sorted(
        name for name, spec in GATE_REGISTRY.items() if spec.rag_optional
    )
    if not rag_gates:
        return "(no gates currently flagged `rag_optional`)"
    return "\n".join(
        f"- `{name}` — {GATE_REGISTRY[name].category}" for name in rag_gates
    )


def _render_categories_summary() -> str:
    cats: Dict[str, List[str]] = {}
    for name, spec in GATE_REGISTRY.items():
        cats.setdefault(spec.category, []).append(name)
    lines = []
    for cat in sorted(cats):
        gates = sorted(cats[cat])
        lines.append(f"- **{cat}** ({len(gates)}): {', '.join(f'`{g}`' for g in gates)}")
    return "\n".join(lines)


APPENDIX_TEMPLATE = """
---

## Failure code conventions

Failure detail records use a free-form `rule` or `code` field. Convention:

- Methodology rule codes from `README_EN.md` § "33 Methodology Rules" —
  `S01`, `P01`, `F02`, `M04`, `E02`, `Z01`, `R02`, `T01`, `Q01`, etc. Used
  when a finding maps 1:1 to a documented rule.
- Gate-local codes prefixed by gate identifier (e.g.
  `LEAKAGE_ROW_HASH_OVERLAP`, `COHORT_EPV_INSUFFICIENT`) for findings that
  don't have a methodology-rule analogue.
- Aggregator codes (`PUBLICATION_FINGERPRINT_DRIFT`, `SELF_CRITIQUE_*`) for
  results computed only at the aggregation / final layers.

Severity values: `ERROR` (always fails), `WARNING` (fails only under
`--strict`), `INFO` (never fails, surfaced in the report for context).
The exact failure-code list per gate is auto-extracted into the tables
above by AST-scanning `add_issue(...)` calls and `register_remediations(...)`
keys; the gate source remains authoritative when the heuristic misses a
dynamically-constructed code.

---

## Gate categories (registry-derived)

{categories_summary}

---

## Aggregation and meta gates

`publication_gate` and `security_audit_gate` consume the upstream JSON
envelopes via the per-gate `aggregation_flag` declared in the registry
(e.g. `--leakage-report`, `--clinical-metrics-report`). The full mapping is
generated automatically by `scripts/orchestration/run_dag_pipeline.py` from
`GATE_REGISTRY`, so adding a new gate only requires:

1. `_register(GateSpec(...))` in `_gate_registry.py`.
2. Implementing the gate module under `scripts/gates/<name>.py`.
3. Adding the gate's `aggregation_flag` to whichever aggregator must consume
   it (typically `publication_gate`).
4. Re-running `python3 scripts/diagnostics/generate_gates_md.py` to refresh
   this document (CI verifies via `--check`).

The `rag_optional` flag controls one specific UX detail: when set, the
[`gate_rag_bridge`](../../scripts/core/gate_rag_bridge.py) suppresses the
"no related peer-review concerns retrieved" placeholder for an empty result
set. Silence is more honest than a placeholder that implies "we looked and
found nothing" when the reality is "this gate has no peer-review domain to
look in." Currently set on:

{rag_optional_list}

---

## Disease KB integration (W11-F2)

A separate diagnostic at
[`scripts/diagnostics/disease_kb_review_check.py`](../../scripts/diagnostics/disease_kb_review_check.py)
enforces clinician sign-off on the LLM-generated disease knowledge base. It
is intentionally NOT registered as a {next_gate_count}th gate, to keep the
"{gate_count} gates" contract referenced across project documentation and
test assertions stable. `publication_gate` calls into it as a fail-closed
prerequisite for L3 publication eligibility; pre-publication callers can
opt out with `--allow-unreviewed-disease-kb` or
`MLGG_ALLOW_UNREVIEWED_DISEASE_KB=1` (not recommended for publication).

---

## Running gates standalone

Every gate is independently executable. Examples:

```bash
# One-off leakage check, fail closed:
python -m scripts.gates.leakage_gate \\
    --train data/train.csv --test data/test.csv \\
    --id-cols patient_id --time-col index_time \\
    --target-col outcome \\
    --report out/leakage_report.json --strict

# Full pipeline via the DAG orchestrator (resolves dependencies, parallelizes):
python -m scripts.orchestration.run_dag_pipeline --request request.json \\
    --report out/pipeline_report.json

# Re-run a single gate through the orchestrator (resolves and runs its
# dependencies first):
python -m scripts.orchestration.run_dag_pipeline --request request.json \\
    --only calibration_dca_gate --report out/pipeline_report.json

# Re-run a single gate in isolation, assuming its dependencies already
# passed (add --no-deps), or invoke its standalone fail-closed CLI directly:
python -m scripts.orchestration.run_dag_pipeline --request request.json \\
    --only calibration_dca_gate --no-deps --report out/pipeline_report.json
python -m scripts.gates.calibration_dca_gate --report out/calibration_dca_report.json --strict
```

Exit codes propagate; CI wraps the orchestrator and treats any `2` as a
release blocker.

---

## Related references

- [LINT_RULES.md](LINT_RULES.md) — static analysis rules that complement
  these runtime gates.
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) — overall system layout.
- [docs/RAG_TROUBLESHOOTING.md](../RAG_TROUBLESHOOTING.md) — RAG bridge ops.
- [docs/KB_TAG_STYLE_GUIDE.md](../KB_TAG_STYLE_GUIDE.md) — KB tag conventions.
- [README_EN.md § 9-Phase Workflow](../../README_EN.md#9-phase-workflow) —
  how gates fit into the end-to-end pipeline.
- [`scripts/core/_gate_registry.py`](../../scripts/core/_gate_registry.py) —
  the registry itself; the authoritative source this document is generated
  from.

---

<!--
  Generated by scripts/diagnostics/generate_gates_md.py.
  Do not hand-edit. Run the generator to refresh; CI checks via --check.
-->
"""


def _render_appendix(gate_count: int) -> str:
    return APPENDIX_TEMPLATE.format(
        categories_summary=_render_categories_summary(),
        rag_optional_list=_render_rag_optional_list(),
        gate_count=gate_count,
        next_gate_count=gate_count + 1,
    )


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def build_markdown() -> str:
    """Build the full GATES.md content as a single string."""
    gate_count = len(GATE_REGISTRY)
    preamble_template = PREAMBLE_PATH.read_text(encoding="utf-8")
    # The preamble is a Markdown file with literal `{gate_count}` placeholders.
    # Use ``str.replace`` rather than ``str.format`` so that other curly braces
    # in the preamble (e.g. JSON examples) are not interpreted as format spec.
    preamble = preamble_template.replace("{gate_count}", str(gate_count))

    parts: List[str] = [preamble.rstrip(), ""]

    for layer_value, gate_names in get_execution_layers():
        parts.append(_layer_table(layer_value, gate_names))

    parts.append(_render_appendix(gate_count).rstrip())
    parts.append("")  # trailing newline
    return "\n".join(parts)


def _write_output(content: str, path: Path) -> None:
    path.write_text(content, encoding="utf-8")


def _safe_display_path(p: Path) -> str:
    """Render ``p`` relative to the repo root when possible, else absolute.

    The tests exercise ``--check`` against paths in ``tmp_path`` which live
    outside the repo; ``Path.relative_to`` would raise on those, so we
    fall back to the absolute path.
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _check_drift(generated: str, committed_path: Path) -> int:
    """Compare generated content against the committed file.

    Returns 0 if identical, 1 if drift (printing a unified diff on stderr).
    """
    if not committed_path.exists():
        print(
            f"[generate_gates_md] --check: committed file {committed_path} "
            f"does not exist; run without --check to create it.",
            file=sys.stderr,
        )
        return 1
    committed = committed_path.read_text(encoding="utf-8")
    if committed == generated:
        return 0
    diff = difflib.unified_diff(
        committed.splitlines(keepends=True),
        generated.splitlines(keepends=True),
        fromfile=f"{committed_path} (committed)",
        tofile=f"{committed_path} (regenerated)",
        n=3,
    )
    sys.stderr.write(
        "[generate_gates_md] DRIFT detected between committed "
        f"{_safe_display_path(committed_path)} and the freshly-generated "
        "output. Run:\n"
        f"    python3 scripts/diagnostics/generate_gates_md.py\n"
        "then commit the regenerated file.\n\n",
    )
    sys.stderr.writelines(diff)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate docs/reference/GATES.md from the gate registry.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the committed GATES.md has drifted "
             "from the freshly-generated output (CI / pre-commit mode).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print regenerated Markdown to stdout instead of writing it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output path (default: {OUTPUT_PATH.relative_to(ROOT)}).",
    )
    args = parser.parse_args(argv)

    if args.check and args.stdout:
        parser.error("--check and --stdout are mutually exclusive.")

    if not PREAMBLE_PATH.exists():
        print(
            f"[generate_gates_md] ERROR: preamble file missing: {PREAMBLE_PATH}",
            file=sys.stderr,
        )
        return 1

    generated = build_markdown()

    if args.stdout:
        sys.stdout.write(generated)
        return 0

    if args.check:
        return _check_drift(generated, args.output)

    _write_output(generated, args.output)
    print(
        f"[generate_gates_md] wrote {_safe_display_path(args.output)} "
        f"({len(GATE_REGISTRY)} gates, {len(get_execution_layers())} layers)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
