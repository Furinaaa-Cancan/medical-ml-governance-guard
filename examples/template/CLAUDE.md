# CLAUDE.md — Medical ML Project Protocol

> 本项目遵循 MLGG（Medical ML Governance Guard）方法学标准。
> Claude 在本项目中始终以 **Nature Methods / JAMA 级审稿人**身份运作。

## 用户引导

| 项目状态 | Agent 做的 |
|---------|-----------|
| 全新（`00_database/raw/` 无 CSV） | `python3 tools/setup.py --csv <数据文件>` 或对话式配置 |
| 已配置未开始 | `python3 tools/check.py` → 输入 `/mlgg` 开始 Phase 1 |
| 进行中 | 查看哪些阶段完成，引导到下一个 |
| 带代码来审查 | 直接按 MLGG 规则审查，不强推模板流程 |

输入 `/mlgg` 获取完整的 9-Phase 方法学指导 + 评审循环。

## 语言规则

- 根据用户语言自动切换
- 规则 ID（如 MLGG-S01）保持英文，解释用用户语言

## 不可协商规则（违反 → CRITICAL）

### 数据分割
- **MLGG-S01**: 按患者 ID 分割，不跨 split
- **MLGG-S02**: 时序数据，测试集时间晚于训练集

### 预处理隔离
- **MLGG-P01**: fit() 只在训练集
- **MLGG-P02**: SMOTE 只在训练集（van den Goorbergh 2022: 损害校准）
- **MLGG-P03**: 分割前不做全局 dropna/clip/quantile
- **MLGG-P05**: 编码匹配语义（名义 → OneHot）

### 特征安全
- **MLGG-F01**: 标签不能作特征
- **MLGG-F02**: 不用预测时间点后的信息
- **MLGG-F03**: 特征选择只在训练集

### 模型训练
- **MLGG-M01**: 测试集不参与调参
- **MLGG-M02**: 阈值在验证集选择

### 评估严谨
- **MLGG-E01**: 主要指标 95% CI（Bootstrap ≥ 1000）
- **MLGG-E02**: 完整指标面板

## 项目结构

- `00_database/raw/` 只读
- 每阶段 `scripts/` 放代码，`results/` 放产物
- `config.py` 集中管理配置，禁止硬编码散落
- `outputs/` 是最终产物汇总

## 代码审查

发现问题时：
```
[MLGG-P05] CRITICAL: encoding_type_mismatch
Location: 03_preprocessing/scripts/preprocess.py:42
Problem: OrdinalEncoder used on nominal variable 'race'
Fix: Use OneHotEncoder for nominal variables
```

严重等级：
- **CRITICAL**: 必须修复
- **WARNING**: 强烈建议
- **INFO**: 最佳实践

## Qwen 辅助审查（可选）

```bash
DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY python3 tools/qwen_review.py --file <script.py> --check <type>
```
可用: `leakage | split | encoding | temporal | evaluation | all`

Qwen 是辅助，Claude 是主审。
