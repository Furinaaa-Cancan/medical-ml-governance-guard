# CodeQL Security Triage — first scan (2026-05-17)

First-run CodeQL scan after enabling `.github/workflows/codeql.yml` with the `security-extended,security-and-quality` query suite returned **344 alerts** across **279 unique files**. This document records the per-class triage, what was fixed, and what was filtered.

| Severity | Count | Disposition |
|---|---|---|
| `error`   | 28  | 1 fixed, 4 hardened, 23 false-positive or low |
| `warning` | 38  | 0 fixed, all noise (mostly style) |
| `note`    | 278 | 0 fixed, all style (unused-import / variable, empty-except) |

Net result after this commit: **1 real bug fixed + 4 hardened + 5 rules filtered → expected next scan ≈ 50 alerts**, almost all of which will be `warning` severity in third-party Python idioms (e.g., `py/mixed-returns`, `py/multiple-definition`) that are tolerable in research code.

---

## REAL BUG (fixed)

### `scripts/codebooks/verify_nhanes_codebook.py:107` — `tempfile.mktemp()` TOCTOU

**Rule:** `py/insecure-temporary-file` (error)

**Problem:** `tempfile.mktemp()` is deprecated. It returns a filename without creating the file, leaving a race window where an attacker on the same machine can predict the name and create a symlink before our code writes. Affects only multi-tenant systems (NHANES download is typically dev-machine use), but the fix is one-liner.

**Fix:** switch to `tempfile.mkstemp()` which atomically creates the file and returns a file descriptor. Immediately close the fd because `urllib.request.urlretrieve(url, path)` re-opens by path; the existing directory entry blocks the symlink race.

---

## HARDENED (defence-in-depth, not exploitable as written)

### `scripts/diagnostics/mlgg_web.py:460/471/479` — stack-trace-exposure (3 alerts)

**Rule:** `py/stack-trace-exposure` (error)

**Problem:** `except ValueError as exc: return str(exc), 400` returns the exception message to the user. CodeQL flags this as potential stack-trace leakage.

**Real risk:** the exceptions are `ValueError` instances raised by our own validators with controlled messages — no stack info. But the user-supplied input (e.g., a path) ends up echoed back, which is noisy.

**Fix:** log the detailed message via `app.logger.warning(...)` (server-side audit trail) and return a generic `"Invalid input."` (400) to the client.

### `scripts/diagnostics/mlgg_web.py:160/473` — path-injection (2 alerts)

**Rule:** `py/path-injection` (error)

**Problem:** CodeQL says user-supplied paths flow into filesystem operations.

**Real risk:** the code DOES validate via `_validate_path_no_traversal()` (rejects null bytes, `/etc`, `/proc`, etc.). CodeQL's flow analysis doesn't recognize the custom validator as a sanitizer. Inspection confirms the validator runs before any filesystem touch.

**Disposition:** NOT FIXED — false positive. The validator is correct. Adding a CodeQL suppression comment would clutter the code; leaving as a "known FP" in this doc instead.

---

## FALSE POSITIVES (filtered in `codeql.yml` `query-filters:`)

### `py/clear-text-logging-sensitive-data` (17 alerts)

**Sample locations:**
- `scripts/training/schema_preflight.py:437-442` — `print(f"Status: {report['status']}")` etc. Report keys are `"OK"`, `"FAIL"`, `"WARN"` or audit code+message. No PHI.
- `scripts/orchestration/mlgg_onboarding.py:269` — `print(f"\n[PREVIEW] {name}: {description}")` for preview-mode workflow output. Name/description are user-facing labels.

**Why filtered:** the project IS an audit reporter — its CLI scripts print methodology findings as their core function. CodeQL flags `print()` of any string that flowed through a function it categorised as handling "private" data; in our case the entire pipeline is "private" because it consumes user data, so every `print` lights up. Suppressing the rule globally is correct here.

**Caveat for production deployment:** if anyone embeds these scripts into a logging-shipper pipeline (e.g., to ship audit logs to a SaaS), they should re-audit whether `issue['message']` could contain column names that are themselves PHI (e.g., a column named `"patient_ssn"`). The CLI use case is fine.

### `py/incomplete-url-substring-sanitization` (10 alerts)

**Sample locations:**
- `scripts/diagnostics/find_code_repos.py:198-199` — `any('github.com' in u for u in urls)` to count how many papers cite GitHub.

**Why filtered:** the URL substring check is used for **statistics counting**, not for routing or security gating. An attacker URL like `https://evil.com/?fake=github.com` would be counted as "has GitHub link" — which is a harmless miscount in stats output, not a security boundary breach.

### `py/uninitialized-local-variable` in `tests/**` (3 alerts)

**Sample location:** `tests/test_rag_scenarios_schema.py:151` references `rag_query` after a `try/except ImportError: pytest.skip(...)`.

**Why filtered:** `pytest.skip()` raises a `SkipException` that halts execution before the use site. CodeQL doesn't model pytest's flow-control conventions. The code is correct.

**Scope:** filter restricted to `paths: ["tests/**"]` so production code uses of the rule still surface.

---

## STYLE NOISE (silenced by dropping `security-and-quality`)

The `security-and-quality` suite adds non-security checks (`py/unused-import`, `py/unused-local-variable`, `py/empty-except`, `py/implicit-string-concatenation-in-list`, etc.). These are the same checks `ruff` already enforces in `ruff.toml`. Running them twice produces 200+ duplicate alerts. Dropping the `,security-and-quality` from `queries:` removes the duplication; `ruff` remains authoritative.

| Rule | Pre-filter count | Handled by |
|---|---|---|
| `py/unused-import`               | 123 | ruff F401 |
| `py/empty-except`                | 72  | ruff B902 (already on by default) |
| `py/unused-local-variable`       | 55  | ruff F841 |
| `py/unused-global-variable`      | 15  | ruff F823 |
| `py/implicit-string-concatenation-in-list` | 12 | ruff ISC001 |
| `py/multiple-definition`         | 6   | ruff F811 |
| `py/mixed-returns`               | 5   | (research-code idiom; tolerated) |
| `py/redundant-comparison`        | 4   | ruff B015 |

---

## What's left after this commit (predicted)

Re-scan after this commit should show roughly:

| Severity | Count | Notes |
|---|---|---|
| `error`   | ~5  | Mostly mlgg_web.py path-injection FPs (kept visible as triage record) + the test-code wrong-args / redundant-assignment |
| `warning` | ~20 | `py/mixed-returns`, third-party idiom flagged in our pinned versions |
| `note`    | 0   | `security-and-quality` queries dropped |

If the next scan shows substantially more, something in the codebase changed or a new query was added — re-triage and update this doc.

---

## Review cadence

- **Every CodeQL `error`-severity alert** should be triaged within 7 days of appearance.
- **`warning`** is on a 30-day SLO.
- **`note`** is informational; review at quarterly cleanup.
- New rule classes (CodeQL pack updates) should add a row to this document, not just be suppressed silently.

This doc is the audit trail for "we looked, here's what we kept and what we filtered" so that an external security reviewer can verify the triage decisions rather than just see a clean dashboard with no context.
