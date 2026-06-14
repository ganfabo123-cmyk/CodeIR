#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv-linux}"
LOG_ROOT="${LOG_ROOT:-$ROOT_DIR/workdir/logs}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/data}"
PROBLEM_FILE="${PROBLEM_FILE:-$ROOT_DIR/examples/problem_lis.json}"
TESTS_FILE="${TESTS_FILE:-$ROOT_DIR/examples/testcases_lis.json}"
PROVIDER="${PROVIDER:-transformers}"
MAX_RESAMPLES="${MAX_RESAMPLES:-8}"
CODEIR_MODEL_PATH="${CODEIR_MODEL_PATH:-/backup01/ganfabo/models/Qwen2.5-32B-Instruct}"
PYTHON_BIN="${PYTHON_BIN:-}"

mkdir -p "$LOG_ROOT" "$OUTPUT_ROOT"

LOG_FILE="$LOG_ROOT/wozailinux1_distill_$(date '+%Y%m%d_%H%M%S').log"
LATEST_LOG="$LOG_ROOT/wozailinux1_distill_latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

resolve_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    echo "$PYTHON_BIN"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  die "Missing required command: python3"
}

venv_is_ready() {
  [[ -x "$VENV_DIR/bin/python" ]] && "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1
}

deps_are_ready() {
  if ! venv_is_ready; then
    return 1
  fi
  "$VENV_DIR/bin/python" -c "import torch, transformers" >/dev/null 2>&1
}

ensure_env() {
  local py
  py="$(resolve_python)"

  if ! venv_is_ready; then
    log "Creating virtualenv at $VENV_DIR"
    "$py" -m venv "$VENV_DIR"
  else
    log "Reusing virtualenv at $VENV_DIR"
  fi

  if deps_are_ready; then
    log "Python inference dependencies already available."
    return 0
  fi

  log "Installing inference dependencies into $VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install -e ".[inference]" --no-build-isolation
}

check_inputs() {
  [[ -d "$CODEIR_MODEL_PATH" ]] || die "Model path does not exist: $CODEIR_MODEL_PATH"
  [[ -f "$PROBLEM_FILE" ]] || die "Problem file does not exist: $PROBLEM_FILE"
  [[ -f "$TESTS_FILE" ]] || die "Tests file does not exist: $TESTS_FILE"
}

run_distill() {
  export CODEIR_MODEL_PATH
  export PYTHONUTF8=1
  export PYTHONIOENCODING=utf-8

  log "Running distill with provider=$PROVIDER"
  log "Model path: $CODEIR_MODEL_PATH"
  log "Problem file: $PROBLEM_FILE"
  log "Tests file: $TESTS_FILE"
  log "Output root: $OUTPUT_ROOT"

  "$VENV_DIR/bin/python" "$ROOT_DIR/run_codeir.py" distill \
    --problem "$PROBLEM_FILE" \
    --tests "$TESTS_FILE" \
    --provider "$PROVIDER" \
    --output-root "$OUTPUT_ROOT" \
    --max-resamples "$MAX_RESAMPLES"
}

show_success_hint() {
  local triple_path="$OUTPUT_ROOT/verified_triples/lc-300-demo.json"
  if [[ -f "$triple_path" ]]; then
    log "Verified triple written to $triple_path"
  else
    log "No verified triple found yet under $OUTPUT_ROOT/verified_triples"
  fi
  log "Latest log symlink: $LATEST_LOG"
}

main() {
  require_cmd bash
  require_cmd tee
  ensure_env
  check_inputs
  run_distill
  show_success_hint
}

main "$@"
