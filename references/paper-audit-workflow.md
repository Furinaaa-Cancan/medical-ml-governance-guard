# Paper Audit End-to-End Workflow

**Version**: 1.0
**Date**: 2026-03-27
**Purpose**: 从"拿到一篇论文"到"产出完整评估报告"的端到端操作指南。

---

## 1. 工作流总览

```
                        ┌──────────────────────────┐
                        │  输入：一篇已发表论文      │
                        │  （PDF + 可选 GitHub URL） │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  Step 1: 创建目录结构     │
                        │  papers/<journal>/<disease>/│
                        │  <author_year_keyword>/    │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  Step 2: 填写 metadata    │
                        │  手动 或 LLM 辅助提取      │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  Step 3: 验证 metadata    │
                        │  参照 validation-rules.md  │
                        └────────────┬─────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                 │
         ┌──────────▼───────┐  ┌────▼────────┐  ┌────▼──────────┐
         │  路径 A:          │  │  路径 C:     │  │  路径 B:       │
         │  元数据评分       │  │  代码扫描    │  │  项目审计      │
         │  score_paper_     │  │  scan_       │  │  audit_        │
         │  metadata.py      │  │  published_  │  │  external_     │
         │                   │  │  repos.py    │  │  project.py    │
         └──────────┬────────┘  └────┬────────┘  └────┬──────────┘
                    │                │                 │
                    └────────────────┼─────────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  Step 4: 交叉比对        │
                        │  metadata vs code 结论    │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  Step 5: 更新 manifest    │
                        │  + 批量审查（可选）        │
                        └──────────────────────────┘
```

---

## 2. 详细步骤

### Step 1: 创建目录结构

**命名规则**：`<first_author_lastname>_<year>_<2-3_keyword>`，全小写，下划线分隔。

```bash
# 示例：Smith et al. 2023, Nature Medicine, 心血管领域, AF 预测
mkdir -p papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction
```

**期刊目录选择**：

| 论文发表期刊 | 放入目录 |
|------------|---------|
| Nature Medicine | `nature_medicine/` |
| Lancet Digital Health | `lancet_digital_health/` |
| JAMA / JAMA Internal Medicine / JAMA Network Open | `jama/` |
| BMJ / BMJ Open | `bmj/` |
| npj Digital Medicine | `npj_digital_medicine/` |
| 其他 | `specialist_journals/` |

**疾病目录选择**：

| 疾病领域 | 目录名 |
|---------|-------|
| 房颤、心衰、心梗、卒中 | `cardiovascular/` |
| 癌症诊断/复发/治疗响应 | `oncology/` |
| 糖尿病诊断/并发症/血糖 | `diabetes/` |
| AKI、CKD、透析 | `kidney_disease/` |
| 脓毒症、ICU 死亡率 | `sepsis_icu/` |
| 痴呆、癫痫、神经退行 | `neurology/` |
| COPD、哮喘、COVID-19 | `respiratory/` |
| 其他感染性疾病 | `infectious_disease/` |
| 以上皆非 | `other/` |

### Step 2: 填写 metadata.json

**复制模板**：

```bash
cp papers/templates/paper_metadata_template.json \
   papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/metadata.json
```

**填写方式**（二选一）：

#### 方式 A：手动填写

阅读论文 Methods 和 Results 部分，按以下顺序填写：

1. `bibliographic` — 从论文首页直接抄录
2. `study_design` — 从 Methods → Study Design 段落提取
3. `dataset` — 从 Methods → Study Population / Data Source 提取
4. `model` — 从 Methods → Model Development 提取
5. `performance_metrics` — 从 Results → Model Performance 表格提取
6. `reporting_standards` — 检查论文是否引用 TRIPOD/PROBAST/STARD
7. `leakage_risk_assessment` — **最关键**：逐项基于 Methods 判断，需特别注意：
   - 预处理是否在 split 之前描述（暗示可能在全量数据上 fit）
   - 是否明确说明 "fitted on training data only"
   - 特征是否包含诊断相关变量（如用诊断码预测同一疾病）

