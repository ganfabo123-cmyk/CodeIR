#!/usr/bin/env bash
# Shared config + helpers for the A-experiment deploy scripts.
# Override any variable by exporting it before calling the scripts.
set -euo pipefail

# ---- paths / env (defaults match the target server) ----
PROJECT_DIR="${PROJECT_DIR:-/home/ganfabo/Projects/CodeIR}"
CONDA_ENV="${CONDA_ENV:-CodeIR}"
STUDENT_MODEL="${STUDENT_MODEL:-/backup01/ganfabo/models/Qwen2.5-7B}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2}"
export CUDA_VISIBLE_DEVICES
# HuggingFace mirror for dataset download
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

# ---- run layout ----
RUN_ID="${RUN_ID:-A-exp}"
DATA_ROOT="${DATA_ROOT:-$PROJECT_DIR/data/$RUN_ID}"
ARTIFACTS="${ARTIFACTS:-$PROJECT_DIR/artifacts/$RUN_ID}"
DATASET_DIR="$ARTIFACTS/codeir_llamafactory"
LORA_ROOT="$ARTIFACTS/lora"
MANIFEST="$ARTIFACTS/metrics_manifest.json"
REPORT="$ARTIFACTS/compare_report.md"

TRAIN_PROBLEMS="$DATA_ROOT/raw_problems/train/problem"
TRAIN_TESTS="$DATA_ROOT/raw_problems/train/tests"
TEST_PROBLEMS="$DATA_ROOT/raw_problems/test/problem"
TEST_TESTS="$DATA_ROOT/raw_problems/test/tests"

# ---- training hyperparams (sized for ~37G free on a shared A6000) ----
N_TRAIN="${N_TRAIN:-300}"
N_TEST="${N_TEST:-100}"
EPOCHS="${EPOCHS:-3}"
LR="${LR:-1.0e-4}"
CUTOFF_LEN="${CUTOFF_LEN:-2048}"
BATCH_SIZE="${BATCH_SIZE:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
MAX_RESAMPLES="${MAX_RESAMPLES:-8}"

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

activate_env() {
  # If the target env is already active, don't touch conda at all
  # (avoids conda plugin errors such as anaconda-anon-usage).
  if [ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ]; then
    local conda_sh=""
    if [ -n "${CONDA_EXE:-}" ]; then
      conda_sh="$(dirname "$(dirname "$CONDA_EXE")")/etc/profile.d/conda.sh"
    fi
    local sourced=0
    for cand in "${CONDA_SH:-}" "$conda_sh" \
                "$HOME/miniconda3/etc/profile.d/conda.sh" \
                "$HOME/anaconda3/etc/profile.d/conda.sh" \
                "/opt/conda/etc/profile.d/conda.sh"; do
      if [ -n "$cand" ] && [ -f "$cand" ]; then
        # shellcheck disable=SC1090
        source "$cand"
        sourced=1
        break
      fi
    done
    [ "$sourced" = "1" ] || die "conda.sh not found; activate '$CONDA_ENV' manually then rerun, or set CONDA_SH"
    conda activate "$CONDA_ENV" || die "cannot activate conda env: $CONDA_ENV"
  fi
  cd "$PROJECT_DIR" || die "PROJECT_DIR not found: $PROJECT_DIR"
  export PYTHONPATH="$PROJECT_DIR/src:${PYTHONPATH:-}"
  log "env ready: conda=${CONDA_DEFAULT_ENV:-?} cuda=$CUDA_VISIBLE_DEVICES project=$PROJECT_DIR"
}

setup_logging() {
  local name="$1"
  mkdir -p "$ARTIFACTS/logs"
  local log_file="$ARTIFACTS/logs/${name}_$(date '+%Y%m%d_%H%M%S').log"
  exec > >(tee -a "$log_file") 2>&1
  log "log file: $log_file"
}
