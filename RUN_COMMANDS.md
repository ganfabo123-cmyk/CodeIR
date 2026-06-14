# Real Teacher Run

## PowerShell

```powershell
$env:CODEIR_MODEL_PATH="/backup01/ganfabo/models/Qwen2.5-32B-Instruct"
python .\run_codeir.py distill `
  --problem examples\problem_lis.json `
  --tests examples\testcases_lis.json `
  --provider transformers `
  --output-root data
```

## Bash

```bash
export CODEIR_MODEL_PATH="/backup01/ganfabo/models/Qwen2.5-32B-Instruct"
python ./run_codeir.py distill \
  --problem examples/problem_lis.json \
  --tests examples/testcases_lis.json \
  --provider transformers \
  --output-root data
```

## Expected Success Signal

The command should finish with JSON like:

```json
{"accepted": true, "attempts": 1, "problem_id": "lc-300-demo", "verified": true, "error": ""}
```

If the first sample fails verification, `attempts` may be greater than `1`, but success still requires both `accepted` and `verified` to be `true`.
