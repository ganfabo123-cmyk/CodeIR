# CodeIR 交付文档

## 1. 交付概述

本次交付基于仓库 `docs/` 下三份设计文档完成了一个可运行的最小部署版本，目标是先跑通文档中定义的最小链路：

`单题输入 -> 老师生成 -> 代码验证过滤 -> 干净三元组落盘 -> SFT 样本派生`

当前交付重点覆盖：

- `M1` 老师生成接口与 Best-of-N 调度骨架
- `M2` 本地代码验证过滤执行器
- `M3` Rich / Lean CodeIR 派生
- `M4` 三条训练样本派生
- 命令行入口、样例数据、运行说明

当前版本优先保证“可运行、可验证、可扩展”，暂未直接落地 LlamaFactory 训练与正式评测脚本。

## 2. 交付内容

### 2.1 代码与入口

- [run_codeir.py](/D:/PycharmProjects/CodeIR/run_codeir.py:1)
  免安装启动入口，避免当前机器环境对 `editable install` 的依赖。
- [src/codeir/cli.py](/D:/PycharmProjects/CodeIR/src/codeir/cli.py:1)
  命令行主入口，提供 `verify`、`distill`、`derive` 三个命令。
- [src/codeir/verifier.py](/D:/PycharmProjects/CodeIR/src/codeir/verifier.py:1)
  本地执行候选代码并比对测试用例结果。
- [src/codeir/teacher.py](/D:/PycharmProjects/CodeIR/src/codeir/teacher.py:1)
  老师模型接口，包含 `mock` provider 和 `transformers` provider 骨架。
- [src/codeir/pipeline.py](/D:/PycharmProjects/CodeIR/src/codeir/pipeline.py:1)
  蒸馏、验证、落盘、训练样本派生的主流程。
- [src/codeir/ir.py](/D:/PycharmProjects/CodeIR/src/codeir/ir.py:1)
  Rich / Lean IR 转换与序列化。
- [src/codeir/schemas.py](/D:/PycharmProjects/CodeIR/src/codeir/schemas.py:1)
  数据结构定义与 JSON / 文本读写。

### 2.2 样例与输出

- [examples/problem_lis.json](/D:/PycharmProjects/CodeIR/examples/problem_lis.json:1)
- [examples/testcases_lis.json](/D:/PycharmProjects/CodeIR/examples/testcases_lis.json:1)
- [examples/triple_lis.json](/D:/PycharmProjects/CodeIR/examples/triple_lis.json:1)
- [examples/teacher_mock/lc-300-demo.json](/D:/PycharmProjects/CodeIR/examples/teacher_mock/lc-300-demo.json:1)

运行后会生成：

- [data/teacher_raw/lc-300-demo/sample_0.json](/D:/PycharmProjects/CodeIR/data/teacher_raw/lc-300-demo/sample_0.json:1)
- [data/verified_triples/lc-300-demo.json](/D:/PycharmProjects/CodeIR/data/verified_triples/lc-300-demo.json:1)
- [data/ir_variants/rich/lc-300-demo.yaml](/D:/PycharmProjects/CodeIR/data/ir_variants/rich/lc-300-demo.yaml:1)
- [data/ir_variants/lean/lc-300-demo.yaml](/D:/PycharmProjects/CodeIR/data/ir_variants/lean/lc-300-demo.yaml:1)
- [data/sft_armA/lc-300-demo.json](/D:/PycharmProjects/CodeIR/data/sft_armA/lc-300-demo.json:1)
- [data/sft_armB/lc-300-demo.json](/D:/PycharmProjects/CodeIR/data/sft_armB/lc-300-demo.json:1)
- [data/sft_baseline/lc-300-demo.json](/D:/PycharmProjects/CodeIR/data/sft_baseline/lc-300-demo.json:1)

## 3. 已实现能力

### 3.1 M1 老师生成

