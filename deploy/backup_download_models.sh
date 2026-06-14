#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(pwd)"
MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
STATE_DIR="${STATE_DIR:-$ROOT_DIR/.download-state}"

HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

TEACHER_MODEL_ID="${TEACHER_MODEL_ID:-Qwen/Qwen2.5-32B-Instruct}"
STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-Qwen/Qwen2.5-7B}"

mkdir -p "$MODEL_ROOT" "$LOG_DIR" "$STATE_DIR"

LOG_FILE="$LOG_DIR/download_models_$(date '+%Y%m%d_%H%M%S').log"
LATEST_LOG="$LOG_DIR/latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  die "Missing required command: python3 or python"
}

refresh_shell_hash() {
  hash -r 2>/dev/null || true
}

dir_bytes() {
  local target_dir="$1"
  if [[ ! -d "$target_dir" ]]; then
    echo 0
    return 0
  fi
  du -sb "$target_dir" 2>/dev/null | awk '{print $1}'
}

bytes_to_mb() {
  local bytes="$1"
  awk -v bytes="$bytes" 'BEGIN { printf "%.2f", bytes / 1024 / 1024 }'
}

bytes_to_gb() {
  local bytes="$1"
  awk -v bytes="$bytes" 'BEGIN { printf "%.2f", bytes / 1024 / 1024 / 1024 }'
}

seconds_to_hms() {
  local total_seconds="$1"
  if (( total_seconds < 0 )); then
    total_seconds=0
  fi
  awk -v s="$total_seconds" 'BEGIN {
    h = int(s / 3600);
    m = int((s % 3600) / 60);
    sec = int(s % 60);
    printf "%02dh:%02dm:%02ds", h, m, sec;
  }'
}

expected_repo_bytes() {
  local model_id="$1"
  case "$model_id" in
    "Qwen/Qwen2.5-7B")
      echo 16320875725
      ;;
    "Qwen/Qwen2.5-32B-Instruct")
      echo 70330046874
      ;;
    *)
      echo 0
      ;;
  esac
}

start_progress_monitor() {
  local model_id="$1"
  local dest_dir="$2"
  local expected_bytes="$3"
  local label="$4"

  (
    local prev_bytes
    local prev_ts
    prev_bytes="$(dir_bytes "$dest_dir")"
    prev_ts="$(date +%s)"

    while true; do
      sleep 10
      local now_ts
      local now_bytes
      local delta_bytes
      local delta_ts
      local speed_mbs
      local size_gb

      now_ts="$(date +%s)"
      now_bytes="$(dir_bytes "$dest_dir")"
      delta_bytes=$((now_bytes - prev_bytes))
      delta_ts=$((now_ts - prev_ts))
      if (( delta_ts <= 0 )); then
        delta_ts=1
      fi

      speed_mbs="$(awk -v bytes="$delta_bytes" -v secs="$delta_ts" 'BEGIN {
        if (secs <= 0) secs = 1;
        printf "%.2f", bytes / 1024 / 1024 / secs;
      }')"
      size_gb="$(bytes_to_gb "$now_bytes")"

      if (( expected_bytes > 0 )); then
        local remaining_bytes
        local eta_seconds
        local progress_pct

        remaining_bytes=$((expected_bytes - now_bytes))
        if (( remaining_bytes < 0 )); then
          remaining_bytes=0
        fi
        progress_pct="$(awk -v cur="$now_bytes" -v total="$expected_bytes" 'BEGIN {
          if (total <= 0) { printf "0.0"; }
          else { printf "%.1f", (cur / total) * 100; }
        }')"
        eta_seconds="$(awk -v remain="$remaining_bytes" -v bytes="$delta_bytes" -v secs="$delta_ts" 'BEGIN {
          if (bytes <= 0) { print -1; }
          else { printf "%.0f", remain / (bytes / secs); }
        }')"
        if [[ "$eta_seconds" == "-1" ]]; then
          log "$label progress: ${size_gb}G downloaded, ${speed_mbs} MB/s, ${progress_pct}% complete, ETA unknown"
        else
          log "$label progress: ${size_gb}G downloaded, ${speed_mbs} MB/s, ${progress_pct}% complete, ETA $(seconds_to_hms "$eta_seconds")"
        fi
      else
        log "$label progress: ${size_gb}G downloaded, ${speed_mbs} MB/s"
      fi

      prev_bytes="$now_bytes"
      prev_ts="$now_ts"
    done
  ) &

  MONITOR_PID=$!
}

