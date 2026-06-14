#!/usr/bin/env bash
# Step 1: install deps + download LeetCodeDataset + API-teacher data generation
#         + derive 3 SFT lines + export to LlamaFactory.
# Usage:  bash deploy/01_prepare_and_gen.sh [--smoke]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/_common.sh"

SMOKE=0
[ "${1:-}" = "--smoke" ] && SMOKE=1

activate_env
setup_logging "01_prepare_and_gen"

# ---- 1. dependencies ----
# Design: LLaMA-Factory owns the whole ML stack (torch/transformers/peft/
# accelerate/datasets/trl) as one self-consistent set. codeir installs with
# --no-deps so it never re-pins or fights that stack. Everything is install-once
# and skipped on re-runs (FORCE_INSTALL=1 to force a reinstall).
LF_HOME="${LF_HOME:-$PROJECT_DIR/third_party/LLaMA-Factory}"
# Official GitHub source. If the clone times out in CN, override LF_REPO with a
# GitHub proxy, e.g.:
#   LF_REPO=https://gh-proxy.com/https://github.com/hiyouga/LLaMA-Factory.git
LF_REPO="${LF_REPO:-https://github.com/hiyouga/LLaMA-Factory.git}"
LF_REF="${LF_REF:-v0.9.2}"

if [ "${FORCE_INSTALL:-0}" != "1" ] && \
   python -c "import codeir, llamafactory, torch, transformers, peft, datasets" 2>/dev/null; then
  log "==== deps already present; skip install (FORCE_INSTALL=1 to force) ===="
else
  python -m pip install --upgrade pip >/dev/null
  # 1a. LLaMA-Factory first: it brings the consistent ML stack.
  if ! python -c "import llamafactory" 2>/dev/null; then
    log "==== install LlamaFactory into $LF_HOME (from $LF_REPO @ $LF_REF) ===="
    if [ ! -d "$LF_HOME" ]; then
      git clone --depth 1 --branch "$LF_REF" "$LF_REPO" "$LF_HOME"
    fi
    python -m pip install -e "$LF_HOME"
  fi
  # 1b. codeir editable, no deps -> never disturbs the ML stack above.
  log "==== install codeir (--no-deps) ===="
  python -m pip install -e . --no-deps
fi

# ---- 2. validate api teacher env (.env) ----
[ -f "$PROJECT_DIR/.env" ] || die ".env not found at $PROJECT_DIR/.env (need LLM_API_KEY/LLM_API_BASE_URL/LLM_MODEL)"

# ---- 3. dump one raw dataset record for field/check inspection ([待确认]#1) ----
log "==== dump raw dataset sample ===="
python -m codeir.cli prepare-leetcode --dump-sample "$ARTIFACTS/raw_sample.json" || \
  die "dataset download failed (check HF_ENDPOINT=$HF_ENDPOINT)"

# ---- 4. prepare problems ----
if [ "$SMOKE" = "1" ]; then
  log "==== prepare-leetcode SMOKE (1 train / 1 test) ===="
  python -m codeir.cli prepare-leetcode --output-root "$DATA_ROOT" --smoke
else
  log "==== prepare-leetcode FULL ($N_TRAIN train / $N_TEST test) ===="
  python -m codeir.cli prepare-leetcode --output-root "$DATA_ROOT" \
    --n-train "$N_TRAIN" --n-test "$N_TEST"
fi

# ---- 5. API teacher generation over the TRAIN split ----
log "==== distill-batch (provider=api) ===="
python -m codeir.cli distill-batch \
  --problems-dir "$TRAIN_PROBLEMS" \
  --tests-dir "$TRAIN_TESTS" \
  --output-root "$DATA_ROOT" \
  --provider api \
  --max-resamples "$MAX_RESAMPLES" \
  --manifest "$MANIFEST" \
  --run-id "$RUN_ID"

# ---- 6. export 3 SFT lines to LlamaFactory ----
log "==== export-llamafactory ===="
python -m codeir.cli export-llamafactory \
  --output-root "$DATA_ROOT" \
  --export-root "$ARTIFACTS"

log "DONE 01: dataset+generation. SFT datasets at $DATASET_DIR ; metrics at $MANIFEST"