- 支持按题目输入生成 `CodeIR + code`
- 支持自适应 Best-of-N 主流程
- 当前默认可用 `mock` provider
- 预留 `transformers` provider，用于后续接本地 Qwen2.5-32B int8

### 3.2 M2 验证过滤

- 将候选代码写入临时执行脚本
- 通过 `Solution.<entry_point>` 调用题解方法
- 对所有测试用例执行比对
- 支持超时失败判定
- 产出 `verified` 结论

### 3.3 M3 IR 派生

- 支持从统一 `CodeIR` 派生 Rich 版本
- 支持派生 Lean 版本
- 支持输出为 YAML 或 JSON 文本

### 3.4 M4 样本派生

- `题面 -> CodeIR` 样本
- `CodeIR -> 代码` 样本
- `题面 -> CoT思路+代码` baseline 样本

## 4. 运行方式

推荐直接使用免安装方式：

```powershell
python .\run_codeir.py verify --triple examples\triple_lis.json --tests examples\testcases_lis.json
python .\run_codeir.py distill --problem examples\problem_lis.json --tests examples\testcases_lis.json --provider mock --output-root data
python .\run_codeir.py derive --verified-root data\verified_triples --output-root data --ir-format yaml
```

如本机具备完整 `pip/setuptools` 环境，可再尝试：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e . --no-build-isolation
```

## 5. 实际验证结果

本次交付已实际跑通以下命令：

```powershell
python .\run_codeir.py verify --triple examples\triple_lis.json --tests examples\testcases_lis.json
```

结果：

```json
{"verified": true, "passed": 4, "total": 4, "error": ""}
```

```powershell
python .\run_codeir.py distill --problem examples\problem_lis.json --tests examples\testcases_lis.json --provider mock --output-root data
```

结果：

```json
{"accepted": true, "attempts": 1, "problem_id": "lc-300-demo", "verified": true, "error": ""}
```

```powershell
python .\run_codeir.py derive --verified-root data\verified_triples --output-root data --ir-format yaml
```

结果：

```json
{"derived": 1}
```

## 6. 当前限制

- 当前正式可用的是 `mock` provider，本地 32B `transformers` provider 仅完成接口骨架，未在本机接入真实模型验证。
- 尚未实现题库批处理、并发调度、失败重试策略细化、落盘日志分级。
- 尚未实现 LlamaFactory 训练配置生成、训练启动脚本、正式评测脚本。
- 当前未实现严格沙箱隔离，仅使用子进程 + 超时机制执行代码，适合最小验证，不适合直接执行高风险不可信代码。
- 当前环境下 `editable install` 受限于本机 Python 权限和构建环境，因此优先建议使用 `run_codeir.py`。

## 7. 与设计文档的对应关系

已覆盖：

- `需求文档_v0.md` 中要求的最小链路起点：`M1 + M2`
- `数据格式参考_v0.md` 中的三元组格式、测试用例格式、三条线样本派生
- `实验设计_v0.md` 中“先跑通单题链路，再扩批量”的实施路径

未覆盖：

- `M5` LlamaFactory LoRA 训练
- `M6` pass@1 正式评测
- LiveCodeBench 时间切分测试集接入
- 真实本地 Qwen2.5-32B int8 推理部署联调

## 8. 建议的下一步

建议按以下顺序继续推进：

1. 接入真实本地老师模型，完成 `transformers` provider 联调。
2. 增加批量题库处理和运行日志。
3. 生成 `verified_triples` 到 LlamaFactory 所需训练格式。
4. 补 `M5` 训练配置与启动脚本。
5. 补 `M6` 评测脚本和分难度统计输出。

## 9. 交付结论

本次交付已经将纯文档仓库推进为一个可运行的最小工程，能够从样例题输入出发，完成生成、验证、落盘和训练样本派生，满足“先跑通最小链路”的交付目标。后续工作重点不再是从零搭骨架，而是接入真实模型、扩展数据规模和补齐训练评测闭环。
