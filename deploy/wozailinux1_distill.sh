#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONDA_ENV_NAME="${CONDA_ENV_NAME:-}"
CONDA_SH_PATH="${CONDA_SH_PATH:-}"
PYTHON_BIN=""

LOG_ROOT="${LOG_ROOT:-$ROOT_DIR/workdir/logs}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/data}"
PROBLEM_FILE="${PROBLEM_FILE:-$ROOT_DIR/examples/problem_lis.json}"
TESTS_FILE="${TESTS_FILE:-$ROOT_DIR/examples/testcases_lis.json}"
PROVIDER="${PROVIDER:-transformers}"
MAX_RESAMPLES="${MAX_RESAMPLES:-8}"
CODEIR_MODEL_PATH="${CODEIR_MODEL_PATH:-/backup01/ganfabo/models/Qwen2.5-32B-Instruct}"

TORCH_VERSION="${TORCH_VERSION:-2.5.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.20.1}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.5.1}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION:-4.46.3}"
ACCELERATE_VERSION="${ACCELERATE_VERSION:-1.1.1}"
PEFT_VERSION="${PEFT_VERSION:-0.13.2}"
BITSANDBYTES_VERSION="${BITSANDBYTES_VERSION:-0.43.3}"

mkdir -p "$LOG_ROOT" "$OUTPUT_ROOT"

LOG_FILE="$LOG_ROOT/wozailinux1_distill_$(date '+%Y%m%d_%H%M%S').log"
exec > >(tee -a "$LOG_FILE") 2>&1

die() {
  echo "ERROR: $*" >&2
  exit 1
}

find_conda_sh() {
  if [[ -n "$CONDA_SH_PATH" && -f "$CONDA_SH_PATH" ]]; then
    echo "$CONDA_SH_PATH"
    return 0
  fi
  if command -v conda >/dev/null 2>&1; then
    conda info --base 2>/dev/null | awk 'NF {print $0 "/etc/profile.d/conda.sh"; exit}'
    return 0
  fi
  for candidate in "$HOME/miniconda3/etc/profile.d/conda.sh" "$HOME/anaconda3/etc/profile.d/conda.sh"; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

activate_conda() {
  if [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" ]]; then
    PYTHON_BIN="${CONDA_PREFIX}/bin/python"
    return 0
  fi

  [[ -n "$CONDA_ENV_NAME" ]] || die "CONDA_ENV_NAME is required when no conda env is active."
  local conda_sh
  conda_sh="$(find_conda_sh)" || die "Unable to locate conda.sh"
  # shellcheck disable=SC1090
  source "$conda_sh"
  conda activate "$CONDA_ENV_NAME"
  PYTHON_BIN="$(command -v python)"
  [[ -n "$PYTHON_BIN" ]] || die "Failed to resolve python from conda environment."
}

ensure_repo_installed() {
  "$PYTHON_BIN" -m pip install -e . --no-deps --no-build-isolation
}

sync_runtime_deps() {
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
  "$PYTHON_BIN" -m pip install --upgrade --force-reinstall \
    --index-url "$TORCH_INDEX_URL" \
    "torch==${TORCH_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}"
  "$PYTHON_BIN" -m pip install --upgrade --force-reinstall \
    "transformers==${TRANSFORMERS_VERSION}" \
    "accelerate==${ACCELERATE_VERSION}" \
    "peft==${PEFT_VERSION}" \
    "bitsandbytes==${BITSANDBYTES_VERSION}"
}

ensure_runtime_versions() {
  if "$PYTHON_BIN" - <<PY
from importlib.metadata import version
expected = {
    "torch": "${TORCH_VERSION}",
    "torchvision": "${TORCHVISION_VERSION}",
    "torchaudio": "${TORCHAUDIO_VERSION}",
    "transformers": "${TRANSFORMERS_VERSION}",
    "accelerate": "${ACCELERATE_VERSION}",
    "peft": "${PEFT_VERSION}",
    "bitsandbytes": "${BITSANDBYTES_VERSION}",
}
for name, want in expected.items():
    if version(name) != want:
        raise SystemExit(1)
PY
  then
    return 0
  fi

  sync_runtime_deps
}

[[ -d "$CODEIR_MODEL_PATH" ]] || die "Model path does not exist: $CODEIR_MODEL_PATH"
[[ -f "$PROBLEM_FILE" ]] || die "Problem file does not exist: $PROBLEM_FILE"
[[ -f "$TESTS_FILE" ]] || die "Tests file does not exist: $TESTS_FILE"

activate_conda
ensure_runtime_versions
ensure_repo_installed

export CODEIR_MODEL_PATH
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

"$PYTHON_BIN" "$ROOT_DIR/run_codeir.py" distill \
  --problem "$PROBLEM_FILE" \
  --tests "$TESTS_FILE" \
  --provider "$PROVIDER" \
  --output-root "$OUTPUT_ROOT" \
  --max-resamples "$MAX_RESAMPLES"
