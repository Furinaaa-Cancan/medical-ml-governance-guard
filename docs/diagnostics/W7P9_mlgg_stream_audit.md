# W7-P9: mlgg.py stream-routing audit

**Subject**: `scripts/orchestration/mlgg.py` (739 LOC) — H7-followup audit for stdout/stderr bugs
**Date**: 2026-05-17
**Result**: 1 bug found (4-LOC class-b), fixed in commit `9127345`

## Print sites inventory

| Line | Site                                          | Classification | Stream  | Verdict |
|------|-----------------------------------------------|----------------|---------|---------|
| 78   | `[FAIL] invalid_python_executable`            | (b) status     | stderr  | OK      |
| 87   | `[FAIL] python_executable_not_found`          | (b) status     | stderr  | OK      |
| 115  | `[FAIL] invalid_cwd: NUL byte`                | (b) status     | stderr  | OK      |
| 120  | `[FAIL] invalid_cwd: cannot resolve`          | (b) status     | stderr  | OK      |
| 126  | `[FAIL] cwd_forbidden_path`                   | (b) status     | stderr  | OK      |
| 133  | `[FAIL] cwd_not_found`                        | (b) status     | stderr  | OK      |
| 136  | `[FAIL] cwd_not_directory`                    | (b) status     | stderr  | OK      |
| 153  | `[FAIL] invalid_profile_name`                 | (b) status     | stderr  | OK      |
| 175  | `[FAIL] passthrough_arg_too_long`             | (b) status     | stderr  | OK      |
| 182  | `[FAIL] passthrough_arg_nul_byte`             | (b) status     | stderr  | OK      |
| 208  | `[FAIL] subprocess_timeout` (centralized)     | (b) status     | stderr  | OK      |
| 215  | `[FAIL] subprocess_not_found`                 | (b) status     | stderr  | OK      |
| 394  | `[FAIL] Interactive script not found`         | (b) status     | stderr  | OK      |
| 403  | `$ <cmd>` echo (interactive help)             | (a) echo H7    | stderr  | OK      |
| 408  | `[FAIL] Script not found for command`         | (b) status     | stderr  | OK      |
| 411  | `$ <cmd>` echo (help dispatch)                | (a) echo H7    | stderr  | OK      |
| 431  | `[FAIL] <code>: <msg>` (emit_fail)            | (b) status     | stderr  | OK      |
| 440  | error_json payload (emit_fail)                | (b) status*    | stderr  | OK**    |
| 573  | `$ <cmd>` echo (workflow w/ profile)          | (a) echo H7    | stderr  | OK      |
| 624  | `$ <cmd>` echo (interactive subroute)         | (a) echo H7    | stderr  | OK      |
| 635  | `[ERROR] No configs/ directory`               | (b) status     | stderr  | OK      |
| 645  | `[WARN] {cf.name}: root is ...`               | (b) status     | **stdout** | **BUG** |
| 648  | `[OK]   {cf.name} (N keys)`                   | (b) status     | **stdout** | **BUG** |
| 650  | `[FAIL] {cf.name}: {err}`                     | (b) status     | **stdout** | **BUG** |
| 652  | `Checked: N, Errors: N` summary               | (b) status     | **stdout** | **BUG** |
| 656  | `flow` ASCII pipeline banner (multiline)      | (d) help/usage | stdout  | OK      |
| 711  | `$ PYTHONPATH=... <cmd>` echo (lint)          | (a) echo H7    | stderr  | OK      |
| 723  | `[FAIL] subprocess_timeout: lint`             | (b) status     | stderr  | OK      |
| 727  | `$ <cmd>` echo (default dispatch)             | (a) echo H7    | stderr  | OK      |

\* error_json payload is technically machine output but it’s an error sentinel keyed to MLGG_ERROR_CONTRACT_VERSION; placing on stderr keeps stdout clean for normal subcommand output and is the documented contract.
\** Verified intentional — error JSON is sent to stderr by design so stdout consumers see clean output.

## Subprocess sites inventory

| Line | Call                                          | Verdict |
|------|-----------------------------------------------|---------|
| 205  | `subprocess.run(cmd, cwd=..., text=True, timeout=...)` — centralized `_run_subprocess`. Inherits parent stdout/stderr (no capture), so child output streams through unbuffered. Stream ordering with parent prints is correct because all parent prints are on stderr while child stdout flows independently. | OK      |
| 719  | `subprocess.run(cmd, cwd=..., text=True, env=env, timeout=...)` — special-case lint with PYTHONPATH. Same inheritance semantics. | OK      |

No `subprocess.Popen` or `subprocess.call`. No `capture_output=True` consumers in this module — every subprocess inherits parent fds, so there is no risk of swallowing child stderr.

## Findings

- (a) `$ <cmd>` echo sites: **6** — all stderr post-H7 fix (lines 403, 411, 573, 624, 711, 727). Verified.
- (b) status/log on stdout (BUG): **4** — all in the `validate` subcommand built-in (lines 645/648/650/652).
- (c) command output forwarding: **0** explicit; all dispatch flows through `_run_subprocess` with inherited stdio (correct).
- (d) help/usage: **1** — `flow` banner (line 656), correctly on stdout.

## Recommended fix — APPLIED

The 4-line bug in the `validate` built-in is the same class as H7. Added `file=sys.stderr` to all four print sites in `scripts/orchestration/mlgg.py` lines 645/648/650/652.

**Impact**:
- `mlgg validate` (a stdlib-only JSON config sanity check) had per-file status and summary going to stdout. If a future caller pipes `mlgg validate | jq` or composes it with `mlgg <other> | tee` for machine consumption, the WARN/OK/FAIL lines would corrupt the assumed clean-output channel.
- Exit code contract unchanged: `0` if no errors, `1` otherwise.
- No tests broken (status messages were not part of any test contract — verified by grep on `mlgg.*validate` callers, which surface only `paper/outline-v0.3.md` as a doc reference).

**Commit**: `9127345` — `fix(mlgg): route validate status messages to stderr (W7-P9 H7-followup)`
**Pushed**: yes (race-safe: stashed concurrent RAG-session edits, pulled-rebase, fix, push, unstash).

## Smoke checks

- `python3 -c "import ast; ast.parse(open('scripts/orchestration/mlgg.py').read())"` — parse OK.
- `python3 scripts/orchestration/mlgg.py --help 2>/dev/null | head -3` — help text reaches stdout as expected.
- `python3 scripts/orchestration/mlgg.py validate 2>/dev/null` — now silent on stdout (good; previously leaked status when configs/ existed).
- CI: `gh run list` shows ci-unit + ci-security `in_progress` on the fix commit at audit time.
