# Audit finding m7 — sort-fix artifact (agent D)

## Bug

`scripts/reporting/export_review_prompt.py` line 161 took `entries[:20]`
from `literature-knowledge-base.json` in **JSON file order**. With 67 entries
in the KB, LIT-021..LIT-067 were never surfaced in the review prompt
regardless of relevance to the criteria being rendered.

## Fix (summary)

- Added `_lit_relevance_key(entry, context_gates, context_dims)` helper:
  composite descending sort key on (gate/dimension-overlap relevance,
  year, impact_factor). Missing year/IF coerce to 0.
- In `render_markdown_prompt`, derived `context_gates` and `context_dims`
  from criteria actually selected at the requested review level
  (plus journal-mandated gates when a `--journal` is supplied), sorted
  `entries` with that key, then sliced `[:20]`.
- Helper kept module-level and underscore-prefixed for unit-testability.

## Diff

```diff
diff --git a/scripts/reporting/export_review_prompt.py b/scripts/reporting/export_review_prompt.py
index 77ab2c1..4b952f7 100644
--- a/scripts/reporting/export_review_prompt.py
+++ b/scripts/reporting/export_review_prompt.py
@@ -93,6 +93,45 @@ def get_criteria_for_level(
     return result


+def _lit_relevance_key(
+    entry: Dict[str, Any],
+    context_gates: Optional[set] = None,
+    context_dims: Optional[set] = None,
+) -> tuple:
+    """Composite sort key for a literature-KB entry.
+
+    Sort order (descending — larger tuple wins):
+      1. Whether ``gates_implementing`` overlaps the current context gate set
+         (or ``dimensions_affected`` overlaps the dimension set as a fallback).
+         Entries with no context return 0 here.
+      2. ``year`` descending (newer first); missing/non-numeric → 0.
+      3. ``impact_factor`` descending; missing/None → 0.
+
+    Returns a tuple suitable for ``sorted(..., key=..., reverse=True)``.
+    """
+    gates = set(entry.get("gates_implementing") or [])
+    dims = set(entry.get("dimensions_affected") or [])
+
+    relevance = 0
+    if context_gates and gates & context_gates:
+        relevance = 2
+    elif context_dims and dims & context_dims:
+        relevance = 1
+
+    try:
+        year = int(entry.get("year") or 0)
+    except (TypeError, ValueError):
+        year = 0
+
+    impact = entry.get("impact_factor")
+    try:
+        impact_val = float(impact) if impact is not None else 0.0
+    except (TypeError, ValueError):
+        impact_val = 0.0
+
+    return (relevance, year, impact_val)
+
+
 def render_markdown_prompt(
     standard: Dict[str, Any],
     level: str,
@@ -156,9 +195,31 @@ def render_markdown_prompt(
     lit_section = ""
     if include_literature and lit_kb:
         entries = lit_kb.get("entries", [])
-        # Only include entries relevant to the level
+        # Derive context from criteria actually rendered at this level so we
+        # surface the most-relevant literature instead of the first 20 entries
+        # in JSON file order (audit finding m7).
+        context_gates: set = set()
+        context_dims: set = set()
+        for entry in criteria_flat:
+            c = entry["criterion"]
+            gate = c.get("gate")
+            if gate:
+                context_gates.add(gate)
+            for g in c.get("gates", []) or []:
+                context_gates.add(g)
+            context_dims.add(entry["dim"]["id"])
+        # Journal-mandated gates also count as in-scope context.
+        if journal_data:
+            for g in journal_data.get("required_gates", []) or []:
+                context_gates.add(g)
+
+        sorted_entries = sorted(
+            entries,
+            key=lambda e: _lit_relevance_key(e, context_gates, context_dims),
+            reverse=True,
+        )
         lit_section = "\n## Key Literature References\n\n"
-        for e in entries[:20]:
+        for e in sorted_entries[:20]:
             lit_section += (
                 f"- **{e['id']}** [{e.get('year','')}] {e['title'][:80]}... "
                 f"(*{e.get('journal','')}*, IF≈{e.get('impact_factor','')})\n"
```

