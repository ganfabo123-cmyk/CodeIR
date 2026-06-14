#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR/workdir/models}"
RUNTIME_ROOT="${RUNTIME_ROOT:-$ROOT_DIR/workdir/runtime}"
HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

TEACHER_MODEL_ID="${TEACHER_MODEL_ID:-bartowski/Qwen2.5-32B-Instruct-GGUF}"
TEACHER_MODEL_FILE="${TEACHER_MODEL_FILE:-Qwen2.5-32B-Instruct-Q8_0.gguf}"
STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-Qwen/Qwen2.5-7B}"

DISK_BUDGET_GB="${DISK_BUDGET_GB:-55}"
TEACHER_SIZE_GB="${TEACHER_SIZE_GB:-35}"
STUDENT_SIZE_GB="${STUDENT_SIZE_GB:-16}"

TMP_ROOT_DIR="$RUNTIME_ROOT/tmp"

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

hf_download_cmd() {
  if command -v hf >/dev/null 2>&1; then
    echo "hf"
    return 0
  fi
  if command -v huggingface-cli >/dev/null 2>&1; then
    echo "huggingface-cli"
    return 0
  fi
  die "Missing required command: hf"
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
    die "Declared model size ${total_gb}G exceeds DISK_BUDGET_GB=${budget_gb}."
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

prepare_runtime_dirs() {
  mkdir -p "$MODEL_ROOT" "$TMP_ROOT_DIR"

  export TMPDIR="$TMP_ROOT_DIR"
  export TEMP="$TMP_ROOT_DIR"
  export TMP="$TMP_ROOT_DIR"

  log "Using minimal temporary files under $RUNTIME_ROOT"
}

cleanup_runtime_dirs() {
  rm -rf "$TMP_ROOT_DIR"
}

prepare_hf() {
  if [[ -n "$HF_TOKEN" ]]; then
    if [[ "$(hf_download_cmd)" == "hf" ]]; then
      hf auth login --token "$HF_TOKEN" --add-to-git-credential
    else
      huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential
    fi
  fi
  if [[ -n "$HF_MIRROR" ]]; then
    export HF_ENDPOINT="$HF_MIRROR"
    log "Using Hugging Face mirror: $HF_ENDPOINT"
  fi
}

download_model() {
  local model_id="$1"
  local include_pattern="$2"
  local dest_dir="$3"
  local dest_path="$dest_dir/$(basename "$model_id")"
  local cli
  local repo_files
  local local_files

  cli="$(hf_download_cmd)"

  mkdir -p "$dest_dir"
  if [[ -n "$include_pattern" ]]; then
    repo_files="1"
  else
    repo_files="$($cli repo-files "$model_id" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
  fi
  local_files="$(find "$dest_path" -type f 2>/dev/null | wc -l | awk '{print $1}')"

  if (( repo_files > 0 )) && (( local_files >= repo_files )); then
    log "Model already exists: $dest_path"
    return 0
  fi

  log "Downloading $model_id -> $dest_path"
  if [[ "$cli" == "hf" ]]; then
    if [[ -n "$include_pattern" ]]; then
      hf download "$model_id" --include "$include_pattern" --local-dir "$dest_path"
    else
      hf download "$model_id" --local-dir "$dest_path"
    fi
  else
    if [[ -n "$include_pattern" ]]; then
      huggingface-cli download "$model_id" --include "$include_pattern" --local-dir "$dest_path"
    else
      huggingface-cli download "$model_id" --local-dir "$dest_path"
    fi
  fi
}

main() {
  ensure_cmd df
  hf_download_cmd >/dev/null
  trap cleanup_runtime_dirs EXIT

  require_var "TEACHER_MODEL_ID" "$TEACHER_MODEL_ID"
  require_var "STUDENT_MODEL_ID" "$STUDENT_MODEL_ID"

  if (( TEACHER_SIZE_GB <= 0 || STUDENT_SIZE_GB <= 0 )); then
    die "TEACHER_SIZE_GB and STUDENT_SIZE_GB must be positive integers."
  fi

  check_budget "$TEACHER_SIZE_GB" "$STUDENT_SIZE_GB" "$DISK_BUDGET_GB"
  check_free_space "$MODEL_ROOT" "$DISK_BUDGET_GB"
  prepare_runtime_dirs
  prepare_hf

  download_model "$TEACHER_MODEL_ID" "$TEACHER_MODEL_FILE" "$MODEL_ROOT"
  download_model "$STUDENT_MODEL_ID" "" "$MODEL_ROOT"

  log "Model download completed."
  log "Teacher model: $TEACHER_MODEL_ID"
  log "Teacher file: $TEACHER_MODEL_FILE"
  log "Student model: $STUDENT_MODEL_ID"
  log "Saved under: $MODEL_ROOT"
}

main "$@"
