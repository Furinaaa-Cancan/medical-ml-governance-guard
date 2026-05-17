# H17: CI-side README drift gate proposal

> **Status:** proposal only. No workflow files were modified by H17 (per
> CLAUDE.md NEVER rule #2: "不修改 `.github/workflows/`（除非用户明确要求）").
> Apply manually when ready.

## Why

G9's pre-push hook and H3's pre-commit hook are both **opt-in**.
Contributors who skip `pre-commit install` (or `make install-hooks`)
still ship README/tree drift to CI. Recent history shows 4 reds caused
by README drift across waves A4, A10, F5, and the G-wave overnight loop.
Each red costs roughly one full CI cycle (~14 min on the `unit` matrix
across Python 3.10/3.11/3.12) plus a fix-forward commit and rebase
noise on other in-flight branches.

A **server-side gate** makes drift impossible to land:

- Runs in CI on every PR + push to `main` / `claude/**`
- Fails loudly on drift, blocks merge
- No opt-in — applies to all contributors and all agents automatically
- Complements (does not replace) the existing local pre-commit hook

The local hook is still useful: fast feedback before push. The CI gate
is the safety net for everyone who forgot, ignored, or bypassed it
(`git commit --no-verify`, fresh clones, automated agents, etc.).

## Existing local hook

`.pre-commit-config.yaml` already exists in the repo root and (per H3's
deep observation) wires `check_readme_stats.py` as a local hook.
Confirmed present: `scripts/diagnostics/check_readme_stats.py`. The
CI-side gate reuses the *same script*, guaranteeing identical
drift semantics locally and in CI.

## Workflow files inspected (5)

```
.github/workflows/ci-unit.yml         <-- recommended insertion point
.github/workflows/ci-extended.yml
.github/workflows/ci-full.yml
.github/workflows/ci-overnight.yml
.github/workflows/ci-security.yml
```

`ci-unit.yml` is the right target because:

- It already runs on every `push` to `main` / `claude/**` and on every
  `pull_request` — the exact trigger surface a drift gate needs.
- It is the workflow whose reds the user already pays attention to;
  adding the gate here surfaces drift in the same UI signal.
- It is fast (~14 min). The other workflows are heavier (extended /
  overnight / full) and run less often — too slow for a drift signal.

## Recommended insertion: STEP inside the `unit` job (not a new job)

Rationale:

- The drift check is essentially a file-count diff against README
  tree-listings. Runtime is sub-second.
- Spinning up a separate runner adds ~30–60 s of GitHub Actions queue +
  checkout + setup-python overhead **per matrix entry** (or one extra
  job slot) for a check that takes ~1 s. Not worth it.
- Co-locating with `unit` ensures the same `actions/checkout@v4` and
  `actions/setup-python@v5` are reused — single source of truth for
  Python version.
- Placing it as the **first** post-setup step (before `Install
  dependencies`) means drift fails in ~30 s instead of after the full
  pip install (~3–5 min). Tight feedback loop = the whole point.

## Patch (apply manually)

`.github/workflows/ci-unit.yml`, insert a new step between
`actions/setup-python@v5` and `Install dependencies`:

```diff
       - uses: actions/setup-python@v5
         with:
           python-version: ${{ matrix.python-version }}

+      - name: README stats drift check
+        run: python3 scripts/diagnostics/check_readme_stats.py
+
       - name: Install dependencies
         run: |
           python3 -m pip install --upgrade pip
           python3 -m pip install -r requirements.txt
```

That is the whole change. ~3 added lines.

### Why no `--strict` / extra flags?

`check_readme_stats.py` already exits non-zero on drift (it is the
same script the local pre-commit hook calls). No CLI surface change
required.

### Matrix consideration

The current `unit` job runs across `python-version: ["3.10", "3.11",
"3.12"]` with `fail-fast: false`. The drift check will therefore run
3 times per push. That is harmless (~3 s total) and gives identical
signal on all three runners, which is fine — drift is deterministic.

If you want to run it exactly once, the alternative is a dedicated
top-level job:

```yaml
  readme-drift:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: README stats drift check
        run: python3 scripts/diagnostics/check_readme_stats.py
```

But this trades 3 redundant sub-second runs for one extra runner
spin-up (~45 s) — net slower wall-clock and more queue pressure.
**Recommendation stays: in-line step inside `unit`.**

## Trade-offs

- Failures will block PRs and require updating tree-listing counts
  before merge — desirable per the user's "stay green" feedback memory.
- Adds ~1 s to every `unit` matrix entry (negligible vs. the 14-min
  total).
- Does not catch other kinds of doc drift (only what
  `check_readme_stats.py` knows about). Future scope: extend the same
  pattern to `check_docs_consistency.py` if desired — but that script
  is heavier and would warrant its own dedicated job.

## Activation instructions for the user

1. Open `.github/workflows/ci-unit.yml`.
2. Apply the 3-line diff above (new step between
   `actions/setup-python@v5` and `Install dependencies`).
3. Push to a feature branch first (e.g. `claude/ci-drift-gate`) to
   verify:
   - The step appears in the Actions UI under each matrix leg.
   - On a clean tree, it passes in <2 s.
   - Optionally: temporarily corrupt a README count, push, confirm the
     step fails with the same report contributors see locally, then
     revert.
4. Merge to `main`. From then on, drift cannot land.

If a future agent is explicitly authorized to modify
`.github/workflows/`, this is a ~3-line change that takes 2 minutes.

## Summary

| Field | Value |
|---|---|
| Insertion point | `.github/workflows/ci-unit.yml`, step inside `unit` job |
| Step position | between `setup-python` and `Install dependencies` |
| Script invoked | `scripts/diagnostics/check_readme_stats.py` (already exists) |
| Lines added | 3 |
| Extra CI runtime | ~1 s per matrix leg (negligible) |
| Pre-commit hook handles local case | true (`.pre-commit-config.yaml` already wires it) |
| Workflows touched by H17 | 0 (proposal only) |
