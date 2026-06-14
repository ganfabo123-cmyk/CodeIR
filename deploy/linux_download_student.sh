#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR/workdir/models}"
RUNTIME_ROOT="${RUNTIME_ROOT:-$ROOT_DIR/workdir/runtime}"
HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-Qwen/Qwen2.5-7B}"
STUDENT_SIZE_GB="${STUDENT_SIZE_GB:-16}"

TMP_ROOT_DIR="$RUNTIME_ROOT/tmp-student"

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

check_free_space() {
  local target_dir="$1"
  local need_gb="$2"
  mkdir -p "$target_dir"

  local free_kb
  free_kb="$(df -Pk "$target_dir" | awk 'NR==2 {print $4}')"
  local free_gb=$((free_kb / 1024 / 1024))

  if (( free_gb < need_gb )); then
    die "Free space ${free_gb}G is below required ${need_gb}G for student model download."
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

download_student() {
  local cli
  local dest_dir="$MODEL_ROOT/$(basename "$STUDENT_MODEL_ID")"
  local repo_files
  local local_files

  cli="$(hf_download_cmd)"
  mkdir -p "$dest_dir"

  repo_files="$($cli repo-files "$STUDENT_MODEL_ID" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
  local_files="$(find "$dest_dir" -type f 2>/dev/null | wc -l | awk '{print $1}')"

  if (( repo_files > 0 )) && (( local_files >= repo_files )); then
    log "Student model already exists: $dest_dir"
    return 0
  fi

  log "Downloading $STUDENT_MODEL_ID -> $dest_dir"
  if [[ "$cli" == "hf" ]]; then
    hf download "$STUDENT_MODEL_ID" --local-dir "$dest_dir"
  else
    huggingface-cli download "$STUDENT_MODEL_ID" --local-dir "$dest_dir"
  fi
}

main() {
  ensure_cmd df
  hf_download_cmd >/dev/null
  trap cleanup_runtime_dirs EXIT

  if (( STUDENT_SIZE_GB <= 0 )); then
    die "STUDENT_SIZE_GB must be a positive integer."
  fi

  check_free_space "$MODEL_ROOT" "$STUDENT_SIZE_GB"
  prepare_runtime_dirs
  prepare_hf
  download_student

  log "Student model download completed."
  log "Student model: $STUDENT_MODEL_ID"
  log "Saved under: $MODEL_ROOT"
}

main "$@"
