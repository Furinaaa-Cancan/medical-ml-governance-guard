#!/usr/bin/env python3
"""Regenerate `references/retrieval_eval/scenarios.json` failure_codes
from real source-of-truth: AST-collected ``add_issue(bucket, "<code>", …)``
literals + ``register_remediations({"<code>": …})`` keys in
``scripts/gates/*.py``, with W7 harvest as fallback for codes that only
fire on very narrow runtime paths.

Background (W17-C4 ghost-finding loop):
- W9-C1 measured 7.7 percent overlap between the failure_codes declared
  in scenarios.json and the real codes emitted by gates. Nobody fixed
  it. Eight waves later W17-C4 flagged the same number. This script
  produces the regeneration that closes the loop.

Hard constraint (CLAUDE.md §"NEVER"):
- This script is DRY-RUN ONLY. It NEVER writes to ``references/``.
- Outputs:
    /tmp/W20_C1_scenarios_v2.json   — candidate scenarios with rewritten
                                       failure_codes lists
    /tmp/W20_C1_scenarios_v2_diff.md — per-scenario added/removed/kept
- A human must approve before any commit to ``references/``.

Algorithm per scenario:
1. ``kept``    = scenario.failure_codes ∩ valid_codes(gate)
2. ``removed`` = scenario.failure_codes − valid_codes(gate)  (ghosts)
3. If kept is empty AND the gate has any valid codes, add the top 1–2
   codes from ``valid_codes(gate)`` to seed a non-empty list. Prefer
   harvest-frequency-ranked codes if any, else lex-sorted source codes.
4. ``new_failure_codes`` = sorted(kept + added)

The intent is to ELIMINATE ghosts. We do NOT try to second-guess the
reviewer's semantic intent — kept codes are preserved verbatim. Added
codes are flagged in the diff so a reviewer can sanity-check whether
the seeded code matches the scenario's described failure mode.

Usage:
    python scripts/rag/evals/regen_scenarios.py
    python scripts/rag/evals/regen_scenarios.py --out-json /tmp/foo.json \\
        --out-diff /tmp/foo.md
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATES_DIR = PROJECT_ROOT / "scripts" / "gates"
HARVEST_PATH = (
    PROJECT_ROOT / "references" / "retrieval_eval" / "real_gate_codes_harvest.json"
)
SCENARIOS_PATH = (
    PROJECT_ROOT / "references" / "retrieval_eval" / "scenarios.json"
)


# ──────────────────────────────────────────────────────────────────────
# AST collection
# ──────────────────────────────────────────────────────────────────────


def collect_codes_from_source(source: str) -> Set[str]:
    """Return the set of failure-code string literals declared in a
    single gate-module source string.

    Two patterns are honored:

    1. ``add_issue(<bucket>, "<code>", ...)`` — the 2nd positional arg
       MUST be a bare string literal. Variables (``add_issue(b, code,
       ...)``) are skipped — they cannot be statically resolved.
    2. ``register_remediations({"<code>": "..."}) — every string key in
       a dict literal is treated as a declared code.

    Returns an empty set on SyntaxError (so a single broken gate cannot
    blow up the whole regen pass).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    codes: Set[str] = set()

    class _V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr

            if name == "add_issue" and len(node.args) >= 2:
                second = node.args[1]
                if isinstance(second, ast.Constant) and isinstance(
                    second.value, str
                ):
                    codes.add(second.value)
            elif name in ("register_remediations", "register_remediation"):
                # bulk-dict form
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        for key in arg.keys:
                            if isinstance(key, ast.Constant) and isinstance(
                                key.value, str
                            ):
                                codes.add(key.value)
                    elif isinstance(arg, ast.Constant) and isinstance(
                        arg.value, str
                    ):
                        # register_remediation("code", "hint")
                        codes.add(arg.value)
            self.generic_visit(node)

    _V().visit(tree)
    return codes


