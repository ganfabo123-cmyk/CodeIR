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

---

# 扩量重跑 + 跳过已知真错（SKIP_IDS_FILE）

扩到更多训练题（如 500）时，已过的题靠 resume 自动跳过、0 API；但**真·模型 bug** 的题
（树/skyline 那类）每轮都会被重采 `max_resamples+1` 次才掉，纯浪费。`--skip-ids-file`
让它们直接跳过（不花 API、**不计入 dropped、不污染 ac_rate**，metrics 多一个 `skiplisted`）。

skip 名单直接取**当前** manifest 的 `dropped_ids`（resume 重跑过一次后它已自愈、只剩真错）：

```bash
# 1) 从 manifest 生成 skip 名单
python -c "import json;print('\n'.join(json.load(open('artifacts/A-exp/metrics_manifest.json'))['data_gen']['dropped_ids']))" > skip_ids.txt

# 2) 扩量重跑:跳过真错,只对新题花 API
SKIP_IDS_FILE=skip_ids.txt N_TRAIN=500 bash deploy/01_prepare_and_gen.sh
```

- 245 已过 → resume 跳过；真错 → skip-list 跳过；新增题 → 正常生成。
- 日志里真错 id 显示 `-> skip (in skip-list)`，不再有 attempts。
- 想强制重试某个被 skip 的题：从 `skip_ids.txt` 删掉那行即可（与 resume 正交，可随时增删）。

---

# 难度对齐重训：从已验证的 420 切 320 训 / 100 测（不重花 API）

> 背景：原 split 训练池偏易（~27/58/15 易/中/难）、测试集却是最难优先（0/21/79），
> 人为倒置导致学生贴地板。这里**复用已验证的 420 题**重切一个难度分布一致的 train/test，
> 老师那步不重跑。新数据落在独立根 `data/A-exp-resplit/`，**不动 `data/A-exp/` 任何文件**。
> GPU 用 4 号卡（`_common.sh` 默认 2/3 常被占，落上去会 CPU offload 极慢）。

```bash
cd /home/ganfabo/Projects/CodeIR
git pull

# 1) 切分：420 -> 320 训(verified_triples) + 100 测(raw_problems/test)，分层匹配难度
python tools/resplit_verified.py --src data/A-exp --out data/A-exp-resplit \
  --n-test 100 --seed 42
# 期望输出：TRAIN 320 (easy=86 medium=187 hard=47) / TEST 100 (27/58/15) / overlap 0

# 2) 从 320 verified 派生 SFT（输出进新根，sft_* 干净只含 320）
python -m codeir.cli derive \
  --verified-root data/A-exp-resplit/verified_triples \
  --output-root   data/A-exp-resplit

# 3) 导出 LlamaFactory 数据集
python -m codeir.cli export-llamafactory \
  --output-root data/A-exp-resplit \
  --export-root artifacts/A-exp-resplit

# 4) 三个 adapter 全重训（训练集从 420 缩到 320，baseline 也变，三个都要重训）
RUN_ID=A-exp-resplit ARMS="baseline armA armB" CUDA_VISIBLE_DEVICES=4 \
  bash deploy/02_train_three_lora.sh

# 5) 在新的 100 题测试集上重评（先 LIMIT=5 冒烟，绿了再全量去掉 LIMIT）
RUN_ID=A-exp-resplit LIMIT=5 CUDA_VISIBLE_DEVICES=4 bash deploy/03_eval_compare.sh
RUN_ID=A-exp-resplit       CUDA_VISIBLE_DEVICES=4 bash deploy/03_eval_compare.sh
```

- 产物在 `artifacts/A-exp-resplit/`：`lora/{baseline,armA,armB}/`、`compare_report.md`
  （这次 `by_difficulty` 三档都有量，baseline vs experiment 才有分辨率）、`compare_report_raw.jsonl`。
- `RUN_ID=A-exp-resplit` 让 `_common.sh` 把 `DATA_ROOT`/`ARTIFACTS` 整体指向新根，deploy 脚本一字不改。
- 注：`_select_test` 已改为分层匹配训练分布（不再最难优先）；本次复用 420 不走 `prepare-leetcode`，
  那个修复只在将来重新 `prepare-leetcode` 拉数据时生效。
