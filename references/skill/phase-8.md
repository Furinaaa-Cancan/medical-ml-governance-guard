# Phase 8: 公平性

## 目标
检查模型在不同亚组（性别/种族/年龄）上的表现差异，评估公平性。

## 前置条件
- Phase 7 评审通过：`evidence/shap_report.json` 存在且无 CRITICAL
- `evidence/evaluation_report.json` 存在
- 测试集包含保护属性列

## Gate 检查

```bash
python3 scripts/gates/fairness_equity_gate.py \
  --evaluation-report evidence/evaluation_report.json \
  --report evidence/fairness_equity_report.json --strict
```

## 检查内容

| 指标 | 阈值 | 含义 |
|------|------|------|
| 均等化优势 (Equalized Odds) gap | < 0.15 | Sens/Spec 跨亚组差异 |
| 差异影响比 (Disparate Impact) | > 0.80 | 四分之五规则 |
| 亚组 PR-AUC | 各组均报告 | 区分度是否一致 |
| 亚组 DCA | `subgroup_dca()` | 净效用差异 |

## 分组维度

- race / ethnicity
- gender / sex
- age groups
- 其他临床相关分组

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| Q01 | WARNING | 必须做亚组分析 |
| Q02 | WARNING | 亚组 CI + n<200 标记为不可靠 |

## 注意事项

- 亚组 n < 200 → 标记为不可靠（MLGG-Q02），不做推断
- 如果数据缺少保护属性 → 在报告中声明局限性
- equity gap = max - min 最优净效用

## 完成后告诉用户

```
Phase 8 公平性评估完成:
- 分析亚组: [race, gender, age]
- 均等化优势 gap: X.XX ([通过/需关注])
- 差异影响比: X.XX ([通过/需关注])
- [如有亚组 n<200] 注意: XX 亚组样本不足，结论不可靠
- [如有显著差异] 需在报告中讨论差异原因和局限性
```
