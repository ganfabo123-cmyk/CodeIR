#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR/workdir/models}"
RUNTIME_ROOT="${RUNTIME_ROOT:-$ROOT_DIR/workdir/runtime}"
HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-Qwen/Qwen2.5-7B}"

DISK_BUDGET_GB="${DISK_BUDGET_GB:-50}"
STUDENT_SIZE_GB="${STUDENT_SIZE_GB:-16}"

HF_HOME_DIR="$RUNTIME_ROOT/hf-home"
HF_CACHE_DIR="$RUNTIME_ROOT/hf-cache"
HF_ASSETS_DIR="$RUNTIME_ROOT/hf-assets"
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
  local student_gb="$1"
  local budget_gb="$2"

  if (( student_gb > budget_gb )); then
    die "Declared student model size ${student_gb}G exceeds DISK_BUDGET_GB=${budget_gb}."
  fi
  log "Declared model size check passed: student=${student_gb}G budget=${budget_gb}G"
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
  mkdir -p "$MODEL_ROOT" "$HF_HOME_DIR" "$HF_CACHE_DIR" "$HF_ASSETS_DIR" "$TMP_ROOT_DIR"

  export HF_HOME="$HF_HOME_DIR"
  export HF_HUB_CACHE="$HF_CACHE_DIR"
  export HUGGINGFACE_HUB_CACHE="$HF_CACHE_DIR"
  export HF_ASSETS_CACHE="$HF_ASSETS_DIR"
  export XDG_CACHE_HOME="$RUNTIME_ROOT/xdg-cache"
  export TMPDIR="$TMP_ROOT_DIR"
  export TEMP="$TMP_ROOT_DIR"
  export TMP="$TMP_ROOT_DIR"

  log "Redirecting Hugging Face cache and temp files under $RUNTIME_ROOT"
}

cleanup_runtime_dirs() {
  rm -rf "$HF_HOME_DIR" "$HF_CACHE_DIR" "$HF_ASSETS_DIR" "$RUNTIME_ROOT/xdg-cache" "$TMP_ROOT_DIR"
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
  local dest_dir="$2"
  local dest_path="$dest_dir/$(basename "$model_id")"
  local cli
  local repo_files
  local local_files

  cli="$(hf_download_cmd)"

  mkdir -p "$dest_dir"
  repo_files="$($cli repo-files "$model_id" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
  local_files="$(find "$dest_path" -type f 2>/dev/null | wc -l | awk '{print $1}')"

  if (( repo_files > 0 )) && (( local_files >= repo_files )); then
    log "Model already exists: $dest_path"
    return 0
  fi

  log "Downloading $model_id -> $dest_path"
  if [[ "$cli" == "hf" ]]; then
    hf download "$model_id" --local-dir "$dest_path" --cache-dir "$HF_CACHE_DIR"
  else
    huggingface-cli download "$model_id" --local-dir "$dest_path" --cache-dir "$HF_CACHE_DIR"
  fi
}

main() {
  ensure_cmd df
  hf_download_cmd >/dev/null
  trap cleanup_runtime_dirs EXIT

  require_var "STUDENT_MODEL_ID" "$STUDENT_MODEL_ID"

  if (( STUDENT_SIZE_GB <= 0 )); then
    die "STUDENT_SIZE_GB must be a positive integer."
  fi

  check_budget "$STUDENT_SIZE_GB" "$DISK_BUDGET_GB"
  check_free_space "$MODEL_ROOT" "$DISK_BUDGET_GB"
  prepare_runtime_dirs
  prepare_hf

  download_model "$STUDENT_MODEL_ID" "$MODEL_ROOT"

  log "Student model download completed."
  log "Student model: $STUDENT_MODEL_ID"
  log "Saved under: $MODEL_ROOT"
}

main "$@"