#### 方式 B：LLM 辅助提取（推荐大批量时使用）

```bash
python3 experiments/paper/extract_paper_metadata.py \
  --pmcid PMC12345678 \
  --output papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/metadata.json
```

> **注意**：LLM 提取结果**必须人工校验**，特别是 `leakage_risk_assessment` 部分。LLM 容易将未报告的项目默认标记为 `null` 而非明确的 `false`，而这两者在评分中含义不同。

### Step 3: 验证 metadata

参照 `references/metadata-validation-rules.md` 检查：

**必检项（ERROR 级别）**：
- [ ] 所有数值字段在合理范围内
- [ ] `test_auroc` 在 CI 范围内（P-001）
- [ ] 样本量加和一致（C-001）
- [ ] `tuning_used_test_data` 和 `tuning_set` 不矛盾（L-001, L-002）
- [ ] `split_strategy` 和 `temporal_split_confirmed` 不矛盾（L-003, L-004）

**可疑信号（WARNING 级别）**：
- [ ] AUROC > 0.99 → 极度可疑泄漏（P-003）
- [ ] AUROC > 0.95 且 prevalence < 5% → 可疑（P-004）
- [ ] 高泄漏风险 + 高性能 → 强泄漏嫌疑（L-005）

### Step 4: 运行评分

#### 路径 A：元数据评分（必选）

```bash
# 单篇评分
python3 scripts/score_paper_metadata.py \
  --metadata papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/metadata.json

# 输出到文件
python3 scripts/score_paper_metadata.py \
  --metadata papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/metadata.json \
  --output papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/audit_output/metadata_score.json
```

**输出解读**：
```json
{
  "total_score": 72.5,      // 总分 0-100
  "grade": "Major issues",   // 等级
  "dimensions": {
    "data_integrity": {
      "score": 10.0,         // 该维度得分
      "max": 12,             // 满分
      "fraction": 0.8333,    // 通过率
      "passed": ["split_reported", "train_test_sizes", "test_size", "total_n_reported", "prevalence_reported"],
      "failed": ["temporal_split"]   // 未通过的检查
    }
    // ... 11 个维度
  }
}
```

#### 路径 C：代码扫描（如果论文有公开代码）

```bash
# 扫描单个 GitHub 仓库
python3 experiments/paper/scan_published_repos.py \
  --repo https://github.com/user/repo \
  --output papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/audit_output/code_scan.json
```

**输出关键字段**：
```json
{
  "has_leakage_error": true,              // 是否有 ERROR 级别泄漏
  "leakage_types_found": ["preprocessing_before_split", "scaler_on_test"],
  "rule_counts": {"R001": 2, "R002": 1},  // 各规则触发次数
  "training_file_findings": 3             // 训练文件中的发现数
}
```

#### 路径 B：项目审计（适用于有完整 evidence/ 目录的 MLGG 项目）

```bash
python3 scripts/audit_external_project.py \
  --project-dir /path/to/project \
  --target-journal nature_medicine \
  --output papers/.../audit_output/project_audit.json
```

> **注意**：路径 B 仅适用于使用 MLGG 流程构建的项目（有 evidence/ 目录和 gate reports）。对于外部论文的公开代码仓库，通常使用路径 C。

### Step 5: 交叉比对

将路径 A 和路径 C 的结论放在一起比对：

| 比对维度 | 路径 A (metadata) 说 | 路径 C (code) 说 | 结论 |
|---------|---------------------|-----------------|------|
| 预处理隔离 | `preprocessing_fit_on_train_only = true` | R001 未触发 | ✅ 一致 |
| 预处理隔离 | `preprocessing_fit_on_train_only = true` | R001 触发 2 次 | ❌ **矛盾**：作者声称做了，代码没做 |
| 时间分割 | `temporal_split_confirmed = false` | R008 未触发 | ✅ 一致（都没做） |
| 目标泄漏 | `target_leakage_risk = "low"` | R007 触发 | ❌ **矛盾**：目标变量可能在特征中 |

**矛盾是有价值的发现**——说明论文存在报告不一致，应在审计报告中特别标注。

