# Phase 2: 数据划分

## 目标
按患者级别划分数据，确保无泄漏、无重叠、时序正确。

## 前置条件
- Phase 1 评审通过：`evidence/cohort_report.json` 存在且无 CRITICAL
- 已确定：患者 ID 列、目标列、数据类型（纵向/横截面）

## 划分策略选择

根据 Phase 1 的样本量自动推荐：

| 样本量 | 模式 | 参数 | 模型选择方式 |
|--------|------|------|-------------|
| n > 5000 | 三分法 | `--train 0.6 --valid 0.2 --test 0.2` | valid 集调参 |
| n 1000-5000 | 两分法 | `--train 0.8 --valid 0.0 --test 0.2` | CV 替代 valid |
| n < 1000 | CV-only | `--train 1.0 --valid 0.0 --test 0.0` | Nested CV + Bootstrap |

## 配置准备（首次运行时）

如果 `configs/` 目录不存在，先初始化：
```bash
mkdir -p configs
cp references/templates/split-protocol.example.json configs/split-protocol.json
```
然后编辑 `configs/split-protocol.json`：
- `id_col` → 实际患者 ID 列名
- `target_col` → 实际目标列名
- `requires_temporal_order` → 横截面数据设为 `false`
- `split_strategy` → 根据数据类型选择

> 后续 Phase 4/5/9 也需要 configs/ 下的配置文件，各 Phase 文件中有具体说明。

## 执行命令

```bash
python3 scripts/training/split_data.py \
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
  --id-cols <ID> --target-col y \
  --report evidence/leakage_report.json --strict

# 2. 分割协议验证
# 如果 configs/split-protocol.json 不存在，先从模板创建:
#   cp references/templates/split-protocol.example.json configs/split-protocol.json
#   然后根据实际划分参数编辑
python3 scripts/gates/split_protocol_gate.py \
  --protocol-spec configs/split-protocol.json \
  --train data/train.csv --test data/test.csv \
  --id-col <ID> --target-col y \
  [--cross-sectional] \
  --report evidence/split_protocol_report.json --strict
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
