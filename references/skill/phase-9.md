# Phase 9: 报告

## 目标
生成出版级报告，通过 TRIPOD+AI 2024 和 PROBAST+AI 2025 合规检查，输出最终质量评分。

## 前置条件
- Phase 8 评审通过
- 所有 evidence/ 报告文件已生成

## Gate 检查

```bash
# 1. 报告偏倚检查（TRIPOD+AI / PROBAST+AI / STARD-AI）
python3 scripts/gates/reporting_bias_gate.py \
  --checklist configs/reporting-bias-checklist.json \
  --report evidence/reporting_bias_report.json --strict

# 2. 出版门控（聚合所有 gate）
python3 scripts/gates/publication_gate.py \
  --evidence-dir evidence/ \
  --report evidence/publication_gate_report.json --strict

# 3. 自我批评评分
python3 scripts/gates/self_critique_gate.py \
  --evidence-dir evidence/ \
  --report evidence/self_critique_report.json --strict

# 4. 安全审计
python3 scripts/gates/security_audit_gate.py \
  --evidence-dir evidence/ \
  --report evidence/security_audit_gate_report.json --strict
```

## 12 维评分体系（100 分制）

| # | 维度 | 权重 |
|---|------|------|
| 1 | Data Integrity | 12 |
| 2 | Leakage Prevention | 15 |
| 3 | Pipeline Isolation | 12 |
| 4 | Model Selection Rigor | 10 |
| 5 | Statistical Validity | 12 |
| 6 | Generalization Evidence | 10 |
| 7 | Clinical Completeness | 7 |
| 8 | Reporting Standards | 7 |
| 9 | Reproducibility | 6 |
| 10 | Security & Provenance | 3 |
| 11 | Fairness & Equity | 3 |
| 12 | Sample Size Adequacy | 3 |

评级: ≥90 顶刊级 · 75-89 需补充 · 60-74 重大缺陷 · <60 不可发表

## 报告精度控制

- n < 500 → 最多 2 位小数
- n < 200 → 1 位小数
- NC 审稿人拒绝过度精确的报告（如 AUC=0.8112 但 n=140）

## 必须包含的报告内容

- TRIPOD+AI 2024 清单 27 项（Collins 2024 BMJ）
- PROBAST+AI 2025 偏倚风险 4 域（Moons 2025 BMJ）
- Model Card: `generate_model_card()`
- TRIPOD Table 1: 按 split 的队列特征表
- **局限性讨论**（不可省略）:
  - 数据来源和代表性
  - 时间外推限制
  - 外部验证状态
  - 公平性差异
  - DCA 阈值范围的临床意义

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| T01 | WARNING | TRIPOD+AI 2024 合规 |

## 完成后告诉用户

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MLGG 9-Phase 流程完成
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  总评分: XX/100 ([顶刊级/需补充/重大缺陷])
  
  Phase 通过情况:
  ✓ Phase 1-9 全部通过
  
  Gate 统计:
  • XX 项 CRITICAL 检查通过
  • XX 项 WARNING（已处理/已声明）
  
  关键产出:
  • evidence/publication_gate_report.json
  • evidence/self_critique_report.json
  
  下一步:
  • 运行 render_user_summary.py 生成可读报告
  • 检查 TRIPOD+AI 清单未覆盖项
  • 补充外部验证（如需要）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
