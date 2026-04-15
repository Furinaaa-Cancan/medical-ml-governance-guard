# 5 分钟快速体验 / 5-Minute Quickstart

从零到看到第一份审查报告，只需要 2 步。

From zero to your first audit report in 2 steps.

---

## Step 1: 安装 / Install

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
cd medical-ml-governance-guard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

验证 / Verify:
```bash
python3 scripts/orchestration/mlgg.py doctor
```

---

## Step 2: 跑你的第一个审查 / Run Your First Audit

### 选项 A: 用自带数据（最快，30 秒）

```bash
# 划分数据（患者级隔离 + 时序分割）
python3 scripts/training/split_data.py \
  --input examples/heart_disease.csv \
  --output-dir /tmp/mlgg_first_run \
  --target-col y --patient-id-col patient_id --time-col event_time \
  --strategy grouped_temporal --seed 42

# 检测数据泄漏
python3 scripts/gates/leakage_gate.py \
  --train /tmp/mlgg_first_run/train.csv \
  --valid /tmp/mlgg_first_run/valid.csv \
  --test /tmp/mlgg_first_run/test.csv \
  --target-col y --id-cols patient_id --time-col event_time \
  --report /tmp/mlgg_first_run/leakage_report.json
```

你会看到:
```
Gate: leakage_gate
Status: PASS  |  Failures: 0  |  Warnings: 0
```

这说明：没有患者跨 split 泄漏、没有时序泄漏、没有行重复。

### 选项 B: 用自己的 CSV

```bash
# 把上面的 examples/heart_disease.csv 换成你的文件
# 把 patient_id、y、event_time 换成你的列名
python3 scripts/training/split_data.py \
  --input /path/to/your_data.csv \
  --output-dir /tmp/my_project \
  --target-col 你的目标列 --patient-id-col 你的患者ID列 \
  --strategy grouped_temporal --seed 42

python3 scripts/gates/leakage_gate.py \
  --train /tmp/my_project/train.csv \
  --test /tmp/my_project/test.csv \
  --target-col 你的目标列 --id-cols 你的患者ID列 \
  --report /tmp/my_project/leakage_report.json
```

### 选项 C: 完整的 AI 审稿人体验（需要 Claude Code）

```bash
claude          # 打开 Claude Code
/mlgg           # 输入 /mlgg，AI 审稿人全程引导 9 阶段
```

---

## Step 3（可选）: 看更多门控 / Try More Gates

leakage_gate 只检查数据泄漏。MLGG 有 33 道门控，覆盖 9 个阶段。试试：

```bash
# 校准检测（你的模型预测概率准不准？）
python3 scripts/gates/calibration_dca_gate.py \
  --prediction-trace /path/to/prediction_trace.csv \
  --evaluation-report /path/to/evaluation_report.json \
  --report /tmp/calibration_report.json

# 静态代码扫描（你的 Python 代码有没有泄漏？）
python3 -m mlgg_lint check /path/to/your_script.py

# 一键全量审计（不需要配置文件）
python3 scripts/reporting/generate_audit_report.py --project-dir /path/to/project
```

---

## 常见问题 / FAQ

**Q: 我没有 patient_id 列怎么办？**

如果每行是独立样本（不是同一患者的多次就诊），可以用行号做 ID：
```bash
--patient-id-col ""  # 空字符串 = 每行独立
```

**Q: 我的数据是横截面的（没有时间列）怎么办？**

省略 `--time-col` 参数即可：
```bash
python3 scripts/training/split_data.py \
  --input data.csv --output-dir /tmp/out \
  --target-col y --patient-id-col pid \
  --strategy stratified_grouped --seed 42
```

**Q: gate 报了 FAIL，我该怎么修？**

每个 failure 都附有修复建议。查看报告 JSON 中的 `failures[].remediation` 字段，或：
```bash
python3 scripts/reporting/explain_gate.py --gate leakage_gate
```

**Q: 我想跑完整 33 道门控怎么做？**

```bash
# 方式 1: 交互式（推荐新手）
python3 scripts/orchestration/mlgg.py onboarding \
  --project-root /tmp/my_project --mode guided --yes

# 方式 2: Claude Code AI 审稿人（最强体验）
claude
/mlgg
```

---

## 下一步 / Next Steps

- 完整文档：[README.md](../../README.md)
- 故障排除：[Troubleshooting-Top20.md](Troubleshooting-Top20.md)
- 架构说明：[Architecture.md](Architecture.md)
- API 参考：[API-Reference.md](API-Reference.md)
