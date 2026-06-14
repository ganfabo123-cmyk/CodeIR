#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv-linux}"
MODEL_ROOT="${MODEL_ROOT:-$ROOT_DIR/workdir/models}"
LOG_ROOT="${LOG_ROOT:-$ROOT_DIR/workdir/logs}"
STATE_ROOT="${STATE_ROOT:-$ROOT_DIR/workdir/deploy-state}"
HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
HF_TOKEN="${HF_TOKEN:-}"

TEACHER_MODEL_ID="${TEACHER_MODEL_ID:-Qwen/Qwen2.5-32B-Instruct}"
STUDENT_MODEL_ID="${STUDENT_MODEL_ID:-Qwen/Qwen2.5-7B}"
TEACHER_SIZE_GB="${TEACHER_SIZE_GB:-66}"
STUDENT_SIZE_GB="${STUDENT_SIZE_GB:-16}"
DISK_BUDGET_GB="${DISK_BUDGET_GB:-100}"

mkdir -p "$LOG_ROOT" "$STATE_ROOT" "$MODEL_ROOT"
LOG_FILE="$LOG_ROOT/linux_one_click_$(date '+%Y%m%d_%H%M%S').log"
LATEST_LOG="$LOG_ROOT/linux_one_click_latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"
exec > >(tee -a "$LOG_FILE") 2>&1

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

require_python() {
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

check_free_space() {
  local target_dir="$1"
  local need_gb="$2"
  local free_kb
  local free_gb

  free_kb="$(df -Pk "$target_dir" | awk 'NR==2 {print $4}')"
  free_gb=$((free_kb / 1024 / 1024))

  if (( free_gb < need_gb )); then
    die "Free space ${free_gb}G is below required ${need_gb}G for one-click deploy."
  fi
  log "Free space check passed: ${free_gb}G available at $target_dir"
}

check_budget() {
  local total_gb=$((TEACHER_SIZE_GB + STUDENT_SIZE_GB))
  if (( total_gb > DISK_BUDGET_GB )); then
    die "Declared model size ${total_gb}G exceeds DISK_BUDGET_GB=${DISK_BUDGET_GB}."
  fi
  log "Declared model size check passed: teacher=${TEACHER_SIZE_GB}G student=${STUDENT_SIZE_GB}G total=${total_gb}G budget=${DISK_BUDGET_GB}G"
}

step_marker() {
  local step_name="$1"
  echo "$STATE_ROOT/${step_name}.done"
}

is_step_done() {
  local step_name="$1"
  [[ -f "$(step_marker "$step_name")" ]]
}

mark_step_done() {
  local step_name="$1"
  date '+%F %T' > "$(step_marker "$step_name")"
}

env_is_ready() {
  [[ -x "$VENV_DIR/bin/python" ]] && "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1
}

student_is_ready() {
  local student_dir="$MODEL_ROOT/$(basename "$STUDENT_MODEL_ID")"
  [[ -f "$student_dir/config.json" ]]
}

teacher_is_ready() {
  local teacher_dir="$MODEL_ROOT/$(basename "$TEACHER_MODEL_ID")"
  [[ -f "$teacher_dir/config.json" ]] && [[ -f "$teacher_dir/model.safetensors.index.json" ]]
}

run_step() {
  local step_name="$1"
  local step_desc="$2"
  shift 2

  log "==== $step_desc ===="
  "$@"
  mark_step_done "$step_name"
  log "Completed: $step_desc"
}

create_env_and_install_deps() {
  local py
  py="$(require_python)"

  if env_is_ready && is_step_done "env"; then
    log "Skipping environment setup; marker and virtualenv already exist."
    return 0
  fi

  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtualenv: $VENV_DIR"
    "$py" -m venv "$VENV_DIR"
  else
    log "Reusing existing virtualenv: $VENV_DIR"
  fi

  export PATH="$VENV_DIR/bin:$PATH"
  log "Installing Python dependencies into $VENV_DIR"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -e ".[all]"
}

download_student_model() {
  export PATH="$VENV_DIR/bin:$PATH"
  export MODEL_ROOT HF_MIRROR HF_TOKEN STUDENT_MODEL_ID STUDENT_SIZE_GB

  if student_is_ready && is_step_done "student"; then
    log "Skipping student download; marker exists and model directory looks complete."
    return 0
  fi

  bash "$ROOT_DIR/deploy/linux_download_student.sh"
}

download_teacher_model() {
  export PATH="$VENV_DIR/bin:$PATH"
  export MODEL_ROOT HF_MIRROR HF_TOKEN TEACHER_MODEL_ID TEACHER_SIZE_GB

  if teacher_is_ready && is_step_done "teacher"; then
    log "Skipping teacher download; marker exists and model directory looks complete."
    return 0
  fi

  bash "$ROOT_DIR/deploy/linux_download_teacher.sh"
}

main() {
  ensure_cmd bash
  ensure_cmd df
  ensure_cmd tee
  check_budget
  check_free_space "$MODEL_ROOT" "$DISK_BUDGET_GB"

  log "Log file: $LOG_FILE"
  log "Model root: $MODEL_ROOT"
  log "Virtualenv: $VENV_DIR"
  log "Using Hugging Face mirror: $HF_MIRROR"

  run_step "env" "Step 1/3: create environment and install dependencies" create_env_and_install_deps
  run_step "student" "Step 2/3: download student model" download_student_model
  run_step "teacher" "Step 3/3: download teacher model" download_teacher_model

  log "One-click deploy completed successfully."
}

main "$@"