def collect_codes_per_gate(gates_dir: Path) -> Dict[str, Set[str]]:
    """Walk ``gates_dir/*.py`` (skipping dunder files) and return
    ``{gate_module_stem: set_of_codes}``.
    """
    out: Dict[str, Set[str]] = {}
    for py in sorted(gates_dir.glob("*.py")):
        if py.name.startswith("_") or py.name == "__init__.py":
            # also skips macOS AppleDouble shadows (._foo.py)
            continue
        try:
            source = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # tolerate stray non-UTF8 files (e.g., resource forks);
            # they cannot be valid Python sources anyway.
            continue
        out[py.stem] = collect_codes_from_source(source)
    return out


# ──────────────────────────────────────────────────────────────────────
# Harvest loader
# ──────────────────────────────────────────────────────────────────────


def load_harvest_codes(harvest_path: Path) -> Dict[str, Dict[str, int]]:
    """Load the W7 harvest. Returns ``{gate_name: {code: frequency}}``.

    Missing file is a non-fatal warning — harvest is a fallback only.
    """
    if not harvest_path.exists():
        print(
            f"warn: harvest not found at {harvest_path}; "
            "regen will rely on source-AST codes only.",
            file=sys.stderr,
        )
        return {}
    data = json.loads(harvest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {
        gate: counts if isinstance(counts, dict) else {}
        for gate, counts in data.items()
    }


# ──────────────────────────────────────────────────────────────────────
# Regen logic
# ──────────────────────────────────────────────────────────────────────


def valid_codes_for_gate(
    gate: str,
    source_codes: Dict[str, Set[str]],
    harvest_codes: Dict[str, Dict[str, int]],
) -> Set[str]:
    """Union of source-AST codes and harvest codes for one gate."""
    return source_codes.get(gate, set()) | set(harvest_codes.get(gate, {}).keys())


def rank_seed_candidates(
    gate: str,
    source_codes: Dict[str, Set[str]],
    harvest_codes: Dict[str, Dict[str, int]],
) -> List[str]:
    """Return up to 2 seed candidates for an empty-after-prune scenario,
    preferring harvest-frequent codes (real-world prevalence), falling
    back to lex-sorted source codes.
    """
    harvested = harvest_codes.get(gate, {})
    by_freq = sorted(harvested.items(), key=lambda kv: (-kv[1], kv[0]))
    seeds: List[str] = [c for c, _ in by_freq[:2]]
    if len(seeds) < 2:
        for c in sorted(source_codes.get(gate, set())):
            if c not in seeds:
                seeds.append(c)
            if len(seeds) >= 2:
                break
    return seeds[:2]


def regen_scenario(
    scenario: dict,
    source_codes: Dict[str, Set[str]],
    harvest_codes: Dict[str, Dict[str, int]],
) -> Tuple[dict, List[str], List[str], List[str]]:
    """Return ``(new_scenario, kept, removed, added)``.

    free_text_probe scenarios (no gate) pass through unchanged.
    """
    new = dict(scenario)
    gate = scenario.get("gate_name")
    if not gate or gate == "free_text_probe":
        return new, list(scenario.get("failure_codes", [])), [], []

    original = list(scenario.get("failure_codes", []))
    valid = valid_codes_for_gate(gate, source_codes, harvest_codes)
    kept = [c for c in original if c in valid]
    removed = [c for c in original if c not in valid]
    added: List[str] = []
    if not kept and valid:
        for c in rank_seed_candidates(gate, source_codes, harvest_codes):
            if c not in kept and c not in added:
                added.append(c)
    new["failure_codes"] = sorted(set(kept) | set(added))
    return new, kept, removed, added


def render_diff_md(
    diffs: List[Tuple[str, str, List[str], List[str], List[str]]],
    source_codes: Dict[str, Set[str]],
    harvest_codes: Dict[str, Dict[str, int]],
) -> str:
    """Render the per-scenario diff as markdown."""
    n_source = sum(len(v) for v in source_codes.values())
    n_harvest = sum(len(v) for v in harvest_codes.values())
    n_scenarios = len(diffs)
    n_changed = sum(1 for _, _, _, removed, added in diffs if removed or added)
    n_removed = sum(len(removed) for _, _, _, removed, _ in diffs)
    n_added = sum(len(added) for _, _, _, _, added in diffs)

    lines: List[str] = []
    lines.append("# W20-C1 scenarios.json regeneration — DRY RUN")
    lines.append("")
    lines.append(f"- scenarios processed: **{n_scenarios}**")
    lines.append(f"- scenarios with changes: **{n_changed}**")
    lines.append(f"- codes removed (ghosts): **{n_removed}**")
    lines.append(f"- codes added (seeds): **{n_added}**")
    lines.append(f"- source codes collected from gates: **{n_source}**")
    lines.append(f"- harvest codes loaded: **{n_harvest}**")
    lines.append("")
    lines.append("## Per-scenario diff")
    lines.append("")
    for sid, gate, kept, removed, added in diffs:
        lines.append(f"### `{sid}` ({gate})")
        lines.append("")
        if kept:
            lines.append("- **kept**:")
            for c in kept:
                lines.append(f"  - `{c}`")
        if removed:
            lines.append("- **removed (ghost)**:")
            for c in removed:
                lines.append(f"  - `{c}`")
        if added:
            lines.append("- **added (seed)**:")
            for c in added:
                lines.append(f"  - `{c}`")
        if not (kept or removed or added):
            lines.append("- _no failure_codes; unchanged (free-text probe)_")
        lines.append("")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gates-dir", default=str(GATES_DIR))
    parser.add_argument("--harvest", default=str(HARVEST_PATH))
    parser.add_argument("--scenarios", default=str(SCENARIOS_PATH))
    parser.add_argument(
        "--out-json", default="/tmp/W20_C1_scenarios_v2.json"
    )
    parser.add_argument(
        "--out-diff", default="/tmp/W20_C1_scenarios_v2_diff.md"
    )
    args = parser.parse_args(argv)

    source_codes = collect_codes_per_gate(Path(args.gates_dir))
    harvest_codes = load_harvest_codes(Path(args.harvest))
    scenarios_doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))

    new_scenarios: List[dict] = []
    diffs: List[Tuple[str, str, List[str], List[str], List[str]]] = []
    for sc in scenarios_doc.get("scenarios", []):
        new_sc, kept, removed, added = regen_scenario(
            sc, source_codes, harvest_codes
        )
        new_scenarios.append(new_sc)
        diffs.append(
            (
                sc.get("scenario_id", "<unknown>"),
                sc.get("gate_name", "<no-gate>"),
                kept,
                removed,
                added,
            )
        )

    new_doc = dict(scenarios_doc)
    new_doc["scenarios"] = new_scenarios
    new_doc.setdefault(
        "regeneration_note",
        "DRY-RUN candidate produced by scripts/rag/evals/regen_scenarios.py "
        "(W20-C1, closes W17-C4 ghost-finding loop).",
    )

    Path(args.out_json).write_text(
        json.dumps(new_doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    Path(args.out_diff).write_text(
        render_diff_md(diffs, source_codes, harvest_codes), encoding="utf-8"
    )

    # ── compute overlap stats so the operator sees the win immediately
    def overlap_pct(scenarios: List[dict]) -> float:
        tot, hits = 0, 0
        for sc in scenarios:
            gate = sc.get("gate_name")
            if not gate or gate == "free_text_probe":
                continue
            valid = valid_codes_for_gate(gate, source_codes, harvest_codes)
            for c in sc.get("failure_codes", []):
                tot += 1
                if c in valid:
                    hits += 1
        return (100.0 * hits / tot) if tot else 0.0

    before = overlap_pct(scenarios_doc.get("scenarios", []))
    after = overlap_pct(new_scenarios)
    print(f"overlap before: {before:.1f}%  after (dry-run): {after:.1f}%")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
