#!/usr/bin/env bash
# Step 2: train baseline(r16) / armA(r8) / armB(r8) LoRA with LlamaFactory.
# Usage:  bash deploy/02_train_three_lora.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/_common.sh"

activate_env
setup_logging "02_train_three_lora"

[ -f "$DATASET_DIR/dataset_info.json" ] || die "missing $DATASET_DIR/dataset_info.json (run 01 first)"
[ -d "$STUDENT_MODEL" ] || die "student model not found: $STUDENT_MODEL"
mkdir -p "$LORA_ROOT" "$ARTIFACTS/configs"

train_one() {
  local arm="$1" rank="$2" dataset_key="$3"
  local out_dir="$LORA_ROOT/$arm"
  local cfg="$ARTIFACTS/configs/lf_${arm}.yaml"
  log "==== train $arm (rank=$rank, dataset=$dataset_key) ===="

  cat > "$cfg" <<YAML
model_name_or_path: $STUDENT_MODEL
stage: sft
do_train: true
finetuning_type: lora
lora_rank: $rank
lora_target: all
dataset: $dataset_key
dataset_dir: $DATASET_DIR
template: alpaca
cutoff_len: $CUTOFF_LEN
output_dir: $out_dir
overwrite_output_dir: true
per_device_train_batch_size: $BATCH_SIZE
gradient_accumulation_steps: $GRAD_ACCUM
lr_scheduler_type: cosine
learning_rate: $LR
num_train_epochs: $EPOCHS
warmup_ratio: 0.03
fp16: true
gradient_checkpointing: true
logging_steps: 5
save_steps: 100000
plot_loss: true
report_to: none
YAML

  local t0 t1
  t0=$(date +%s)
  llamafactory-cli train "$cfg"
  t1=$(date +%s)
  local wall=$((t1 - t0))

  # record metrics for this arm (loss/runtime parsed from all_results.json if present)
  python - "$MANIFEST" "$arm" "$rank" "$out_dir" "$wall" "$RUN_ID" <<'PYEOF'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from codeir.metrics import update_train_arm

manifest, arm, rank, out_dir, wall, run_id = sys.argv[1:7]
wall = int(wall)
loss = None
n_samples = None
ar = Path(out_dir) / "all_results.json"
if ar.exists():
    data = json.loads(ar.read_text(encoding="utf-8"))
    loss = data.get("train_loss")
    runtime = data.get("train_runtime")
    if runtime:
        wall = int(runtime)
update_train_arm(manifest, arm, {
    "rank": int(rank),
    "final_loss": loss,
    "wall_sec": wall,
    "gpu_hours": round(wall / 3600.0, 4),
    "adapter_dir": out_dir,
}, run_id=run_id)
print(f"recorded {arm}: wall={wall}s loss={loss}")
PYEOF
}

train_one baseline 16 baseline
train_one armA 8 armA
train_one armB 8 armB

log "DONE 02: 3 LoRA at $LORA_ROOT ; train metrics in $MANIFEST"
