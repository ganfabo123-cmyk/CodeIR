# Linux 模型下载说明

## 入口

```bash
bash deploy/linux_one_click.sh
```

当前脚本只做两件事：

- 下载老师模型
- 下载学生模型

它不会：

- 创建虚拟环境
- 安装 Python 依赖
- 安装 LlamaFactory
- 训练
- 推理

## 50G 磁盘约束

- `MODEL_ROOT`
- `DISK_BUDGET_GB`
- `TEACHER_MODEL_ID`
- `STUDENT_MODEL_ID`
- `TEACHER_SIZE_GB`
- `STUDENT_SIZE_GB`
- `HF_TOKEN`
- `HF_MIRROR`

默认会使用国内镜像：

- `HF_MIRROR=https://hf-mirror.com`

如果你有自己的镜像地址，可以直接覆盖这个变量。

脚本会先做两层检查：

1. `TEACHER_SIZE_GB + STUDENT_SIZE_GB <= DISK_BUDGET_GB`
2. `MODEL_ROOT` 所在磁盘的可用空间至少达到 `DISK_BUDGET_GB`

注意：

- 这个“50G 可下”只对你声明的模型体积成立。
- 如果你填的是原始 `32B` 老师仓库，通常本身就不可能稳进 `50G`。
- 想压进 `50G`，老师和学生都应选已经量化过、体积更小的仓库。

## 常用环境变量

- `MODEL_ROOT`
- `DISK_BUDGET_GB=50`
- `TEACHER_MODEL_ID`
- `STUDENT_MODEL_ID`
- `TEACHER_SIZE_GB`
- `STUDENT_SIZE_GB`
- `HF_TOKEN`
- `HF_MIRROR`

## 示例

```bash
TEACHER_MODEL_ID=<your_teacher_repo> \
STUDENT_MODEL_ID=<your_student_repo> \
TEACHER_SIZE_GB=22 \
STUDENT_SIZE_GB=14 \
DISK_BUDGET_GB=50 \
bash deploy/linux_one_click.sh
```

## 前提

- Linux
- 已安装 `huggingface-cli`
- 能联网访问 Hugging Face 或配置镜像

## 限制

- 脚本不会自动判断某个仓库的真实体积，只按你声明的 `*_SIZE_GB` 做预算拦截。
- “保证 50G 可下”不等于“任何老师/学生组合都能下”，而是“脚本拒绝超预算组合”。
