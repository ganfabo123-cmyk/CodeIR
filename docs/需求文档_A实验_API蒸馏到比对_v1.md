# 需求文档 · A实验（API 老师 → 普通微调 vs IR微调 比对）v1

> 交付顺序 Step 1：**说清楚做什么、为什么**。本文档是 codex 写「部署测试脚本」的唯一依据。
> 配套：《实验设计_v0.md》《数据格式参考_v0.md》。schema / 采样 / 验证过滤 / 三线派生格式**以《数据格式参考_v0》为准，本文不重复**。
> 本文新增的只有两件事：①老师从本地 32B 换成 **API（qwen3-30b-a3b）**；②把链路一路打通到 **pass@1 比对 + 成本指标**。

---

## 0. 一句话目标

用 API 老师生成一份数据，**同源**派生出「普通微调(baseline)」和「IR微调(实验臂)」两条训练线，各训一个学生，在同一批新题上比 pass@1，**并完整记录两次微调的成本与各项指标**，产出一份比对报告，供用户决定项目是否继续。

**成功 ≠ 超过 32B**。本期只回答**问题A（机制承重墙）**：

> 实验臂 pass@1 > baseline pass@1 ？哪怕只高一点，就有卖点，项目继续。

问题B（够到大模型）本期**主动放弃**（用 API 老师→防污染铁律已破，且显存跑不动 32B 参照线）。

---

## 1. 数据流（输入 → 处理 → 输出）

```
[LeetCodeDataset]  ──下载/切分──►  300 训练题 + 100 测试题（题面+可执行测试用例）
       │
       ▼  (M1) API 老师 qwen3-30b-a3b 生成：题→ Rich CodeIR + Python代码
[teacher_raw]  ──(M2) 真机跑测试用例验证过滤──►  只留 AC 样本
       │
       ▼  (M3/M4) 同一份 AC 三元组，派生三套 SFT 数据（不重新生成）
   ┌─────────────────────────┬──────────────────────────┐
   │ baseline: 题→(CoT思路+码) │ 实验臂: 题→IR(A) + IR→码(B) │
   └─────────────────────────┴──────────────────────────┘
       │                              │
       ▼ (M5) LlamaFactory LoRA       ▼ (M5) LlamaFactory LoRA ×2
   [LoRA_baseline rank=16]        [LoRA_A rank=8] [LoRA_B rank=8]
       │                              │
       ▼ (M6) 100 测试题 pass@1       ▼ (M6) 级联推理 A→B，pass@1
       └──────────────┬───────────────┘
                      ▼
        [比对报告.md] + [metrics_manifest.json]（含成本/GPU-小时/token/pass@1）
```

**输入**：LeetCodeDataset（HuggingFace `newfacade/LeetCodeDataset`，自带可执行测试用例+难度+时间字段）。
**输出**：①两个/三个 LoRA 权重 ②比对报告 ③成本指标清单。

---

## 2. 关键参数（已定，codex 不要自行更改）

