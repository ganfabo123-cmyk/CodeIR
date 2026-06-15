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

---

# A 实验：API 老师 → 普通微调 vs IR微调（三脚本一键链路）

> 服务器：Linux 单卡 A6000（默认用 2 号卡）。所有路径默认值写在 `deploy/_common.sh`，
> 需覆盖时在命令前 `export`。API 凭证读项目根目录 `.env`（`LLM_API_KEY/LLM_API_BASE_URL/LLM_MODEL`）。
> 默认布局：数据 `data/A-exp/`，产物 `artifacts/A-exp/`（LoRA、report、metrics_manifest.json）。

## 默认服务器路径（如与实际不符，先 export 覆盖）

```bash
export PROJECT_DIR=/home/ganfabo/Projects/CodeIR
export CONDA_ENV=CodeIR
export STUDENT_MODEL=/backup01/ganfabo/models/Qwen2.5-7B
export CUDA_VISIBLE_DEVICES=2
```

## Step 1：下载数据集 + 生成训练数据（API 老师）

先冒烟（1 题跑通全链路，硬要求）：

```bash
bash deploy/01_prepare_and_gen.sh --smoke
```

冒烟绿了再全量（300 训 / 100 测）：

```bash
bash deploy/01_prepare_and_gen.sh
```

产物：`data/A-exp/sft_{baseline,armA,armB}/`、`artifacts/A-exp/codeir_llamafactory/`、`metrics_manifest.json`（data_gen 段）、`artifacts/A-exp/raw_sample.json`（首个原始样例，供核对字段/check 调用）。

## Step 2：训练三个 LoRA（baseline r16 / armA r8 / armB r8）

```bash
bash deploy/02_train_three_lora.sh
```

产物：`artifacts/A-exp/lora/{baseline,armA,armB}/`，`metrics_manifest.json`（train 段：gpu_hours/final_loss/wall_sec）。

## Step 3：评测比对（pass@1：baseline 单模型 vs 实验臂 A→B 级联）

```bash
bash deploy/03_eval_compare.sh
```

产物：`artifacts/A-exp/compare_report.md`、`metrics_manifest.json`（eval + verdict 段）。

## 可调参数（在命令前 export 即可）

`N_TRAIN N_TEST EPOCHS LR CUTOFF_LEN BATCH_SIZE GRAD_ACCUM MAX_RESAMPLES HF_ENDPOINT LF_HOME`

---

# 对账：扫 dropped_ids（冤枉 vs 真错）

排查 data_gen 的 ac 率被环境问题（缺包等）压低时用。对每道被 drop 的题，把它持久化的
teacher_raw 生成代码重新喂进真实验证器跑一遍（**不重花 API**），归类输出「能捞回 / 真模型 bug /
仍缺包 / 语法错 / 无样本」，并写 `scan_report.json`。

**先装包再扫**（已知 LeetCodeDataset 的 `prompt` 会 `import sortedcontainers`，缺它会静默误杀一片）：

```bash
pip install sortedcontainers

python tools/scan_dropped.py \
  --run-json    /home/ganfabo/Projects/CodeIR/artifacts/A-exp/metrics_manifest.json \
  --output-root /home/ganfabo/Projects/CodeIR/data/A-exp
```

- `--tests-dir` 默认 `<output-root>/raw_problems/train/tests`；teacher_raw 取 `<output-root>/teacher_raw`。
- 输出末尾的 `RECOVERABLE` 数 = resume 重跑能捞回的题数；`REAL_WA/SYNTAX` 数 = 真·模型 bug，捞不回。

捞回方式（**纯增量、不重花已过的 245 个**）：装包后原样重跑 `bash deploy/01_prepare_and_gen.sh`
（resume 默认开，跳过已有 `verified_triples/<pid>.json` 的题），过了的单题文件自动追加进
`sft_*`，最后由 01 脚本的导出步骤重建合并后的 `codeir_llamafactory/*.jsonl`。
