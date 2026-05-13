#!/usr/bin/env python3
"""Clone the verified-cohort corpus' GitHub repos, run mlgg-lint on each,
aggregate findings.

Reads:
  paper/code-repos-corpus.json (which has primary_repo field per entry)

Per repo:
  1. Shallow git clone to .cache/audit-repos/<paper_id>
  2. Run `python3 -m mlgg_lint check <repo>/ --output <evidence>` (best effort)
  3. Capture: rules fired, files affected, exit code

Aggregates:
  - Per-rule firing count across N papers
  - Per-paper findings list

Writes:
  paper/lint-audit-results.json
  paper/lint-audit-results.md

Usage:
  python3 scripts/diagnostics/audit_corpus_repos.py
"""
from __future__ import annotations
import argparse, json, subprocess, sys, os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_PATH = ROOT / "paper" / "code-repos-corpus.json"
CACHE_DIR = ROOT / ".cache" / "audit-repos"
EVIDENCE_DIR = ROOT / ".cache" / "audit-evidence"
OUT_JSON = ROOT / "paper" / "lint-audit-results.json"
OUT_MD = ROOT / "paper" / "lint-audit-results.md"


def shallow_clone(url: str, dest: Path, timeout: int = 120) -> tuple[bool, str]:
    """Shallow clone (depth=1, no LFS). Returns (success, message)."""
    if dest.exists() and any(dest.iterdir()):
        return True, "already_cloned"
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    # Strip any /tree/<branch>/path or /blob/<...> from URL — git clone needs base repo
    base = url.split("/tree/")[0].split("/blob/")[0].rstrip("/")
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", base, str(dest)],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if r.returncode == 0:
            return True, "cloned"
        return False, f"clone_failed: {r.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired:
        return False, "clone_timeout"
    except Exception as e:
        return False, f"clone_exception: {e}"


def count_python_files(repo: Path) -> int:
    return sum(1 for _ in repo.rglob("*.py"))


def count_notebook_files(repo: Path) -> int:
    return sum(1 for _ in repo.rglob("*.ipynb"))