| 项 | 值 | 来源/理由 |
|---|---|---|
| 老师 | API `qwen3-30b-a3b-instruct-2507` | 用户指定 |
| 端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1`（OpenAI 兼容） | 用户指定 |
| API key 环境变量 | `DASHSCOPE_API_KEY` | 用户确认 |
| 学生基座 | Qwen2.5-7B，**fp16 不量化** | 硬件配置铁律（满血求赢） |
| 数据集 | `newfacade/LeetCodeDataset`，仅 Python | 用户确认 |
| 规模 | 训练 300 题 / 测试 100 题 | 用户确认（小试点，先要 go/no-go） |
| IR 变体 | 本期只用 **Rich**（无损优先） | 数据格式参考 §1 |
| 采样 | 自适应 Best-of-N：贪心1次(temp0) AC即收，WA重采样 temp0.8 最多8次 | 数据格式参考 §3 |
| 训练框架 | LlamaFactory，LoRA | 硬件配置 |

### 公平性铁律（脚本必须强制，违反即实验作废）

1. **同源切分**：三套 SFT 数据全部由 M2 那**同一份 AC 三元组**派生，**禁止**为 baseline 单独再调一次 API。
2. **容量对齐**：baseline `rank=16` ＝ 实验臂 `LoRA_A(8) + LoRA_B(8)`。
3. **同基座同精度**：三条线学生都是 Qwen2.5-7B fp16，同样训练超参（除 rank/数据外）。
4. **验证过滤**：只有 100% 通过测试用例的样本进训练集。
5. **等算力按 GPU-小时记**，不按显存；实验臂推理是两段（≈2×8B），token/时延必须**和精度一起诚实汇报**，不许藏。
6. **测试集区分度**（替代已放弃的防污染）：测试 100 题尽量选**难度偏高/发布日偏新**的题，避免 baseline 和实验臂双双满分导致看不出 IR 增量——**天花板效应是本期最大风险**。

---

## 3. 本期交付的「部署测试脚本」清单（codex 要写的东西）

全部跑在 Linux 训练机（单卡 A6000 48G），复用现有 `deploy/` 风格（conda 激活、日志 tee、绝对路径校验）。

| 脚本 | 职责（一句话） | 关键输入 | 关键输出 |
|---|---|---|---|
| `deploy/prepare_dataset.sh` | 下载 LeetCodeDataset，转成本项目格式，切 300训/100测 | — | `data/raw_problems/{train,test}/*.json`（格式见数据格式参考 §2/§4） |
| `deploy/gen_distill_api.sh` | M1+M2+M3+M4：批量调 API 老师生成→验证过滤→派生三线 SFT | 300 训练题 | `data/verified_triples/`、`data/sft_{baseline,armA,armB}/` |
| `deploy/train_three_lines.sh` | M5：用 LlamaFactory 训 baseline / armA / armB 三个 LoRA | 三套 SFT 数据 | 3 个 LoRA 权重 + 训练日志/指标 |
| `deploy/eval_compare.sh` | M6：100 测试题跑 pass@1（baseline 单模型 / 实验臂 A→B 级联），出比对 | 测试题 + 3 LoRA | `比对报告.md` + `metrics_manifest.json` |
| `deploy/run_A_experiment.sh` | 一键串起上面四步；带 `--smoke` 先用 1 题跑通全链路 | — | 全流程产物 |

> **先冒烟后全量**：`run_A_experiment.sh --smoke` 必须先用 1 题把「API→验证→派生→(可选迷你训练)→评测」整条路跑绿，再放 300 题。这是硬要求（编码节奏：先跑通最小链路）。

---

## 4. 成本监控与指标（用户硬要求："记录两微调的成本等各项指标"）

> **定位是"监控记录"，不是"成本保护"**：不做跑飞自动停。目的只有一个——把两次微调各自花了多少、各拿到多少 pass@1，**如实记下来好做性价比对比**。
> 关键看点：实验臂比 baseline 多花的成本（多训 1 个 LoRA + 推理 ≈2× token/时延）换来了多少 pass@1 增量，**值不值**。

所有阶段把指标写进**统一的 `metrics_manifest.json`**（结构见下），比对报告由它生成。

### 4.1 数据生成阶段（API 成本）
- 调用总次数（含重采样）、输入/输出 token 累计、**估算费用(¥)**、墙钟时间
- 每题采样次数分布、AC 率（多少题最终拿到干净样本）、被丢弃题数

### 4.2 训练阶段（**每条线分别记**：baseline / armA / armB）
- GPU 型号、**GPU-小时**（墙钟 × 卡数）、显存峰值
- 可训练参数量(LoRA)、rank、训练样本数、epoch/步数、最终 train loss
- 训练墙钟

### 4.3 评测阶段（每条线）
- **pass@1（贪心，temp0，单样本）** ← 主指标，公平比对口径
- Best-of-N pass@1（可选，单独列，不与 pass@1 混）
- 平均 attempts、推理墙钟/题、**推理 token/题**（实验臂≈2×baseline，必须诚实体现）
- 按难度分桶（easy/medium/hard）的 pass@1

### 4.4 比对结论（报告核心）
- baseline pass@1 vs 实验臂 pass@1、**差值**、分难度差值
- **性价比对照**：实验臂相对 baseline 的「pass@1 增量 ÷ 多花成本」——多花的训练 GPU-小时、多花的推理 token/题，对应换来多少分
- 一句话 go/no-go：实验臂是否 > baseline

### `metrics_manifest.json` 顶层结构（草稿，遵循全局 schema 简单原则）
```json
{
  "run_id": "A-exp-YYYYMMDD",
  "config": { "teacher_api": "...", "student_base": "...", "n_train": 300, "n_test": 100 },
  "data_gen": { "api_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_cny": 0.0,
                "wall_sec": 0, "ac_rate": 0.0, "kept": 0, "dropped": 0 },
  "train": {
    "baseline": { "gpu_hours": 0.0, "rank": 16, "n_samples": 0, "final_loss": 0.0, "wall_sec": 0 },
    "armA":     { "gpu_hours": 0.0, "rank": 8,  "n_samples": 0, "final_loss": 0.0, "wall_sec": 0 },
    "armB":     { "gpu_hours": 0.0, "rank": 8,  "n_samples": 0, "final_loss": 0.0, "wall_sec": 0 }
  },
  "eval": {
    "baseline":  { "pass_at_1": 0.0, "by_difficulty": {}, "tokens_per_problem": 0, "wall_sec_per_problem": 0.0 },
    "experiment":{ "pass_at_1": 0.0, "by_difficulty": {}, "tokens_per_problem": 0, "wall_sec_per_problem": 0.0 }
  },
  "verdict": { "experiment_minus_baseline": 0.0, "go": null }
}
```

---

## 5. 受影响的代码模块（接入点，给 codex 定位；本文不写实现）

> 原则：**只加不改**。老师已是 provider 架构，加 API 老师＝新增一个 provider。

| 模块 | 改动性质 | 说明 |
|---|---|---|
| `src/codeir/teacher.py` | **新增** `ApiTeacherProvider` | OpenAI 兼容 client，读 `DASHSCOPE_API_KEY` + base_url；`load_teacher_provider` 加 `"api"` 分支。复用现有 `build_teacher_prompt` / `_validate_teacher_payload` |
| `src/codeir/cli.py`（distill） | **扩展** | 支持批量题目输入（目录/jsonl，非单题）、`--provider api`；其余链路（验证/派生/导出）已存在，尽量复用 |
| 评测模块 M6 | **新增** | pass@1 评测器 + 实验臂 A→B 级联推理 + 比对报告/指标输出。infer.py 已有单 LoRA 推理可复用 |
| 指标记录 | **新增** | 贯穿各阶段写 `metrics_manifest.json` |
| `RUN_COMMANDS.md` | **更新** | 新增 API 蒸馏 / 训练 / 评测的标准命令（全局规范 §十二） |

---

## 6. 验收标准（怎么算这份脚本做完了）

1. `run_A_experiment.sh --smoke` 1 题跑通：API 出 CodeIR+码 → 验证 AC → 派生三线 → 评测能出 pass@1 数字（哪怕迷你训练）。
2. 全量 300/100 跑完，产出：3 个 LoRA + `比对报告.md` + `metrics_manifest.json`。
3. 报告里能直接读到：**baseline pass@1、实验臂 pass@1、差值、go/no-go**，以及第 4 节全部成本指标。
4. 三套 SFT 数据可追溯到**同一份** `verified_triples`（铁律1 自检）；rank 配置满足 16=8+8（铁律2 自检）。

---

## 7. [待确认]（codex 拉到真实数据后核对，别猜）

| # | 项 | 解决路径 |
|---|---|---|
| 1 | LeetCodeDataset 字段 → 本项目 `problem/testcases` 格式的精确映射（entry_point、参数名、expected 类型） | 下载后看真实样例再写映射，禁止猜 |
| 2 | 该数据集测试用例是否全是 functional 式（有无 stdin/stdout 题、有无特判/浮点比较） | 同上，核对后决定执行器是否要扩展 |
| 3 | API 限流/并发上限、单次 max_tokens、是否支持 OpenAI `response_format` 强制 JSON | 用 1 题试调确认；不支持 JSON mode 就退回提示词约束+解析 |
| 4 | 成本监控的口径（API 单价用哪一档算 ¥、GPU-小时按单卡墙钟） | 出脚本时按 DashScope 当前定价填默认单价，记录原始 token 便于事后重算 |
| 5 | baseline 的 codeir→CoT 线性化模板措辞（保证与实验臂等信息） | 数据格式参考 §6，最小链路时定 |

---

> **下一交付物**（本文确认后）：Step 2 接口文档 / Step 4 代码骨架——`ApiTeacherProvider` 签名、批量 distill 入口、M6 评测器签名、metrics manifest 写入点，**只签名+注释+`[待确认]`，无实现**。
