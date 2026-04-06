# Medical ML Project Template

基于 MLGG（Medical ML Leakage Guard）方法学标准的医学二分类预测项目模板。

内置 AI 审稿人，在你写代码的过程中实时检查数据泄漏、方法学错误和报告缺陷。

## 30 秒快速开始

```bash
# 1. 克隆模板
git clone <this-repo> my-project && cd my-project

# 2. 运行配置向导（会问你几个问题，自动生成 config.py）
python3 tools/setup.py --csv path/to/your_data.csv

# 3. 查看项目状态
python3 tools/check.py

# 4. 打开 Claude Code，输入 /mlgg，开始！
```

## 这个模板会帮你做什么

| 你做的事情 | 模板自动做的事情 |
|-----------|----------------|
| 写预处理代码 | Claude 实时检查 fit() 是否只用了训练集 |
| 做特征选择 | Claude 检查是否在训练集内完成，提醒对比 Ridge baseline |
| 训练模型 | Claude 确认测试集没有参与任何调参/选择 |
| 看结果 | Claude 检查是否报告了完整指标面板和 95% CI |
| 写论文 | Claude 帮你过 TRIPOD+AI 2024 checklist |

## 三层防护

```
你写代码
  │
  ├── CLAUDE.md（自动生效）
  │   Claude 始终按 MLGG 标准审查，发现泄漏立即警告
  │
  ├── /mlgg（手动触发）
  │   9-Phase 完整指导 + 26 条规则 + 检查点
  │
  └── Qwen 二审（可选）
      在关键节点调用 Qwen 做独立审查，交叉验证
```

## 项目结构

```
├── tools/
│   ├── setup.py              # 配置向导（首次使用）
│   ├── check.py              # 项目状态仪表盘
│   └── qwen_review.py        # Qwen 辅助审查
│
├── config.py                  # 全局配置（由 setup.py 生成）
├── run_all.py                 # 一键运行所有阶段
│
├── 00_database/raw/           # 原始数据（只读）
├── 01_exploration/            # Phase 1: 数据理解
├── 02_splitting/              # Phase 2: 数据分割
├── 03_preprocessing/          # Phase 3: 预处理
├── 04_feature_selection/      # Phase 4: 特征选择
├── 05_modeling/               # Phase 5: 模型训练
├── 06_evaluation/             # Phase 6: 评估
├── 07_interpretability/       # Phase 7: 可解释性
├── 08_fairness/               # Phase 8: 公平性
├── 09_reporting/              # Phase 9: 报告
├── outputs/                   # 最终产物（论文直接引用）
│
├── .claude/commands/mlgg.md   # /mlgg 审稿人 skill
├── CLAUDE.md                  # 项目级方法学规则
└── references/mlgg-rules.md   # 规则速查手册
```

## 常用命令

```bash
python3 tools/setup.py                    # 交互式配置
python3 tools/setup.py --csv data.csv     # 指定 CSV 配置
python3 tools/check.py                    # 查看进度
python3 run_all.py                        # 运行全部
python3 run_all.py --from 3              # 从 Phase 3 继续
python3 run_all.py --only 6              # 只跑 Phase 6

# Qwen 辅助审查（需要配置 .env）
python3 tools/qwen_review.py --file <script.py> --check leakage
python3 tools/qwen_review.py --file <script.py> --check all
```

## 配置 Qwen 辅助审查（可选）

```bash
cp .env.example .env
# 编辑 .env，填入你的 DashScope API Key
```

## 不需要 Claude Code 也能用

即使不用 Claude Code，这个模板仍然有用：
- 9 个阶段的脚手架代码遵循 MLGG 最佳实践
- `references/mlgg-rules.md` 是独立的规则参考文档
- `tools/qwen_review.py` 可以独立运行代码审查
- `tools/check.py` 可以追踪项目进度

## MLGG 方法学标准

本模板内置 26 条 MLGG 规则，每条都有文献引用：

- **数据泄漏防护**: 患者级分割、时序约束、预处理隔离
- **特征安全**: 禁止标签泄漏、未来信息、训练集外选择
- **评估严谨**: 完整指标面板、Bootstrap CI、校准三件套、DCA
- **可复现性**: 固定随机种子、多种子稳定性检验
- **公平性**: 亚组分析 + CI、差异讨论
- **报告合规**: TRIPOD+AI 2024 checklist

详见 `references/mlgg-rules.md`。