Test file `tests/test_export_review_prompt.py` gained two new test classes:
`TestLitRelevanceKey` (5 tests for the helper) and `TestLiteratureTopTwenty`
(2 tests proving the rendered top-20 surfaces high-relevance entries and
that the pre-fix bug no longer reproduces). Both use `tmp_path`.

## pytest output

### `pytest tests/test_export_review_prompt.py -x -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.0.2, pluggy-1.6.0
collected 29 items

tests/test_export_review_prompt.py::TestGetCriteriaForLevel::test_quick_subset_of_standard PASSED
tests/test_export_review_prompt.py::TestGetCriteriaForLevel::test_standard_subset_of_comprehensive PASSED
tests/test_export_review_prompt.py::TestGetCriteriaForLevel::test_quick_has_criteria PASSED
tests/test_export_review_prompt.py::TestGetCriteriaForLevel::test_comprehensive_max_criteria PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_returns_string PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_contains_criteria_heading PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_contains_role_section PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_journal_section_included PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_literature_section_included PASSED
tests/test_export_review_prompt.py::TestRenderMarkdownPrompt::test_literature_not_included_by_default PASSED
tests/test_export_review_prompt.py::TestRenderJsonPrompt::test_returns_valid_json PASSED
tests/test_export_review_prompt.py::TestRenderJsonPrompt::test_has_required_keys PASSED
tests/test_export_review_prompt.py::TestRenderJsonPrompt::test_criteria_count_matches PASSED
tests/test_export_review_prompt.py::TestRenderJsonPrompt::test_journal_section_in_json PASSED
tests/test_export_review_prompt.py::TestLitRelevanceKey::test_context_gate_overlap_beats_year PASSED
tests/test_export_review_prompt.py::TestLitRelevanceKey::test_year_breaks_tie_when_relevance_equal PASSED
tests/test_export_review_prompt.py::TestLitRelevanceKey::test_impact_factor_breaks_tie_when_year_equal PASSED
tests/test_export_review_prompt.py::TestLitRelevanceKey::test_missing_impact_factor_treated_as_zero PASSED
tests/test_export_review_prompt.py::TestLitRelevanceKey::test_dimension_overlap_fallback PASSED
tests/test_export_review_prompt.py::TestLiteratureTopTwenty::test_top_twenty_prefers_relevant_entries PASSED
tests/test_export_review_prompt.py::TestLiteratureTopTwenty::test_pre_fix_bug_no_longer_reproduces PASSED
tests/test_export_review_prompt.py::TestCLI::test_quick_stdout PASSED
tests/test_export_review_prompt.py::TestCLI::test_standard_stdout PASSED
tests/test_export_review_prompt.py::TestCLI::test_comprehensive_stdout PASSED
tests/test_export_review_prompt.py::TestCLI::test_json_format PASSED
tests/test_export_review_prompt.py::TestCLI::test_output_to_file PASSED
tests/test_export_review_prompt.py::TestCLI::test_journal_flag PASSED
tests/test_export_review_prompt.py::TestCLI::test_include_literature PASSED
tests/test_export_review_prompt.py::TestCLI::test_json_with_journal PASSED

============================== 29 passed in 0.51s ==============================
```

### `pytest tests/ -k "export_review" -x --ignore=tests/test_math_properties.py`

```
collected 5695 items / 5665 deselected / 13 skipped / 30 selected
30 passed, 13 skipped, 5665 deselected in 4.15s
```

### `pytest tests/ -k "audit_report" -x --ignore=tests/test_math_properties.py`

```
collected 5695 items / 5619 deselected / 13 skipped / 76 selected
76 passed, 13 skipped, 5619 deselected in 2.06s
```

Note: `tests/test_math_properties.py` was excluded only because the
project venv lacks the optional `hypothesis` dependency — pre-existing
collection error, unrelated to this fix.

### Lint

`ruff check scripts/reporting/export_review_prompt.py tests/test_export_review_prompt.py`
→ **All checks passed!**

## Commit & push

- **Commit SHA**: `dd7678bea9c727298a7cf2475f5bcacc317809ee`
- **Message**: `fix(reporting): sort lit entries before truncation in export_review_prompt`
- **Pre-push hook**: 361 tests passed (~33.7s)
- **Push result**: `6be18e4..dd7678b  main -> main` to
  https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