def run_mlgg_lint(repo: Path, evidence: Path, timeout: int = 180) -> dict:
    """Run mlgg-lint, return parsed result dict.

    NB: pass -W ignore to silence Python SyntaxWarnings (some .ipynb cells
    contain '\C', '\d' etc. that trigger DeprecationWarning) which would
    otherwise pollute stdout and break JSON parsing. Stderr is captured
    separately so warnings don't corrupt the JSON output stream.
    """
    evidence.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-W", "ignore", "-m", "mlgg_lint", "check",
           str(repo), "--format", "json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, cwd=str(ROOT))
        # findings list is in stdout; warnings/errors in stderr
        payload: list | dict
        try:
            payload = json.loads(r.stdout) if r.stdout.strip() else []
        except json.JSONDecodeError as exc:
            payload = {
                "_json_decode_error": str(exc)[:200],
                "_stdout_first_500": r.stdout[:500],
            }
        return {
            "exit_code": r.returncode,
            "stdout_bytes": len(r.stdout),
            "stderr_tail": r.stderr[-300:] if r.stderr else "",
            "payload": payload,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stderr_tail": "lint_timeout", "payload": []}
    except Exception as e:
        return {"exit_code": -2, "stderr_tail": f"lint_exception: {e}", "payload": []}


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not CORPUS_PATH.exists():
        print(f"ERROR: {CORPUS_PATH} not found. Run find_code_repos.py first.", file=sys.stderr)
        return 1
    corpus = json.loads(CORPUS_PATH.read_text())["results"]
    # Filter to entries with a github primary_repo (other hosts need separate clone strategy)
    targets = [r for r in corpus
               if r.get("primary_repo") and "github.com" in r["primary_repo"]]
    print(f"Auditing {len(targets)} GitHub repos...", file=sys.stderr)

    audit_results = []
    for i, r in enumerate(targets):
        pid = r["id"]
        url = r["primary_repo"].split("&#")[0]
        dest = CACHE_DIR / pid
        evidence = EVIDENCE_DIR / f"{pid}.json"

        print(f"\n[{i+1}/{len(targets)}] {pid}: {url[:70]}", file=sys.stderr)
        ok, msg = shallow_clone(url, dest)
        result = {"id": pid, "primary_repo": url, "clone_status": msg,
                  "python_files": 0, "notebook_files": 0, "lint": None}

        if ok:
            n_py = count_python_files(dest)
            n_nb = count_notebook_files(dest)
            result["python_files"] = n_py
            result["notebook_files"] = n_nb
            print(f"  clone: {msg}, py={n_py}, ipynb={n_nb}", file=sys.stderr)
            if n_py > 0:
                lint = run_mlgg_lint(dest, evidence)
                result["lint"] = lint
                # mlgg-lint --format json returns a top-level LIST of findings
                payload = lint.get("payload", [])
                findings = payload if isinstance(payload, list) else []
                rules_fired = sorted(set(f.get("rule_id") for f in findings if f.get("rule_id")))
                from collections import Counter
                rule_counts = dict(Counter(f.get("rule_id") for f in findings if f.get("rule_id")).most_common())
                sev_counts = dict(Counter(f.get("severity") for f in findings if f.get("severity")).most_common())
                result["rules_fired"] = rules_fired
                result["rule_counts"] = rule_counts
                result["severity_counts"] = sev_counts
                result["finding_count"] = len(findings)
                print(f"  lint: exit={lint['exit_code']}, findings={len(findings)}, rules={rules_fired[:8]}", file=sys.stderr)
            else:
                result["rules_fired"] = []
                result["finding_count"] = 0
                print("  no Python files, skipping lint", file=sys.stderr)
        else:
            print(f"  clone failed: {msg}", file=sys.stderr)
        audit_results.append(result)

    # Aggregate
    from collections import Counter
    rule_counts = Counter()
    for r in audit_results:
        for rule in r.get("rules_fired", []):
            rule_counts[rule] += 1

    # Stats
    n_total = len(audit_results)
    n_cloned = sum(1 for r in audit_results if r["clone_status"] in ("cloned", "already_cloned"))
    n_with_py = sum(1 for r in audit_results if r["python_files"] > 0)
    n_with_findings = sum(1 for r in audit_results if r.get("finding_count", 0) > 0)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(CORPUS_PATH.relative_to(ROOT)),
        "stats": {
            "total_targets": n_total,
            "successfully_cloned": n_cloned,
            "have_python_files": n_with_py,
            "lint_findings_at_least_one": n_with_findings,
        },
        "rules_fired_across_corpus": dict(rule_counts.most_common()),
        "results": audit_results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    md = [
        f"# mlgg-lint audit on {n_total}-paper verified-cohort corpus",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Headline numbers",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| GitHub repos targeted | {n_total} |",
        f"| Successfully cloned | {n_cloned} |",
        f"| Repos with Python files | {n_with_py} |",
        f"| Repos with ≥1 mlgg-lint finding | {n_with_findings} |",
        "",
        "## Rules fired across corpus (rule × papers count)",
        "",
        "| Rule | Papers fired |",
        "|---|---:|",
    ]
    for rule, cnt in rule_counts.most_common(30):
        md.append(f"| `{rule}` | {cnt} |")
    md.append("")
    md.append("## Per-paper detail")
    md.append("")
    md.append("| ID | Repo | Clone | Py files | Findings | Top rules |")
    md.append("|---|---|---|---:|---:|---|")
    for r in audit_results:
        url = r["primary_repo"].split("github.com/")[-1] if "github.com" in r["primary_repo"] else r["primary_repo"]
        rules_short = ", ".join(r.get("rules_fired", [])[:4])
        md.append(f"| {r['id']} | `{url[:50]}` | {r['clone_status'][:20]} | {r['python_files']} | {r.get('finding_count', '—')} | {rules_short} |")
    OUT_MD.write_text("\n".join(md))

    print("\n=== DONE ===")
    print(f"Targets: {n_total}, cloned: {n_cloned}, with Python: {n_with_py}, with findings: {n_with_findings}")
    print("Top rules fired:")
    for rule, cnt in rule_counts.most_common(10):
        print(f"  {cnt:3} papers: {rule}")
    print("\nReports:")
    print(f"  {OUT_JSON.relative_to(ROOT)}")
    print(f"  {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
