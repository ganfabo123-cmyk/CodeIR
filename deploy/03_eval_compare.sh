#!/usr/bin/env bash
# Step 3: pass@1 evaluation on the TEST split, baseline vs IR cascade, + report.
# Usage:  bash deploy/03_eval_compare.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/_common.sh"

activate_env
setup_logging "03_eval_compare"

for arm in baseline armA armB; do
  [ -d "$LORA_ROOT/$arm" ] || die "missing LoRA: $LORA_ROOT/$arm (run 02 first)"
done
[ -d "$TEST_PROBLEMS" ] || die "missing test problems: $TEST_PROBLEMS (run 01 first)"

log "==== eval-compare (baseline single vs experiment A->B) ===="
python -m codeir.cli eval-compare \
  --base-model "$STUDENT_MODEL" \
  --adapter-baseline "$LORA_ROOT/baseline" \
  --adapter-armA "$LORA_ROOT/armA" \
  --adapter-armB "$LORA_ROOT/armB" \
  --test-problem-dir "$TEST_PROBLEMS" \
  --test-tests-dir "$TEST_TESTS" \
  --manifest "$MANIFEST" \
  --report "$REPORT" \
  --run-id "$RUN_ID"

log "DONE 03: report at $REPORT ; full metrics at $MANIFEST"
echo "----- VERDICT -----"
python - "$MANIFEST" <<'PYEOF'
import json, sys
m = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(json.dumps(m.get("verdict", {}), ensure_ascii=False, indent=2))
PYEOF
