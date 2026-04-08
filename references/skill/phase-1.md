# Phase 1: 数据理解 & 队列定义

## 目标
理解数据结构、验证样本量充足性、建立疾病定义、排除泄漏变量。

## 前置条件
- Intake 问诊已完成（知道预测目标、数据来源、疾病定义）
- CSV 数据文件可访问

## 执行步骤

### 1. 疾病定义审查（如适用）

如果用户提到具体疾病，读取 `references/disease-definition-knowledge-base.json`：
- 获取标准定义模板（ICD 码、实验室阈值、药物、排除标准）
- 识别**泄漏变量黑名单**：定义疾病的变量不能做预测特征（MLGG-F01）
- 评估定义强度（5 层证据）：
  - 1 层 = 弱（审稿人会质疑）
  - ≥ 2 层一致 = 推荐
  - ≥ 3 层 = 强定义

### 2. 运行 Gate

```bash
# 完整 CSV 模式（标准路径）
python3 scripts/gates/cohort_definition_gate.py \
  --data <CSV> \
  --target-col y \
  --id-col <patient_id> \
  --outcome-definition '<JSON>' \
  --definition-cols <cols> \
  --report evidence/cohort_report.json \
  --output-dir evidence/

# 已有 train/test 模式（用 train.csv 做队列检查）
python3 scripts/gates/cohort_definition_gate.py \
  --data data/train.csv \
  --target-col y \
  --id-col <patient_id> \
  --outcome-definition '<JSON>' \
  --definition-cols <cols> \
  --report evidence/cohort_report.json \
  --output-dir evidence/
# 注意：已有 split 时 EPV 基于训练集计算，Phase 2 仍需跑 leakage_gate 验证 split 质量
```

### 3. Gate 检查内容

- **Riley 2019 样本量三准则**: EPV < 5 → FAIL, EPV < 10 → WARNING
- 数据类型自动检测（numeric / binary / categorical）
- 缺失值概况（>50% 标记）
- 异常值检测（3×IQR，仅报告不删除）
- 特征-结局高相关（|r| > 0.8 → 调查泄漏）
- 缺失与结局相关性（MNAR 信号）
- 调查权重自动检测（NHANES/BRFSS）
- 纵向 vs 横截面判定

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| C01 | CRITICAL | 排除结局不可能记录 |
| F01 | CRITICAL | 禁止目标变量作特征 |
| F05 | CRITICAL | 定义预测时间点 |

## 常见陷阱

- HbA1c 列既定义糖尿病又作预测特征 → 最常见的泄漏
- ICD 编码列包含结局疾病的诊断码 → 定义变量泄漏
- NHANES 数据中权重列被当特征
- 缺失率 >80% 的列没被标记

## 产出

- `evidence/cohort_report.json`
- 队列特征摘要（行数、特征数、正类率、EPV）
- 泄漏变量黑名单（后续 Phase 排除用）

## 完成后告诉用户

```
Phase 1 数据理解完成:
- 样本: N 行 × M 特征
- 正类率: X% (N_pos 例)
- EPV: XX（[充足/需注意/不足]）
- 泄漏风险变量: [列出]
- 数据类型: XX numeric, XX categorical, XX binary
- 缺失: XX 列有缺失，最高 XX%
[如有问题，列出 CRITICAL/WARNING]
```