### Step 6: 更新 manifest（批量审查用）

在对应的 `papers/manifests/batch_manifest_*.json` 的 `projects` 数组中添加：

```json
{
  "id": "smith_2023_af_ehr_prediction",
  "path": "papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction",
  "label": "Smith et al. 2023 — AF prediction from EHR (Nature Medicine)",
  "notes": "External validation on 2 cohorts. R001 detected in code scan."
}
```

---

## 3. 批量审查

### 3.1 批量元数据评分

```bash
python3 scripts/score_paper_metadata.py \
  --batch-dir papers/ \
  --output papers/audit_results/batch_scores.json
```

输出包含：聚合统计（mean/median/std）、维度聚合、泄漏流行率、每篇论文详细评分。

### 3.2 批量代码扫描

```bash
python3 experiments/paper/scan_published_repos.py \
  --manifest experiments/paper/papers_verified_v2.jsonl \
  --output experiments/paper/output/code_audit.json \
  --output-dir experiments/paper/output/code_audit/per_repo
```

### 3.3 批量项目审计

```bash
python3 scripts/batch_journal_review.py \
  --manifest papers/manifests/batch_manifest_nature_medicine.json \
  --target-journal nature_medicine \
  --output papers/audit_results/batch_nature_medicine.json \
  --format markdown \
  --summary-csv papers/audit_results/batch_nature_medicine_summary.csv \
  --workers 4
```

---

## 4. papers/ 与 experiments/paper/ 的关系

| 维度 | `papers/` | `experiments/paper/` |
|------|-----------|---------------------|
| **目的** | 按期刊/疾病组织的论文元数据库 | 系统性综述实验（大规模扫描） |
| **粒度** | 每篇论文有完整 metadata.json（~80 字段） | 每篇论文只有 JSONL 条目（~10 字段）+ 代码扫描结果 |
| **数据量** | 目前 6 篇（精选代表性论文） | 172 篇（PMC 批量收集） |
| **评分** | 12 维 100 分制（精细） | 二值判定（有/无泄漏） |
| **用途** | 框架验证 + 个案深度分析 | 流行率估计 + 统计推断 |
| **交叉** | 可从 experiments/paper/ 中挑选论文深度纳入 papers/ | papers/ 中的论文如有代码也可通过路径 C 扫描 |

**建议工作流**：
1. 先用 `experiments/paper/` 的大规模扫描获取流行率数据
2. 从中挑选代表性论文（高/中/低泄漏风险各取若干）纳入 `papers/`
3. 在 `papers/` 中做精细的 metadata 评分 + 代码扫描交叉验证
4. 用精细评估结果校准大规模扫描的 sensitivity/specificity

---

## 5. 审计报告输出结构

完成一篇论文的审计后，其目录结构应为：

```
papers/nature_medicine/cardiovascular/smith_2023_af_ehr_prediction/
├── paper.pdf                          # PDF 原文（.gitignore 忽略）
├── metadata.json                      # 结构化元数据
└── audit_output/
    ├── metadata_score.json            # 路径 A: 12 维评分
    ├── code_scan.json                 # 路径 C: R001-R020 扫描（如有代码）
    ├── cross_comparison.md            # 交叉比对备注（手动）
    └── audit_report.json              # 路径 B: 项目审计（如适用）
```

---

## 6. 快速参考卡片

```bash
# 1. 新论文入库
mkdir -p papers/<journal>/<disease>/<author_year_keyword>
cp papers/templates/paper_metadata_template.json papers/<...>/metadata.json

# 2. 评分
python3 scripts/score_paper_metadata.py --metadata papers/<...>/metadata.json

# 3. 代码扫描（如有）
python3 experiments/paper/scan_published_repos.py --repo <github_url> --output papers/<...>/audit_output/code_scan.json

# 4. 批量评分
python3 scripts/score_paper_metadata.py --batch-dir papers/ --output papers/audit_results/batch_scores.json

# 5. 批量项目审计
python3 scripts/batch_journal_review.py --manifest papers/manifests/<manifest>.json --output papers/audit_results/<output>.json
```
