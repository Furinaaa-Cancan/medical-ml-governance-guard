#!/bin/bash
# ============================================================
# Overnight 33-Gate Pipeline Run
# ============================================================
# Runs the full MLGG pipeline on all large datasets.
# Designed to run unattended for several hours.
#
# Usage:
#   nohup bash experiments/overnight_pipeline_run.sh > experiments/overnight_run.log 2>&1 &
#
# Or simply:
#   bash experiments/overnight_pipeline_run.sh
# ============================================================

set -o pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_ROOT"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_BASE="experiments/overnight_${TIMESTAMP}"
SUMMARY_FILE="${OUTPUT_BASE}/summary.json"
ERROR_LOG="${OUTPUT_BASE}/errors.jsonl"
FULL_LOG="${OUTPUT_BASE}/full_run.log"

mkdir -p "$OUTPUT_BASE"

echo "============================================================"
echo "MLGG Overnight Pipeline Run"
echo "Started: $(date)"
echo "Output:  ${OUTPUT_BASE}"
echo "============================================================"

# ---------------------------------------------------------------------------
# Dataset definitions
# ---------------------------------------------------------------------------

declare -A DATASETS
DATASETS=(
    ["diabetes130_full"]="examples/diabetes130_full_readmission.csv"
    ["brfss2022"]="examples/brfss2022_diabetes.csv"
    ["nhis2022"]="examples/nhis2022_diabetes.csv"
    ["nhanes"]="examples/nhanes_diabetes.csv"
    ["support2"]="examples/support2.csv"
    ["heart"]="examples/heart_disease.csv"
    ["breast"]="examples/breast_cancer.csv"
    ["pima"]="examples/pima_diabetes.csv"
)

# Target columns per dataset
declare -A TARGET_COLS
TARGET_COLS=(
    ["diabetes130_full"]="y"
    ["brfss2022"]="y"
    ["nhis2022"]="y"
    ["nhanes"]="y"
    ["support2"]="hospdead"
    ["heart"]="y"
    ["breast"]="y"
    ["pima"]="y"
)

# Patient ID columns
declare -A PID_COLS
PID_COLS=(
    ["diabetes130_full"]="patient_id"
    ["brfss2022"]="patient_id"
    ["nhis2022"]="patient_id"
    ["nhanes"]="patient_id"
    ["support2"]=""
    ["heart"]="patient_id"
    ["breast"]="patient_id"
    ["pima"]="patient_id"
)

# Time columns
declare -A TIME_COLS
TIME_COLS=(
    ["diabetes130_full"]="event_time"
    ["brfss2022"]="event_time"
    ["nhis2022"]="event_time"
    ["nhanes"]=""
    ["support2"]=""
    ["heart"]="event_time"
    ["breast"]="event_time"
    ["pima"]=""
)

# Phenotype definition specs (for definition_variable_guard)
declare -A PHENOTYPE_SPECS
PHENOTYPE_SPECS=(
    ["nhanes"]="examples/nhanes_diabetes_phenotype_spec.json"
)

# Split strategies
declare -A SPLIT_STRATEGIES
SPLIT_STRATEGIES=(
    ["diabetes130_full"]="grouped_temporal"
    ["brfss2022"]="grouped_temporal"
    ["nhis2022"]="grouped_temporal"
    ["nhanes"]="stratified_grouped"
    ["support2"]="stratified_grouped"
    ["heart"]="grouped_temporal"
    ["breast"]="grouped_temporal"
    ["pima"]="stratified_grouped"
)

# Ordered list (large first)
DATASET_ORDER="diabetes130_full brfss2022 nhis2022 nhanes support2 heart breast pima"

# ---------------------------------------------------------------------------
# Initialize results
# ---------------------------------------------------------------------------

TOTAL=0
PASSED=0
FAILED=0
ERRORS=0
RESULTS=""

echo '{"run_id": "'${TIMESTAMP}'", "started": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "datasets": [' > "$SUMMARY_FILE"

