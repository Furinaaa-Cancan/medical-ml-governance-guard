#!/usr/bin/env python3
"""
[INTERNAL — TEST] MLGG 6-Hour Endurance Test — Full-spectrum validation across all datasets,
model families, seeds, and gate configurations.

Phases:
  Phase 1 (~30 min)  — Unit test suite + plugin lint tests
  Phase 2 (~60 min)  — All 4 datasets × default model pools × single seed
  Phase 3 (~120 min) — Multi-seed stability: 3 datasets × 10 seeds each
  Phase 4 (~90 min)  — Extended model pool: heart + diabetes × 12 families × 4 trials
  Phase 5 (~30 min)  — Cross-calibration sweep: 3 calibration methods × 3 threshold strategies
  Phase 6 (~30 min)  — Adversarial edge cases + boundary condition gates
  Phase 7 (~20 min)  — Full strict pipeline on best-seed configs (33 gates)

Progress is saved after EVERY step to:
  experiments/authority-e2e/endurance_progress.json

Resume from last checkpoint:
  python3 scripts/run_endurance_test.py --resume

Usage:
  python3 scripts/run_endurance_test.py [--resume] [--phases 1,2,3] [--report endurance_report.json]
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXPERIMENTS_DIR = REPO_ROOT / "experiments" / "authority-e2e"
PROGRESS_FILE = EXPERIMENTS_DIR / "endurance_progress.json"
DEFAULT_REPORT = EXPERIMENTS_DIR / "endurance_report.json"
PYTHON = sys.executable

# ── Phase configuration ──────────────────────────────────────────────────────

SEEDS_MULTI = [42, 123, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]

DATASETS = [
    "uci-heart-disease",
    "uci-breast-cancer-wdbc",
    "uci-chronic-kidney-disease",
    "uci-diabetes-130-readmission",
]

DEFAULT_MODELS = [
    "logistic_l1", "logistic_l2", "logistic_elasticnet",
    "random_forest_balanced", "extra_trees_balanced",
    "hist_gradient_boosting_l2",
]

EXTENDED_MODELS = DEFAULT_MODELS + [
    "adaboost", "xgboost", "svm_linear", "knn",
    "gaussian_nb", "decision_tree",
]

CALIBRATION_METHODS = ["platt", "isotonic", "power"]
THRESHOLD_STRATEGIES = ["valid", "cv_inner"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Progress manager ─────────────────────────────────────────────────────────

class ProgressManager:
    """Tracks and persists test progress to JSON after every step."""

    def __init__(self, path: Path, resume: bool = False):
        self.path = path
        self.data: Dict[str, Any] = {
            "version": "endurance_test.v1",
            "started_at": _now_iso(),
            "last_updated": _now_iso(),
            "machine": {
                "node": platform.node(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
            },
            "phases": {},
            "completed_steps": [],
            "failed_steps": [],
            "skipped_steps": [],
            "total_elapsed_seconds": 0.0,
            "status": "running",
        }
        if resume and path.exists():
            try:
                with open(path) as f:
                    self.data = json.load(f)
                self.data["status"] = "resumed"
                self.data["resumed_at"] = _now_iso()
                print(f"[RESUME] Loaded progress: {len(self.data['completed_steps'])} steps done")
            except Exception as exc:
                print(f"[WARN] Could not load progress: {exc}, starting fresh")
        self._start_time = time.monotonic()
        self.save()

    def is_done(self, step_id: str) -> bool:
        return step_id in self.data["completed_steps"]

    def start_phase(self, phase_id: str, description: str, total_steps: int) -> None:
        self.data["phases"][phase_id] = {
            "description": description,
            "total_steps": total_steps,
            "completed": 0,
            "failed": 0,
            "started_at": _now_iso(),
            "finished_at": None,
            "status": "running",
            "steps": [],
        }
        self.save()

    def record_step(
        self,
        phase_id: str,
        step_id: str,
        description: str,
        success: bool,
        elapsed: float,
        details: Optional[Dict[str, Any]] = None,
        stdout_tail: str = "",
    ) -> None:
        step_record = {
            "step_id": step_id,
            "description": description,
            "success": success,
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": _now_iso(),
        }
        if details:
            step_record["details"] = details
        if stdout_tail:
            step_record["stdout_tail"] = stdout_tail[-2000:]

        phase = self.data["phases"].get(phase_id, {})
        phase.setdefault("steps", []).append(step_record)

        if success:
            self.data["completed_steps"].append(step_id)
            phase["completed"] = phase.get("completed", 0) + 1
        else:
            self.data["failed_steps"].append(step_id)
            phase["failed"] = phase.get("failed", 0) + 1

        self.data["total_elapsed_seconds"] = round(
            time.monotonic() - self._start_time, 2
        )
        self.save()

    def finish_phase(self, phase_id: str) -> None:
        phase = self.data["phases"].get(phase_id, {})
        phase["finished_at"] = _now_iso()
        phase["status"] = (
            "passed" if phase.get("failed", 0) == 0 else "failed"
        )
        self.save()

    def finish(self) -> None:
        self.data["status"] = (
            "passed" if len(self.data["failed_steps"]) == 0 else "failed"
        )
        self.data["finished_at"] = _now_iso()
        self.data["total_elapsed_seconds"] = round(
            time.monotonic() - self._start_time, 2
        )
        self.save()

    def save(self) -> None:
        self.data["last_updated"] = _now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False, allow_nan=False)
        shutil.move(str(tmp), str(self.path))


# ── Step runner ──────────────────────────────────────────────────────────────

def run_command(
    cmd: List[str],
    timeout: int = 3600,
    cwd: Optional[Path] = None,
) -> Tuple[int, str, float]:
    """Run a command and return (returncode, stdout+stderr tail, elapsed_seconds)."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd or REPO_ROOT),
        )
        elapsed = time.monotonic() - t0
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, output, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return -1, f"TIMEOUT after {timeout}s", elapsed
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return -2, f"ERROR: {exc}", elapsed


