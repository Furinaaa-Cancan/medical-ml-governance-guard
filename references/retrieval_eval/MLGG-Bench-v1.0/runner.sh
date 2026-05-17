#!/usr/bin/env bash
# bench_10: reproducibility runner.
# Reproduces every MLGG retrieval-eval number from the train/dev/test split
# files end-to-end, against the current RAG. Designed to be run from any cwd;
# all paths are resolved against $REPO.
#
# Usage:
#   ./run_benchmark.sh               # uses defaults (REPO=ml-leakage-guard, all splits, both modes)
#   REPO=/path/to/repo ./run_benchmark.sh
#   SPLITS="dev test" MODES="hybrid" ./run_benchmark.sh
#
# Outputs:
#   /tmp/mlgg_benchmark/run_results_<timestamp>.json   (aggregate)
#   /tmp/mlgg_benchmark/run_<timestamp>/<split>_<mode>.json{,.md}  (per-run sidecars)

set -euo pipefail

REPO="${REPO:-/Volumes/Seagate/Skill/ml-leakage-guard}"
SPLIT_DIR="${SPLIT_DIR:-/tmp/mlgg_benchmark}"
OUT_DIR="${OUT_DIR:-/tmp/mlgg_benchmark}"
SPLITS="${SPLITS:-dev}"  # default dev only; export SPLITS="dev test" to touch held-out
MODES="${MODES:-bm25_only hybrid}"
TOP_K="${TOP_K:-5}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${OUT_DIR}/run_${TS}"
AGG="${OUT_DIR}/run_results_${TS}.json"
mkdir -p "${RUN_DIR}"

KB_PATH="${REPO}/references/case-studies/peer-review-kb.json"

# --- 1. Provenance header (these affect reproducibility; print BEFORE any work) ---
PY_VER="$(python3 --version 2>&1)"
PY_EXE="$(command -v python3)"

GIT_SHA="unknown"
GIT_DIRTY="unknown"
if command -v git >/dev/null 2>&1 && git -C "${REPO}" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_SHA="$(git -C "${REPO}" rev-parse HEAD)"
  if [ -z "$(git -C "${REPO}" status --porcelain)" ]; then
    GIT_DIRTY="clean"
  else
    GIT_DIRTY="dirty"
  fi
fi

KB_SHA="missing"
if [ -f "${KB_PATH}" ]; then
  KB_SHA="$(shasum -a 256 "${KB_PATH}" | awk '{print $1}')"
fi

EMBED_MODEL="$(
  cd "${REPO}" && python3 - <<'PY' 2>/dev/null || echo unknown
try:
    from scripts.rag import config
    print(getattr(config, "EMBEDDING_MODEL", "unknown"))
except Exception:
    print("unknown")
PY
)"

cat <<EOF | tee "${RUN_DIR}/_provenance.txt"
================================================================
MLGG bench_10 reproducibility run -- ${TS}
================================================================
repo            : ${REPO}
python          : ${PY_VER}  (${PY_EXE})
git sha         : ${GIT_SHA}  (${GIT_DIRTY})
KB path         : ${KB_PATH}
KB SHA256       : ${KB_SHA}
embedding model : ${EMBED_MODEL}
split dir       : ${SPLIT_DIR}
splits          : ${SPLITS}
modes           : ${MODES}
top_k           : ${TOP_K}
output dir      : ${RUN_DIR}
aggregate JSON  : ${AGG}
================================================================
EOF

# --- 2. Run eval per (split, mode) ---
cd "${REPO}"

# Build aggregate JSON header.
python3 - <<PY > "${AGG}"
import json
print(json.dumps({
    "timestamp_utc":  "${TS}",
    "repo":           "${REPO}",
    "python":         "${PY_VER}",
    "git_sha":        "${GIT_SHA}",
    "git_state":      "${GIT_DIRTY}",
    "kb_path":        "${KB_PATH}",
    "kb_sha256":      "${KB_SHA}",
    "embedding_model":"${EMBED_MODEL}",
    "top_k":          ${TOP_K},
    "runs":           [],
}, indent=2))
PY

for split in ${SPLITS}; do
  scen_path="${SPLIT_DIR}/split_${split}.json"
  if [ ! -f "${scen_path}" ]; then
    echo "WARN: split file not found, skipping: ${scen_path}" >&2
    continue
  fi
  for mode in ${MODES}; do
    md_out="${RUN_DIR}/${split}_${mode}.md"
    json_out="${RUN_DIR}/${split}_${mode}.json"
    echo "----- running split=${split} mode=${mode} -----"
    python3 scripts/rag/evals/run_eval.py \
      --mode "${mode}" \
      --scenarios "${scen_path}" \
      --top-k "${TOP_K}" \
      --output "${md_out}"
    # run_eval.py writes <output>.json sidecar; some versions write same name.
    if [ ! -f "${json_out}" ] && [ -f "${md_out%.md}.json" ]; then
      cp "${md_out%.md}.json" "${json_out}"
    fi

    # Append a run entry to aggregate.
    python3 - <<PY
import json, pathlib
agg_path = pathlib.Path("${AGG}")
agg = json.loads(agg_path.read_text())
entry = {
    "split":    "${split}",
    "mode":     "${mode}",
    "scenarios":"${scen_path}",
    "md":       "${md_out}",
    "json":     "${json_out}",
}
sidecar = pathlib.Path("${json_out}")
if sidecar.exists():
    try:
        data = json.loads(sidecar.read_text())
        # Lift top-level aggregate metrics if present.
        for k in ("recall_at_5", "precision_at_5", "mrr", "ndcg_at_5",
                  "summary", "aggregate", "overall"):
            if isinstance(data, dict) and k in data:
                entry[k] = data[k]
        if isinstance(data, dict) and "scenarios" in data:
            entry["n_scenarios"] = len(data["scenarios"])
    except Exception as e:
        entry["sidecar_parse_error"] = str(e)
agg["runs"].append(entry)
agg_path.write_text(json.dumps(agg, indent=2))
PY
  done
done

echo ""
echo "DONE. Aggregate -> ${AGG}"
echo "Per-run artefacts -> ${RUN_DIR}/"