# ---------------------------------------------------------------------------
# Run each dataset
# ---------------------------------------------------------------------------

FIRST=true
for DNAME in $DATASET_ORDER; do
    CSV="${DATASETS[$DNAME]}"
    TARGET="${TARGET_COLS[$DNAME]}"
    PID="${PID_COLS[$DNAME]}"
    TIME="${TIME_COLS[$DNAME]}"
    SPLIT="${SPLIT_STRATEGIES[$DNAME]}"
    PHENO_SPEC="${PHENOTYPE_SPECS[$DNAME]:-}"

    # Skip if CSV doesn't exist
    if [ ! -f "$CSV" ]; then
        echo "[SKIP] $DNAME: $CSV not found"
        continue
    fi

    TOTAL=$((TOTAL + 1))
    DOUT="${OUTPUT_BASE}/${DNAME}"
    DREPORT="${DOUT}/onboarding_report.json"

    echo ""
    echo "============================================================"
    echo "[${TOTAL}] Dataset: ${DNAME}"
    echo "    CSV: ${CSV} ($(wc -l < "$CSV") lines)"
    echo "    Target: ${TARGET}, Split: ${SPLIT}"
    echo "    Started: $(date +%H:%M:%S)"
    echo "============================================================"

    # Resolve absolute paths
    ABS_CSV="${PROJ_ROOT}/${CSV}"
    ABS_DOUT="${PROJ_ROOT}/${DOUT}"
    ABS_DREPORT="${PROJ_ROOT}/${DREPORT}"

    # Build command
    CMD="python3 scripts/mlgg.py onboarding \
        --project-root ${ABS_DOUT} \
        --mode auto \
        --input-csv ${ABS_CSV} \
        --target-col ${TARGET} \
        --split-strategy ${SPLIT} \
        --no-stop-on-fail \
        --report ${ABS_DREPORT} \
        --seed 42 \
        --run-id ${DNAME}_${TIMESTAMP}"

    # Add optional columns
    if [ -n "$PID" ]; then
        CMD="$CMD --patient-id-col ${PID}"
    fi
    if [ -n "$TIME" ]; then
        CMD="$CMD --time-col ${TIME}"
    fi

    # Cross-sectional datasets: no temporal structure, skip temporal ordering checks
    # NHANES: stratified multistage survey, nhanes_cycle is cohort label not event time
    # Pima: single-timepoint screening dataset
    if [ "$DNAME" = "nhanes" ] || [ "$DNAME" = "pima" ]; then
        CMD="$CMD --cross-sectional"
    fi

    # Phenotype definition spec (enables definition_variable_guard post-prediction checks)
    if [ -n "$PHENO_SPEC" ] && [ -f "${PROJ_ROOT}/${PHENO_SPEC}" ]; then
        CMD="$CMD --phenotype-spec ${PROJ_ROOT}/${PHENO_SPEC}"
    fi

    # Run with timing
    START_SEC=$(date +%s)
    eval "$CMD" > "${DOUT}_stdout.log" 2>&1
    EXIT_CODE=$?
    END_SEC=$(date +%s)
    ELAPSED=$((END_SEC - START_SEC))
    ELAPSED_MIN=$(echo "scale=1; $ELAPSED / 60" | bc)

    # Parse result
    if [ $EXIT_CODE -eq 0 ]; then
        STATUS="PASS"
        PASSED=$((PASSED + 1))
        echo "  ✓ PASS (${ELAPSED_MIN} min)"
    elif [ $EXIT_CODE -eq 2 ]; then
        STATUS="FAIL_GATE"
        FAILED=$((FAILED + 1))
        echo "  ✗ GATE FAILURE (${ELAPSED_MIN} min)"
        # Extract which gates failed
        if [ -f "$DREPORT" ]; then
            python3 -c "
import json
with open('${DREPORT}') as f:
    r = json.load(f)
