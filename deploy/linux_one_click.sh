#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR/workdir/models}"
HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

TEACHER_MODEL_ID="${TEACHER_MODEL_ID:-}"
STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-}"

DISK_BUDGET_GB="${DISK_BUDGET_GB:-50}"
TEACHER_SIZE_GB="${TEACHER_SIZE_GB:-0}"
STUDENT_SIZE_GB="${STUDENT_SIZE_GB:-0}"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_var() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "Missing required environment variable: $name"
}

check_budget() {
  local teacher_gb="$1"
  local student_gb="$2"
  local budget_gb="$3"
  local total_gb=$((teacher_gb + student_gb))

  if (( total_gb > budget_gb )); then
    die "Declared model size ${total_gb}G exceeds DISK_BUDGET_GB=${budget_gb}. Choose smaller/quantized repos."
  fi
  log "Declared model size check passed: teacher=${teacher_gb}G student=${student_gb}G total=${total_gb}G budget=${budget_gb}G"
}

check_free_space() {
  local target_dir="$1"
  local need_gb="$2"
  mkdir -p "$target_dir"

  local free_kb
  free_kb="$(df -Pk "$target_dir" | awk 'NR==2 {print $4}')"
  local free_gb=$((free_kb / 1024 / 1024))

  if (( free_gb < need_gb )); then
    die "Free space ${free_gb}G is below required ${need_gb}G for model download."
  fi
  log "Free space check passed: ${free_gb}G available at $target_dir"
}

prepare_hf() {
  if [[ -n "$HF_TOKEN" ]]; then
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential
  fi
  if [[ -n "$HF_MIRROR" ]]; then
    export HF_ENDPOINT="$HF_MIRROR"
    log "Using Hugging Face mirror: $HF_ENDPOINT"
  fi
}

download_model() {
  local model_id="$1"
  local dest_dir="$2"
  local dest_path="$dest_dir/$(basename "$model_id")"

  mkdir -p "$dest_dir"
  if [[ -f "$dest_path/config.json" ]]; then
    log "Model already exists: $dest_path"
    return 0
  fi

  log "Downloading $model_id -> $dest_path"
  huggingface-cli download "$model_id" --local-dir "$dest_path"
}

main() {
  ensure_cmd huggingface-cli
  ensure_cmd df

  require_var "TEACHER_MODEL_ID" "$TEACHER_MODEL_ID"
  require_var "STUDENT_MODEL_ID" "$STUDENT_MODEL_ID"

  if (( TEACHER_SIZE_GB <= 0 || STUDENT_SIZE_GB <= 0 )); then
    die "Set TEACHER_SIZE_GB and STUDENT_SIZE_GB explicitly so the 50G budget check is meaningful."
  fi

  check_budget "$TEACHER_SIZE_GB" "$STUDENT_SIZE_GB" "$DISK_BUDGET_GB"
  check_free_space "$MODEL_ROOT" "$DISK_BUDGET_GB"
  prepare_hf

  download_model "$TEACHER_MODEL_ID" "$MODEL_ROOT"
  download_model "$STUDENT_MODEL_ID" "$MODEL_ROOT"

  log "Model download completed."
  log "Teacher model: $TEACHER_MODEL_ID"
  log "Student model: $STUDENT_MODEL_ID"
  log "Saved under: $MODEL_ROOT"
}

main "$@"
