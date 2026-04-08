# Phase 2: 数据划分

## 目标
按患者级别划分数据，确保无泄漏、无重叠、时序正确。

## 前置条件
- Phase 1 评审通过
- 已确定：患者 ID 列、目标列、数据类型（纵向/横截面）

## 划分策略选择

根据 Phase 1 的样本量自动推荐：

| 样本量 | 模式 | 参数 | 模型选择方式 |
|--------|------|------|-------------|
| n > 5000 | 三分法 | `--train 0.6 --valid 0.2 --test 0.2` | valid 集调参 |
| n 1000-5000 | 两分法 | `--train 0.8 --valid 0.0 --test 0.2` | CV 替代 valid |
| n < 1000 | CV-only | `--train 1.0 --valid 0.0 --test 0.0` | Nested CV + Bootstrap |

## 执行命令

```bash
python3 scripts/tools/split_data.py \
  --input <CSV> \
  --output-dir data/ \
  --patient-id-col <ID> \
  --target-col y \
  --strategy stratified_grouped \
  [--cross-sectional]    # 横截面数据
  [--temporal-cv]        # 纵向数据防时序泄漏
```

## Gate 检查

运行两个 Gate：

```bash
# 1. 泄漏检测
python3 scripts/gates/leakage_gate.py \
  --train data/train.csv --test data/test.csv \
  [--valid data/valid.csv] \
  --patient-id-col <ID> --target-col y \
  --report evidence/leakage_report.json

# 2. 分割协议验证
python3 scripts/gates/split_protocol_gate.py \
  --protocol configs/split-protocol.json \
  --train data/train.csv --test data/test.csv \
  --report evidence/split_protocol_report.json
```

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| S01 | CRITICAL | 同一患者不跨 split |
| S02 | CRITICAL | 测试集时间晚于训练集（纵向数据） |

## 常见陷阱

- 按行随机而非按患者划分 → 同一患者出现在 train 和 test
- 纵向数据未做时序约束 → 未来数据训练预测过去
- 极端不平衡时某个 split 正类为 0
- 划分后 EPV 不再满足 Phase 1 的阈值

## 产出

- `data/train.csv`, `data/valid.csv`（如适用）, `data/test.csv`
- `evidence/leakage_report.json`
- `evidence/split_protocol_report.json`

## 完成后告诉用户

```
Phase 2 数据划分完成:
- 模式: [三分法/两分法/CV-only]
- Train: N 行 (正类 X%)
- Valid: N 行 (正类 X%)  [或 "CV 替代"]
- Test:  N 行 (正类 X%)
- 患者重叠检查: ✓ 无重叠
- 时序检查: ✓ [通过/不适用]
```