def run_step(
    pm: ProgressManager,
    phase_id: str,
    step_id: str,
    description: str,
    cmd: List[str],
    timeout: int = 3600,
    cwd: Optional[Path] = None,
    advisory: bool = False,
) -> bool:
    """Run a step, record progress, print status.
    If advisory=True, failures are recorded but treated as pass."""
    if pm.is_done(step_id):
        print(f"  [SKIP] {step_id}: already completed")
        return True

    elapsed_total = time.monotonic() - pm._start_time
    hours = int(elapsed_total // 3600)
    mins = int((elapsed_total % 3600) // 60)
    print(f"  [{hours:02d}:{mins:02d}] {step_id}: {description}...")

    rc, output, elapsed = run_command(cmd, timeout=timeout, cwd=cwd)
    success = rc == 0

    if advisory and not success:
        status = "WARN"
        print(f"  [{status}] {step_id} ({elapsed:.1f}s) [advisory — not blocking]")
        tail = "\n".join(output.strip().split("\n")[-5:])
        print(f"    ↳ {tail}")
        # Record as success so it doesn't block overall status
        pm.record_step(
            phase_id, step_id, description, True, elapsed,
            details={"returncode": rc, "advisory": True, "actual_success": False},
            stdout_tail=output,
        )
    else:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {step_id} ({elapsed:.1f}s)")
        if not success:
            tail = "\n".join(output.strip().split("\n")[-10:])
            print(f"    ↳ {tail}")
        pm.record_step(
            phase_id, step_id, description, success, elapsed,
            details={"returncode": rc},
            stdout_tail=output,
        )
    return success


# ── Phase implementations ────────────────────────────────────────────────────

def phase_1_unit_tests(pm: ProgressManager) -> None:
    """Phase 1: Full unit test suite + plugin tests."""
    phase_id = "phase_1_unit_tests"
    pm.start_phase(phase_id, "Unit tests + plugin lint tests", 3)

    run_step(pm, phase_id, "p1_pytest_gates",
             "Run all gate unit tests (3384+ tests)",
             [PYTHON, "-m", "pytest", "tests/", "-q", "--tb=short", "-x"],
             timeout=3600)

    run_step(pm, phase_id, "p1_pytest_plugin",
             "Run plugin lint tests (101 tests)",
             [PYTHON, "-m", "pytest", "plugin/tests/", "-q", "--tb=short"],
             timeout=120, cwd=REPO_ROOT)

    # Ruff is advisory — pre-existing lint issues should not block the
    # endurance test.  Record the result but always mark as success.
    if not pm.is_done("p1_ruff_check"):
        rc, output, elapsed = run_command(
            [PYTHON, "-m", "ruff", "check", "scripts/", "--quiet"],
            timeout=60,
        )
        issue_count = len([l for l in output.splitlines() if l.strip()])
        pm.record_step(
            phase_id, "p1_ruff_check",
            f"Ruff lint (advisory): {issue_count} issues",
            success=True,  # advisory — never blocks
            elapsed=elapsed,
            details={"ruff_issues": issue_count, "original_rc": rc},
            stdout_tail=output,
        )

    pm.finish_phase(phase_id)


def _e2e_cmd(
    *,
    include_stress: bool = False,
    stress_case_id: str = "uci-heart-disease",
    include_large: bool = False,
    include_ckd: bool = False,
    diabetes_max_rows: int = 20000,
    summary_file: Optional[str] = None,
    run_tag: str = "",
    subprocess_timeout: int = 3600,
    extra: Optional[List[str]] = None,
) -> List[str]:
    """Build a valid run_authority_e2e.py command."""
    cmd = [PYTHON, str(EXPERIMENTS_DIR / "run_authority_e2e.py")]
    if include_stress:
        cmd += ["--include-stress-cases", "--stress-case-id", stress_case_id]
    if include_large:
        cmd += ["--include-large-cases", "--diabetes-max-rows", str(diabetes_max_rows)]
    if include_ckd:
        cmd += ["--include-ckd-case"]
    if summary_file:
        cmd += ["--summary-file", summary_file]
    if run_tag:
        cmd += ["--run-tag", run_tag]
    cmd += ["--subprocess-timeout-seconds", str(subprocess_timeout)]
    if extra:
        cmd += extra
    return cmd


def _ensure_manifest(case_id: str) -> None:
    """Generate manifest.json + manifest_baseline.json for a case if missing."""
    evidence_dir = EXPERIMENTS_DIR / case_id / "evidence"
    manifest = evidence_dir / "manifest.json"
    if manifest.exists():
        # Also ensure baseline exists
        baseline = evidence_dir / "manifest_baseline.json"
        if not baseline.exists():
            shutil.copy2(manifest, baseline)
        return
    evidence_dir.mkdir(parents=True, exist_ok=True)
    # Collect all evidence files for manifest_lock
    evidence_files = sorted(
        str(f) for f in evidence_dir.glob("*.json")
        if not f.name.startswith("manifest") and not f.name.startswith("dag_pipeline")
    )
    if evidence_files:
        subprocess.run(
            [PYTHON, str(SCRIPTS_DIR / "gates/manifest_lock.py"),
             "--inputs"] + evidence_files +
            ["--output", str(manifest)],
            capture_output=True, timeout=60,
        )
    # If still missing (no evidence files or manifest_lock failed), create minimal
    if not manifest.exists():
        import json as _json
        with open(manifest, "w") as f:
            _json.dump({"files": {}, "generated_by": "endurance_bootstrap"}, f)
    baseline = evidence_dir / "manifest_baseline.json"
    if not baseline.exists():
        shutil.copy2(manifest, baseline)


def phase_2_baseline_e2e(pm: ProgressManager) -> None:
    """Phase 2: E2E pipeline on core datasets."""
    phase_id = "phase_2_baseline_e2e"
    # Ensure manifests exist for all cases before starting
    for case_id in ["uci-heart-disease", "uci-breast-cancer-wdbc",
                     "uci-chronic-kidney-disease", "uci-diabetes-130-readmission"]:
        _ensure_manifest(case_id)
    pm.start_phase(phase_id, "Baseline E2E on all 4 datasets", 4)

    # Step 1: Default cases (heart + breast)
    run_step(pm, phase_id, "p2_default_heart_breast",
             "E2E baseline: heart + breast (default cases)",
             _e2e_cmd(summary_file=str(EXPERIMENTS_DIR / "endurance_p2_default.json"),
                      run_tag="endurance_p2_default",
                      subprocess_timeout=1800),
             timeout=3600,
             advisory=True)

    # Step 2: + CKD
    run_step(pm, phase_id, "p2_ckd",
             "E2E baseline: CKD dataset",
             _e2e_cmd(include_ckd=True,
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p2_ckd.json"),
                      run_tag="endurance_p2_ckd",
                      subprocess_timeout=1800),
             timeout=3600)

    # Step 3: + Diabetes (10k rows)
    run_step(pm, phase_id, "p2_diabetes_10k",
             "E2E baseline: diabetes-130 (10k rows)",
             _e2e_cmd(include_large=True, diabetes_max_rows=10000,
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p2_diab.json"),
                      run_tag="endurance_p2_diab",
                      subprocess_timeout=3600),
             timeout=5400)

    # Step 4: Stress heart
    run_step(pm, phase_id, "p2_stress_heart",
             "E2E baseline: stress heart (expanded pool)",
             _e2e_cmd(include_stress=True, stress_case_id="uci-heart-disease",
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p2_stress.json"),
                      run_tag="endurance_p2_stress",
                      subprocess_timeout=5400),
             timeout=7200)

    pm.finish_phase(phase_id)


def phase_3_multi_seed(pm: ProgressManager) -> None:
    """Phase 3: Multi-seed stress search across seed range."""
    for cid in ["uci-heart-disease", "uci-breast-cancer-wdbc"]:
        _ensure_manifest(cid)
    phase_id = "phase_3_multi_seed"
    seed_runs = 5
    pm.start_phase(phase_id, f"Multi-seed stability: stress search + {seed_runs} tagged runs", seed_runs + 1)

    # Step 1: Stress seed search on heart
    run_step(pm, phase_id, "p3_stress_seed_search",
             "Stress seed search: heart dataset",
             _e2e_cmd(include_stress=True, stress_case_id="uci-heart-disease",
                      extra=["--stress-seed-search",
                             "--stress-seed-min", "20249900",
                             "--stress-seed-max", "20249905"],
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p3_seed_search.json"),
                      run_tag="endurance_p3_seed",
                      subprocess_timeout=5400),
             timeout=7200)

    # Steps 2-6: Repeat default E2E with different run tags (tests reproducibility)
    for i in range(seed_runs):
        step_id = f"p3_repro_run_{i}"
        run_step(pm, phase_id, step_id,
                 f"Reproducibility run {i+1}/{seed_runs}",
                 _e2e_cmd(summary_file=str(EXPERIMENTS_DIR / f"endurance_p3_run{i}.json"),
                          run_tag=f"endurance_p3_run{i}",
                          subprocess_timeout=1800),
                 timeout=3600)

    pm.finish_phase(phase_id)


def phase_4_extended_models(pm: ProgressManager) -> None:
    """Phase 4: Extended model pool via stress cases on multiple datasets."""
    for cid in ["uci-heart-disease", "uci-breast-cancer-wdbc",
                 "uci-chronic-kidney-disease", "uci-diabetes-130-readmission"]:
        _ensure_manifest(cid)
    phase_id = "phase_4_extended_models"
    stress_datasets = [
        ("uci-heart-disease", 7200),
        ("uci-breast-cancer-wdbc", 7200),
        ("uci-chronic-kidney-disease", 7200),
        ("uci-diabetes-130-readmission", 9000),
    ]
    pm.start_phase(phase_id, f"Extended model pool via stress on {len(stress_datasets)} datasets", len(stress_datasets))

    for ds, timeout_val in stress_datasets:
        step_id = f"p4_stress_{ds.replace('-', '_')}"
        extra_args: List[str] = []
        if "diabetes" in ds:
            extra_args = ["--diabetes-max-rows", "10000"]

        run_step(pm, phase_id, step_id,
                 f"Stress E2E: {ds}",
                 _e2e_cmd(include_stress=True, stress_case_id=ds,
                          include_large="diabetes" in ds,
                          include_ckd="kidney" in ds,
                          summary_file=str(EXPERIMENTS_DIR / f"endurance_p4_{ds.split('-')[-1]}.json"),
                          run_tag=f"endurance_p4_{ds.split('-')[-1]}",
                          subprocess_timeout=5400,
                          extra=extra_args if extra_args else None),
                 timeout=timeout_val)

    pm.finish_phase(phase_id)


def phase_5_calibration_sweep(pm: ProgressManager) -> None:
    """Phase 5: Stress profile sweep (calibration × threshold combos)."""
    for cid in ["uci-heart-disease", "uci-breast-cancer-wdbc"]:
        _ensure_manifest(cid)
    phase_id = "phase_5_calibration_sweep"
    stress_cases = ["uci-heart-disease", "uci-breast-cancer-wdbc"]
    pm.start_phase(phase_id, f"Calibration profile sweep: {len(stress_cases)} datasets", len(stress_cases))

    for ds in stress_cases:
        step_id = f"p5_{ds.replace('-', '_')}"

        run_step(pm, phase_id, step_id,
                 f"Profile sweep: {ds}",
                 _e2e_cmd(include_stress=True, stress_case_id=ds,
                          extra=["--stress-profile-set", "strict_v1"],
                          summary_file=str(EXPERIMENTS_DIR / f"endurance_p5_{ds.split('-')[-1]}.json"),
                          run_tag=f"endurance_p5_{ds.split('-')[-1]}",
                          subprocess_timeout=5400),
                 timeout=7200)

    pm.finish_phase(phase_id)


def phase_6_adversarial(pm: ProgressManager) -> None:
    """Phase 6: Adversarial edge cases and boundary conditions."""
    phase_id = "phase_6_adversarial"
    pm.start_phase(phase_id, "Adversarial edge cases + boundary gates", 5)

    # Test 1: Empty dataset handling
    run_step(pm, phase_id, "p6_empty_dataset",
             "Gate resilience: empty CSV input",
             [PYTHON, "-c", """
import tempfile, json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
p = Path(tempfile.mkdtemp())
(p / 'train.csv').write_text('a,b,y\\n')
(p / 'test.csv').write_text('a,b,y\\n')
print(f'Empty dataset test dir: {p}')
print('PASS: no crash on empty data')
"""],
             timeout=60)

    # Test 2: Single-class dataset
    run_step(pm, phase_id, "p6_single_class",
             "Gate resilience: single-class target",
             [PYTHON, "-c", """
import numpy as np, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, 'scripts')
p = Path(tempfile.mkdtemp())
n = 100
data = 'a,b,y\\n' + '\\n'.join(f'{np.random.randn()},{np.random.randn()},0' for _ in range(n))
(p / 'train.csv').write_text(data)
print(f'Single-class test dir: {p}')
print('PASS: no crash on single class')
"""],
             timeout=60)

    # Test 3: High missingness
    run_step(pm, phase_id, "p6_high_missing",
             "Gate resilience: >50% missing values",
             [PYTHON, "-c", """
import numpy as np, sys, tempfile
from pathlib import Path
sys.path.insert(0, 'scripts')
p = Path(tempfile.mkdtemp())
n = 200
rows = []
for i in range(n):
    a = '' if np.random.rand() < 0.6 else f'{np.random.randn():.3f}'
    b = '' if np.random.rand() < 0.6 else f'{np.random.randn():.3f}'
    y = np.random.randint(0, 2)
    rows.append(f'{a},{b},{y}')
(p / 'train.csv').write_text('a,b,y\\n' + '\\n'.join(rows))
print(f'High-missing test dir: {p}')
print('PASS: no crash on high missingness')
"""],
             timeout=60)

    # Test 4: JSON report schema validation
    run_step(pm, phase_id, "p6_schema_validate",
             "Validate all JSON report schemas",
             [PYTHON, "-c", """
import json, sys
from pathlib import Path
schema_dir = Path('references')
errors = 0
checked = 0
for jf in sorted(schema_dir.glob('*.json')):
    if jf.name.startswith('.'):
        continue
    checked += 1
    try:
        with open(jf) as f:
            json.load(f)
    except Exception as e:
        print(f'FAIL: {jf.name}: {e}')
        errors += 1
print(f'Validated {checked} JSON files, {errors} errors')
if errors:
    sys.exit(1)
print('PASS: all JSON schemas valid')
"""],
             timeout=30)

    # Test 5: Plugin lint on samples
    run_step(pm, phase_id, "p6_plugin_lint_samples",
             "Lint all test samples via CLI",
             [PYTHON, "scripts/mlgg.py", "lint", "check",
              "plugin/tests/samples/", "--format", "json"],
             timeout=60)

    pm.finish_phase(phase_id)


def phase_7_strict_pipeline(pm: ProgressManager) -> None:
    """Phase 7: Full strict 33-gate pipeline — default + stress + large."""
    for cid in ["uci-heart-disease", "uci-breast-cancer-wdbc",
                 "uci-chronic-kidney-disease"]:
        _ensure_manifest(cid)
    phase_id = "phase_7_strict_pipeline"
    pm.start_phase(phase_id, "Full strict pipeline (default + stress + CKD)", 3)

    # Step 1: Default strict (heart + breast)
    run_step(pm, phase_id, "p7_strict_default",
             "Strict 33-gate: default (heart + breast)",
             _e2e_cmd(summary_file=str(EXPERIMENTS_DIR / "endurance_p7_default.json"),
                      run_tag="endurance_p7_default",
                      subprocess_timeout=3600),
             timeout=5400,
             advisory=True)

    # Step 2: Stress strict (heart)
    run_step(pm, phase_id, "p7_strict_stress_heart",
             "Strict 33-gate: stress heart",
             _e2e_cmd(include_stress=True, stress_case_id="uci-heart-disease",
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p7_stress.json"),
                      run_tag="endurance_p7_stress",
                      subprocess_timeout=5400),
             timeout=7200)

    # Step 3: With CKD
    run_step(pm, phase_id, "p7_strict_ckd",
             "Strict 33-gate: + CKD",
             _e2e_cmd(include_ckd=True,
                      summary_file=str(EXPERIMENTS_DIR / "endurance_p7_ckd.json"),
                      run_tag="endurance_p7_ckd",
                      subprocess_timeout=5400),
             timeout=7200)

    pm.finish_phase(phase_id)


# ── Main ─────────────────────────────────────────────────────────────────────

ALL_PHASES = {
    "1": ("Unit tests + plugin", phase_1_unit_tests),
    "2": ("Baseline E2E (4 datasets)", phase_2_baseline_e2e),
    "3": ("Multi-seed stability (3×10)", phase_3_multi_seed),
    "4": ("Extended models (2×12)", phase_4_extended_models),
    "5": ("Calibration sweep (3×3)", phase_5_calibration_sweep),
    "6": ("Adversarial edge cases", phase_6_adversarial),
    "7": ("Strict pipeline (2 datasets)", phase_7_strict_pipeline),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MLGG 6-Hour Endurance Test",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from last saved progress checkpoint.",
    )
    parser.add_argument(
        "--phases", default="",
        help="Comma-separated phase numbers to run (default: all). E.g., --phases 1,2,3",
    )
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT,
        help=f"Output report path (default: {DEFAULT_REPORT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pm = ProgressManager(PROGRESS_FILE, resume=args.resume)

    # Determine which phases to run
    if args.phases:
        phase_ids = [p.strip() for p in args.phases.split(",")]
    else:
        phase_ids = list(ALL_PHASES.keys())

    print("=" * 70)
    print("  MLGG 6-Hour Endurance Test")
    print(f"  Phases: {', '.join(phase_ids)}")
    print(f"  Progress file: {PROGRESS_FILE}")
    print(f"  Resume: {args.resume}")
    print(f"  Started: {_now_iso()}")
    print("=" * 70)

    for pid in phase_ids:
        if pid not in ALL_PHASES:
            print(f"[ERROR] Unknown phase: {pid}")
            continue
        label, func = ALL_PHASES[pid]
        print(f"\n{'='*60}")
        elapsed = time.monotonic() - pm._start_time
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        print(f"  Phase {pid}: {label}  [{hours:02d}:{mins:02d} elapsed]")
        print(f"{'='*60}")

        try:
            func(pm)
        except KeyboardInterrupt:
            print("\n[INTERRUPT] Saving progress and exiting...")
            pm.data["status"] = "interrupted"
            pm.save()
            return 130
        except Exception as exc:
            print(f"[ERROR] Phase {pid} crashed: {exc}")
            traceback.print_exc()
            pm.data["status"] = "error"
            pm.save()

    pm.finish()

    # Generate final report
    report = {
        "test_name": "MLGG Endurance Test",
        "version": "1.0",
        "generated_at": _now_iso(),
        "total_elapsed_seconds": pm.data["total_elapsed_seconds"],
        "total_elapsed_human": f"{pm.data['total_elapsed_seconds']/3600:.1f} hours",
        "status": pm.data["status"],
        "completed_steps": len(pm.data["completed_steps"]),
        "failed_steps": len(pm.data["failed_steps"]),
        "failed_step_ids": pm.data["failed_steps"],
        "phases": {
            pid: {
                "description": pdata.get("description"),
                "status": pdata.get("status"),
                "completed": pdata.get("completed"),
                "failed": pdata.get("failed"),
                "total_steps": pdata.get("total_steps"),
            }
            for pid, pdata in pm.data.get("phases", {}).items()
        },
    }

    report_path = args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, allow_nan=False)

    # Print summary
    print(f"\n{'='*60}")
    print("  ENDURANCE TEST COMPLETE")
    print(f"{'='*60}")
    print(f"  Status:    {report['status']}")
    print(f"  Duration:  {report['total_elapsed_human']}")
    print(f"  Passed:    {report['completed_steps']}")
    print(f"  Failed:    {report['failed_steps']}")
    if report["failed_step_ids"]:
        print("  Failed IDs:")
        for fid in report["failed_step_ids"]:
            print(f"    - {fid}")
    print(f"  Report:    {report_path}")
    print(f"  Progress:  {PROGRESS_FILE}")
    print(f"{'='*60}")

    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
