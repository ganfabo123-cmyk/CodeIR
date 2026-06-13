# CodeIR

根据 `docs/` 下三份设计文档实现的最小可运行部署，覆盖：

- `M1` 老师生成接口与自适应 Best-of-N 调度
- `M2` 本地代码验证过滤
- `M3` Rich/Lean CodeIR 派生
- `M4` 三条 SFT 样本派生

当前版本优先保证单题到批量链路可运行，训练与评测先输出数据和配置骨架，不直接绑定具体模型框架。

## 目录

```text
src/codeir/           Python 包
examples/             单题样例与 mock 老师输出
data/                 运行生成的数据目录
```

## 安装

优先使用免安装方式：

```powershell
python .\run_codeir.py verify --triple examples\triple_lis.json --tests examples\testcases_lis.json
```

如果本机具备完整 `pip/setuptools` 环境，也可以再做 editable install：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e . --no-build-isolation
```

## 快速开始

1. 验证单题代码：

```powershell
python .\run_codeir.py verify --triple examples\triple_lis.json --tests examples\testcases_lis.json
```

2. 跑最小链路（使用 mock 老师）：

```powershell
python .\run_codeir.py distill --problem examples\problem_lis.json --tests examples\testcases_lis.json --provider mock --output-root data
```

3. 从 `verified_triples` 派生训练样本：

```powershell
python .\run_codeir.py derive --verified-root data\verified_triples --output-root data
```

## Linux 一键部署

Linux 下当前脚本已经改成“只下载老师和学生模型，不配环境”：

```bash
bash deploy/linux_one_click.sh
```

使用时需要显式提供老师/学生仓库，以及它们的预估体积：

```bash
TEACHER_MODEL_ID=<your_teacher_repo> \
STUDENT_MODEL_ID=<your_student_repo> \
TEACHER_SIZE_GB=22 \
STUDENT_SIZE_GB=14 \
DISK_BUDGET_GB=50 \
bash deploy/linux_one_click.sh
```

脚本会先检查：

- 你声明的老师+学生体积之和不超过 `50G`
- 实际磁盘可用空间不少于 `50G`

脚本默认使用 Hugging Face 国内镜像：

```bash
HF_MIRROR=https://hf-mirror.com
```

如果你有自己的镜像，可以直接覆盖 `HF_MIRROR`。

更多变量和限制见 [deploy/linux_requirements_note.md](/D:/PycharmProjects/CodeIR/deploy/linux_requirements_note.md:1)。

## 环境变量

- `CODEIR_PROVIDER=mock|transformers`
- `CODEIR_MODEL_PATH=<本地模型目录>`

`transformers` provider 需要用户自行准备本地模型权重和对应运行环境。A6000/Ampere 按文档约束只应使用 `int8`，不要用 `fp8`。