for step in r.get('steps', []):
    if step.get('exit_code', 0) != 0:
        print(f'    FAILED: {step.get(\"name\", \"?\")} (exit={step[\"exit_code\"]})')
" 2>/dev/null
        fi
    else
        STATUS="ERROR"
        ERRORS=$((ERRORS + 1))
        echo "  ✗ ERROR exit=$EXIT_CODE (${ELAPSED_MIN} min)"
        # Log error
        echo "{\"dataset\": \"${DNAME}\", \"exit_code\": ${EXIT_CODE}, \"elapsed_sec\": ${ELAPSED}, \"log\": \"${DOUT}_stdout.log\"}" >> "$ERROR_LOG"
    fi

    # Extract gate pass/fail counts from report
    GATES_PASSED=""
    GATES_FAILED=""
    TOTAL_SCORE=""
    if [ -f "$DREPORT" ]; then
        GATE_INFO=$(python3 -c "
import json
try:
    with open('${DREPORT}') as f:
        r = json.load(f)
    steps = r.get('steps', [])
    passed = sum(1 for s in steps if s.get('exit_code', -1) == 0)
    failed = sum(1 for s in steps if s.get('exit_code', -1) != 0)
    print(f'{passed},{failed}')
except:
    print('?,?')
" 2>/dev/null)
        GATES_PASSED=$(echo "$GATE_INFO" | cut -d, -f1)
        GATES_FAILED=$(echo "$GATE_INFO" | cut -d, -f2)
    fi

    # Append to summary JSON
    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$SUMMARY_FILE"
    fi
    cat >> "$SUMMARY_FILE" << JSONENTRY
    {
      "dataset": "${DNAME}",
      "csv": "${CSV}",
      "status": "${STATUS}",
      "exit_code": ${EXIT_CODE},
      "elapsed_sec": ${ELAPSED},
      "elapsed_min": ${ELAPSED_MIN},
      "gates_passed": "${GATES_PASSED}",
      "gates_failed": "${GATES_FAILED}",
      "report": "${DREPORT}",
      "log": "${DOUT}_stdout.log"
    }
JSONENTRY

done

# ---------------------------------------------------------------------------
# Finalize summary
# ---------------------------------------------------------------------------

echo "" >> "$SUMMARY_FILE"
cat >> "$SUMMARY_FILE" << EOF
],
  "finished": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "total_datasets": ${TOTAL},
  "passed": ${PASSED},
  "failed_gate": ${FAILED},
  "errors": ${ERRORS}
}
EOF

echo ""
echo "============================================================"
echo "OVERNIGHT RUN COMPLETE"
echo "============================================================"
echo "  Total:   ${TOTAL} datasets"
echo "  Passed:  ${PASSED}"
echo "  Failed:  ${FAILED} (gate failures)"
echo "  Errors:  ${ERRORS} (crashes)"
echo "  Summary: ${SUMMARY_FILE}"
echo "  Finished: $(date)"
echo "============================================================"

# ---------------------------------------------------------------------------
# Auto-commit results if any
# ---------------------------------------------------------------------------

if [ -d "$OUTPUT_BASE" ]; then
    cd "$PROJ_ROOT"

    # Stage scripts (not large CSV data files)
    git add experiments/overnight_pipeline_run.sh 2>/dev/null
    git add "${OUTPUT_BASE}/summary.json" 2>/dev/null
    git add "${OUTPUT_BASE}/errors.jsonl" 2>/dev/null

    # Don't add large log files or data directories
    # Stage onboarding reports (small JSON)
    for report in ${OUTPUT_BASE}/*/onboarding_report.json; do
        if [ -f "$report" ]; then
            git add "$report" 2>/dev/null
        fi
    done

    git commit -m "experiment: overnight 33-gate pipeline run on ${TOTAL} datasets (${PASSED} pass, ${FAILED} fail, ${ERRORS} error)

Datasets: ${DATASET_ORDER}
Run ID: ${TIMESTAMP}

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>/dev/null

    git push 2>/dev/null
    echo "Results committed and pushed."
fi
