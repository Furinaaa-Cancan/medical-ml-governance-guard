# W15-A5: Dead code audit (unused imports + unreferenced defs)

**Agent**: W15-A5 (read-only)
**Date**: 2026-05-17
**Scope**: `scripts/` (208 `.py` files, 1020 top-level public defs)
**Methods**: ruff F401 for unused imports; AST walk + corpus-wide regex ref-count for defined-not-called

---

## F401 unused imports

```
$ python3 -m ruff check scripts/ --select F401
All checks passed!
```

**0 unused imports.** ruff F401 is clean across all 208 script files.

---

## Functions defined-not-called (high confidence)

Method: walked `ast.parse` on every `scripts/**.py`, collected top-level `def`/`class` whose name is public (no leading `_`) and not decorated with CLI-entry markers (`@click.command`, `@pytest.fixture`, etc.). For each, counted regex word-boundary occurrences across `scripts/` ∪ `tests/`. A def with `≤0` references outside its own definition line is flagged.

Raw count: **5 / 1020 defs (0.49%)**. Below, manually triaged.

| # | file:line | name | judgment |
|---|---|---|---|
| 1 | `scripts/codebooks/fetch_nhanes_2021_2023.py:55` | `class CodebookPageParser` | **DELETE** — never instantiated anywhere; the file uses regex-based parsing (`parse_codebook_page`, line 97) instead. Sibling `DataPageParser` IS used (line 237). Class is ~40 lines of dead state. |
| 2 | `scripts/core/_gate_framework.py:351` | `add_common_arguments` | **DELETE or ADOPT** — intended to standardise gate CLI surface (`--report`, `--strict`, `--dry-run`), but every gate (`leakage_gate.py`, `split_protocol_gate.py`, `manifest_lock.py`, ~30 more) rolls its own argparse. Either retro-fit gates to call this, or remove. |
| 3 | `scripts/core/_gate_framework.py:370` | `add_input_file_argument` | **DELETE or ADOPT** — same situation as #2; trivial 1-line wrapper around `group.add_argument`. |
| 4 | `scripts/diagnostics/mlgg_web.py:445` | `handle_step` | **KEEP** — false positive. Decorated `@app.route("/step/<int:step_num>", methods=["POST"])`; called by Flask dispatcher. |
| 5 | `scripts/diagnostics/mlgg_web.py:542` | `stream_logs` | **KEEP** — false positive. Decorated `@app.route("/logs/<sid>")`; SSE endpoint dispatched by Flask. |

The detector's `EXCLUDE_DECOS` set caught `command`/`group`/`callback`/`fixture` but missed `route` — items 4 & 5 are intentional plugin-loaded entry points and should NOT be removed. Adding `route` to the exclude list would drop these.

**True dead defs after triage: 3** (items 1, 2, 3).

---

## Dead branches

`grep -rn "^[[:space:]]*if False:" scripts/` → **0 hits**.
No obvious `return`-then-code patterns surfaced in the spot-check.

---

## Verdict: PASS

- **F401: clean** (0 unused imports across 208 files).
- **Defined-not-called: 3 confirmed dead, 2 false positives** (Flask routes).
- **Dead branches: none found.**
- Density: 3 / 1020 = **0.29% genuine dead public defs** — well within acceptable noise; not a structural problem.

The Wave-14 fake-coverage concern (gates with subprocess-tested coverage looking artificially low) is a separate phenomenon; the gates themselves are reachable through CLI invocation, so they do not appear here even though their internal functions may show low line-coverage in pytest.

---

## Recommendation for Wave N+

Open a **single small cleanup commit** (not in this audit wave):

1. Delete `CodebookPageParser` class + its imports if NHANES fetch script still works end-to-end (the file already imports `HTMLParser` for `DataPageParser`, so the import stays).
2. Decide on `add_common_arguments` / `add_input_file_argument`: either (a) refactor 3-4 representative gates to use them, then file an issue to migrate the rest, or (b) delete both.
3. Patch the detector script (kept in `/tmp/W15_A5_ast_walk2.py` for this audit) to include `route` in `EXCLUDE_DECOS` if anyone re-runs it.

No urgency; safe to defer.

---

## Caveats / known false-negative classes

The corpus-wide regex word-boundary check will UNDER-report dead code in these cases — they need a separate pass if anyone wants tighter results:

- **Dynamic dispatch via `getattr(mod, name)`** — not surfaced; would need data-flow analysis.
- **Entry points loaded via `pkg_resources` / `importlib.metadata`** — none used here, low risk.
- **Methods on classes** — this audit only inspected *top-level* defs; instance methods (incl. dead ones) are out of scope.
- **String-referenced callables** (e.g. `"module.func"` in YAML/JSON config) — would falsely flag.

These limits keep precision high (5/5 of the flagged items were defensible, even if 2 were false positives on inspection). For broader coverage install `vulture` (currently unavailable in env) in a separate dev-tooling PR.
