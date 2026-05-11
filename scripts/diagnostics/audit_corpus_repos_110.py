#!/usr/bin/env python3
"""Clone the 110-paper cohort-binary corpus' GitHub/GitLab repos, run mlgg-lint
on each, aggregate findings.

This is the v2 of audit_corpus_repos.py for the larger 110-paper cohort.

Reads:
  paper/code-repos-cohort-binary.json (results[*].primary_repo)

Filter: primary_repo not null AND host in {github.com, gitlab.com}
        (Zenodo / Figshare / Mendeley DOIs need a separate fetch strategy
         and are out-of-scope for v1 of this audit.)

Per repo:
  1. Shallow clone (depth=1, GIT_LFS_SKIP_SMUDGE=1) to .cache/audit-repos-110/<id>
  2. If .py count > 0, run `python3 -W ignore -m mlgg_lint check <repo> --format json`
  3. Capture: rule_id + severity + file + line ONLY (no diagnostic message —
     mlgg-lint messages occasionally quote source-code snippets which we
     must not redistribute).

Aggregates:
  - Per-rule firing count across N papers
  - Per-rule total findings across the corpus
  - Per-paper rule_counts and severity_counts

Writes:
  paper/lint-audit-110.json
  paper/lint-audit-110.md

Usage:
  python3 scripts/diagnostics/audit_corpus_repos_110.py
"""
from __future__ import annotations
import json, subprocess, sys, os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_PATH = ROOT / "paper" / "code-repos-cohort-binary.json"
CACHE_DIR = ROOT / ".cache" / "audit-repos-110"
OUT_JSON = ROOT / "paper" / "lint-audit-110.json"
OUT_MD = ROOT / "paper" / "lint-audit-110.md"

CLONE_TIMEOUT_S = 240   # 4 min per clone
LINT_TIMEOUT_S = 300    # 5 min per lint (kill anything slower)
ALLOWED_HOSTS = ("github.com", "gitlab.com")


def shallow_clone(url: str, dest: Path, timeout: int = CLONE_TIMEOUT_S) -> tuple[bool, str]:
    """Shallow clone (depth=1, no LFS, no auth prompt). Returns (success, message)."""
    if dest.exists() and any(dest.iterdir()):
        return True, "already_cloned"
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ,
           "GIT_LFS_SKIP_SMUDGE": "1",
           "GIT_TERMINAL_PROMPT": "0",
           "GIT_ASKPASS": "/bin/echo"}
    # Strip any /tree/<branch>/path or /blob/<...> from URL — git clone needs base repo
    base = url.split("/tree/")[0].split("/blob/")[0].split("#")[0].rstrip("/")
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", base, str(dest)],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if r.returncode == 0:
            return True, "cloned"
        # Sanitize stderr — keep the headline reason but cap length
        err = r.stderr.strip().splitlines()
        first = err[0][:160] if err else ""
        return False, f"clone_failed: {first}"
    except subprocess.TimeoutExpired:
        return False, "clone_timeout"
    except Exception as e:
        return False, f"clone_exception: {type(e).__name__}: {str(e)[:120]}"


def count_files(repo: Path, suffix: str, cap: int = 5000) -> int:
    """Count files with given suffix; cap to avoid pathological repos."""
    n = 0
    for _ in repo.rglob(f"*{suffix}"):
        n += 1
        if n >= cap:
            return n
    return n