stop_progress_monitor() {
  if [[ -n "${MONITOR_PID:-}" ]]; then
    kill "$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
    MONITOR_PID=""
  fi
}

ensure_hf_cli() {
  local py
  py="$(python_cmd)"

  if command -v hf >/dev/null 2>&1; then
    return 0
  fi

  if command -v huggingface-cli >/dev/null 2>&1; then
    if huggingface-cli repo-files Qwen/Qwen2.5-7B >/dev/null 2>&1; then
      return 0
    fi
    log "Detected old huggingface-cli; upgrading huggingface_hub[cli]"
  else
    log "hf / huggingface-cli not found; installing huggingface_hub[cli]"
  fi

  "$py" -m pip install -U "huggingface_hub[cli]"
  refresh_shell_hash

  command -v hf >/dev/null 2>&1 && return 0
  command -v huggingface-cli >/dev/null 2>&1 && return 0

  local user_base
  user_base="$("$py" -m site --user-base 2>/dev/null || true)"
  if [[ -n "$user_base" ]] && [[ -d "$user_base/bin" ]]; then
    export PATH="$user_base/bin:$PATH"
    refresh_shell_hash
  fi

  command -v hf >/dev/null 2>&1 && return 0
  command -v huggingface-cli >/dev/null 2>&1 && return 0
  die "Failed to install hf / huggingface-cli"
}

hf_cmd() {
  ensure_hf_cli
  if command -v hf >/dev/null 2>&1; then
    echo "hf"
    return 0
  fi
  if command -v huggingface-cli >/dev/null 2>&1; then
    echo "huggingface-cli"
    return 0
  fi
  die "Missing required command: hf or huggingface-cli"
}

prepare_hf() {
  if [[ -n "$HF_TOKEN" ]]; then
    if [[ "$(hf_cmd)" == "hf" ]]; then
      hf auth login --token "$HF_TOKEN" --add-to-git-credential
    else
      huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential
    fi
  fi

  export HF_ENDPOINT="$HF_MIRROR"
  log "Using Hugging Face mirror: $HF_ENDPOINT"
}

download_repo() {
  local model_id="$1"
  local step_name="$2"
  local dest_dir="$MODEL_ROOT/$(basename "$model_id")"
  local marker="$STATE_DIR/${step_name}.done"
  local cli
  local expected_bytes

  cli="$(hf_cmd)"
  mkdir -p "$dest_dir"
  expected_bytes="$(expected_repo_bytes "$model_id")"

  if [[ -f "$marker" ]] && find "$dest_dir" -type f 2>/dev/null | grep -q .; then
    log "Skipping $model_id; already complete."
    return 0
  fi

  log "Downloading $model_id -> $dest_dir"
  start_progress_monitor "$model_id" "$dest_dir" "$expected_bytes" "$step_name"
  if [[ "$cli" == "hf" ]]; then
    if ! hf download "$model_id" --local-dir "$dest_dir"; then
      log "hf download failed once; refreshing CLI and retrying $model_id"
      ensure_hf_cli
      hf download "$model_id" --local-dir "$dest_dir"
    fi
  else
    if ! huggingface-cli download "$model_id" --local-dir "$dest_dir"; then
      log "huggingface-cli download failed once; upgrading CLI and retrying $model_id"
      ensure_hf_cli
      cli="$(hf_cmd)"
      if [[ "$cli" == "hf" ]]; then
        hf download "$model_id" --local-dir "$dest_dir"
      else
        huggingface-cli download "$model_id" --local-dir "$dest_dir"
      fi
    fi
  fi
  stop_progress_monitor

  date '+%F %T' > "$marker"
  log "Completed $model_id"
}

main() {
  command -v df >/dev/null 2>&1 || die "Missing required command: df"
  prepare_hf

  log "MODEL_ROOT=$MODEL_ROOT"
  log "LOG_FILE=$LOG_FILE"

  download_repo "$STUDENT_MODEL_ID" "student"
  download_repo "$TEACHER_MODEL_ID" "teacher"

  log "All downloads completed."
}

main "$@"