def run_mlgg_lint(repo: Path, timeout: int = LINT_TIMEOUT_S) -> dict:
    """Run mlgg-lint --format json on repo, return parsed result.

    Stdout = list of finding dicts. Stderr captured separately so warnings
    (e.g., DeprecationWarning from .ipynb cells with '\d', '\C') don't
    pollute JSON parse.
    """
    cmd = [sys.executable, "-W", "ignore", "-m", "mlgg_lint", "check",
           str(repo), "--format", "json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=str(ROOT))
        try:
            payload = json.loads(r.stdout) if r.stdout.strip() else []
        except json.JSONDecodeError as exc:
            payload = {"_json_decode_error": str(exc)[:200]}
        return {
            "exit_code": r.returncode,
            "stderr_tail": r.stderr[-200:] if r.stderr else "",
            "payload": payload,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stderr_tail": "lint_timeout", "payload": []}
    except Exception as e:
        return {"exit_code": -2,
                "stderr_tail": f"lint_exception: {type(e).__name__}",
                "payload": []}


def summarize_findings(findings: list) -> dict:
    """Strip everything except rule_id + severity (IP compliance: do NOT
    retain message field, which may quote source code from the audited repo).
    """
    if not isinstance(findings, list):
        return {"finding_count": 0, "rule_counts": {}, "severity_counts": {},
                "top_5_rules": []}
    rule_counter = Counter(f.get("rule_id") for f in findings if f.get("rule_id"))
    sev_counter = Counter(f.get("severity") for f in findings if f.get("severity"))
    return {
        "finding_count": len(findings),
        "rule_counts": dict(rule_counter.most_common()),
        "severity_counts": dict(sev_counter.most_common()),
        "top_5_rules": [r for r, _ in rule_counter.most_common(5)],
    }


def main() -> int:
    if not CORPUS_PATH.exists():
        print(f"ERROR: {CORPUS_PATH} not found.", file=sys.stderr)
        return 1
    corpus = json.loads(CORPUS_PATH.read_text())["results"]
    targets = []
    for r in corpus:
        repo = r.get("primary_repo")
        if not repo:
            continue
        if any(h in repo for h in ALLOWED_HOSTS):
            targets.append(r)
    print(f"Corpus rows: {len(corpus)}, targets after filter: {len(targets)}",
          file=sys.stderr)

    audit_results = []
    for i, r in enumerate(targets):
        pid = r["id"]
        url = r["primary_repo"].split("&#")[0].strip()
        dest = CACHE_DIR / pid

        print(f"\n[{i+1}/{len(targets)}] {pid}: {url[:80]}", file=sys.stderr)
        ok, msg = shallow_clone(url, dest)
        result = {
            "id": pid,
            "primary_repo": url,
            "clone_status": msg,
            "python_files": 0,
            "notebook_files": 0,
            "finding_count": 0,
            "rule_counts": {},
            "severity_counts": {},
            "top_5_rules": [],
            "lint_exit_code": None,
        }

        if ok:
            n_py = count_files(dest, ".py")
            n_nb = count_files(dest, ".ipynb")
            result["python_files"] = n_py
            result["notebook_files"] = n_nb
            print(f"  clone={msg}, py={n_py}, ipynb={n_nb}", file=sys.stderr)
            if n_py > 0 or n_nb > 0:
                lint = run_mlgg_lint(dest)
                payload = lint.get("payload", [])
                findings = payload if isinstance(payload, list) else []
                summary = summarize_findings(findings)
                result.update(summary)
                result["lint_exit_code"] = lint.get("exit_code")
                print(f"  lint exit={lint.get('exit_code')}, "
                      f"findings={summary['finding_count']}, "
                      f"top={summary['top_5_rules']}", file=sys.stderr)
            else:
                print("  no Python or notebook files, skipping lint",
                      file=sys.stderr)
        else:
            print(f"  clone failed: {msg}", file=sys.stderr)
        audit_results.append(result)

    # Aggregate ----------------------------------------------------------------
    # Two views:
    #   - paper_count[rule]: number of papers in which rule fired ≥1 time
    #   - total_findings[rule]: total finding count for rule across corpus
    paper_count: Counter[str] = Counter()
    total_findings: Counter[str] = Counter()
    sev_total: Counter[str] = Counter()
    for r in audit_results:
        for rule, cnt in r.get("rule_counts", {}).items():
            paper_count[rule] += 1
            total_findings[rule] += cnt
        for sev, cnt in r.get("severity_counts", {}).items():
            sev_total[sev] += cnt

    n_total = len(audit_results)
    n_cloned = sum(1 for r in audit_results
                   if r["clone_status"] in ("cloned", "already_cloned"))
    n_with_py = sum(1 for r in audit_results
                    if r["python_files"] > 0 or r["notebook_files"] > 0)
    n_with_findings = sum(1 for r in audit_results
                          if r["finding_count"] > 0)
    total_findings_sum = sum(r["finding_count"] for r in audit_results)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(CORPUS_PATH.relative_to(ROOT)),
        "corpus_size": len(corpus),
        "stats": {
            "total_targets": n_total,
            "successfully_cloned": n_cloned,
            "have_python_files": n_with_py,
            "lint_findings_at_least_one": n_with_findings,
            "total_findings_aggregate": total_findings_sum,
            "by_severity": dict(sev_total.most_common()),
        },
        "rules_fired_across_corpus": dict(paper_count.most_common()),
        "rules_total_findings": dict(total_findings.most_common()),
        "results": audit_results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    # Markdown ----------------------------------------------------------------
    md: list[str] = [
        f"# mlgg-lint audit on {n_total}-repo cohort-binary corpus (v1)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Source corpus: `{CORPUS_PATH.relative_to(ROOT)}` ({len(corpus)} papers, "
        f"{n_total} GitHub/GitLab targets after filter).",
        "",
        "## Headline numbers",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Repos targeted (host ∈ github/gitlab) | {n_total} |",
        f"| Successfully cloned | {n_cloned} |",
        f"| Repos with Python or notebook files | {n_with_py} |",
        f"| Repos with ≥1 mlgg-lint finding | {n_with_findings} |",
        f"| Total findings across corpus | {total_findings_sum} |",
        "",
        "### Findings by severity",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for sev, cnt in sev_total.most_common():
        md.append(f"| {sev} | {cnt} |")
    md.append("")

    md.extend([
        "## Top 15 most common rules (by paper count, ie how many papers fired)",
        "",
        "| Rule | Papers | Total findings |",
        "|---|---:|---:|",
    ])
    for rule, p_cnt in paper_count.most_common(15):
        md.append(f"| `{rule}` | {p_cnt} | {total_findings.get(rule, 0)} |")
    md.append("")

    md.extend([
        "## Per-paper detail",
        "",
        "| ID | Repo (host/path) | Clone | Py | Nb | Findings | Top rules |",
        "|---|---|---|---:|---:|---:|---|",
    ])
    for r in audit_results:
        url = r["primary_repo"]
        if "github.com/" in url:
            short = url.split("github.com/", 1)[-1]
        elif "gitlab.com/" in url:
            short = url.split("gitlab.com/", 1)[-1]
        else:
            short = url
        rules_short = ", ".join(r.get("top_5_rules", [])[:4])
        clone_short = r["clone_status"][:18]
        md.append(
            f"| {r['id']} | `{short[:55]}` | {clone_short} | "
            f"{r['python_files']} | {r['notebook_files']} | "
            f"{r['finding_count']} | {rules_short} |"
        )
    OUT_MD.write_text("\n".join(md) + "\n")

    # Console summary ----------------------------------------------------------
    print("\n=== DONE ===")
    print(f"Targets: {n_total}, cloned: {n_cloned}, with code: {n_with_py}, "
          f"with findings: {n_with_findings}")
    print(f"Total findings aggregate: {total_findings_sum}")
    print("\nTop rules (papers fired):")
    for rule, cnt in paper_count.most_common(12):
        print(f"  {cnt:3} papers / {total_findings.get(rule, 0):4} total: {rule}")
    print("\nReports:")
    print(f"  {OUT_JSON.relative_to(ROOT)}")
    print(f"  {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
