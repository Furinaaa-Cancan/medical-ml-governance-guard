---
name: ml-leakage-guard
description: "Publication-grade medical prediction workflow with strict anti-data-leakage controls, phenotype-definition safeguards, lineage-based leakage detection, split-protocol verification, class-imbalance policy validation, hyperparameter-tuning isolation checks, falsification tests, and reproducibility gates. Use when building, reviewing, or debugging disease risk or prognosis models in EHR/claims/registry data, especially when target definitions, diagnosis codes, lab criteria, medications, temporal windows, and derived features can leak target information."
---

# ML Leakage Guard

## ⚠️ Agent 主动引导协议（最高优先级）

**当用户要求建模/预测/训练时，Agent 必须先完成以下检查清单，而非直接运行命令。**
**绝不跳过 Phase 1 的临床审查直接开始训练。**

### 首次交互检查清单

当用户说"帮我预测 X"/"训练模型"/"分析数据"时，Agent 应该按以下顺序主动提问：

```
🔍 第一步：了解研究目标（必须先问，不能假设）
├── "你要预测什么结局？（如：糖尿病、再入院、死亡率）"
├── "你的数据来自哪里？（NHANES/医院 EHR/试验/登记库）"
├── "数据量大约多少行？有多少个特征？"
└── "你有明确的疾病定义吗？还是需要我帮你建立？"

📋 第二步：临床审查（根据第一步答案引导）
├── 如果用户提到具体疾病名称 →
│   读取 references/disease-definition-knowledge-base.json
│   获取该疾病的标准定义模板（ICD 码、实验室标准、药物、排除标准）
│   主动提醒：
│   "⚠️ 你的数据中是否有 [HbA1c/血压/肌酐等] 列？
│    如果这些列用于定义结局，它们不能作为预测特征。
│    这是最常见的数据泄漏类型。"
│
├── 如果数据来自 NHANES/BRFSS/NHIS →
│   主动提醒：
│   "⚠️ 这是复杂抽样设计数据，标准 ML 不使用调查权重。
│    需要在论文 Limitations 中声明。
│    你的数据中有权重列吗？（如 WTMEC2YR）"
│
├── 如果数据量 < 500 →
│   主动提醒：
│   "⚠️ 小样本，Riley 样本量三准则可能不满足。
│    建议先运行 Phase 1 检查，再决定建模策略。
│    小样本应该用 CV-only 模式而非三分法。"
│
└── 如果用户不确定疾病定义 →
    引导走 Phase 1 Agent 引导协议 Step 3 的完整流程
    （5 层证据、裁决策略、排除标准、时间窗）

⚙️ 第三步：数据质量快检（运行 Phase 1 门控）
├── 运行 cohort_definition_gate.py
├── 检查报告中的 warnings/failures
├── 向用户解释每个发现（用通俗语言，不是代码术语）
└── 确认用户理解后再进入 Phase 2

✂️ 第四步：划分策略选择（根据样本量推荐）
├── n > 5000  → "推荐三分法 60/20/20"
├── n 1000-5000 → "推荐两分法 80/20 + CV 替代验证集"
├── n < 1000  → "小样本，推荐 CV-only + Bootstrap 内部验证"
├── 纵向数据  → 加 --temporal-cv 防止时序泄漏
└── 横截面数据 → 加 --cross-sectional 跳过时序检查

🏋️ 第五步以后 → 按 Phase 3-9 正常执行
```

### 关键提醒规则（Agent 必须遵守）

| 场景 | Agent 必须主动说的话 |
|------|-------------------|
| 用户提供的 CSV 中有 `hba1c` 列且要预测糖尿病 | "⚠️ HbA1c 可能是定义糖尿病的变量。如果用它定义了结局，它不能做预测特征。" |
| 用户数据来自 NHANES/BRFSS | "⚠️ 这是调查数据，有抽样权重。标准 ML 不使用权重，需在论文中声明。" |
| 用户数据 < 200 行 | "⚠️ 样本量可能不足。建议先检查 Riley 标准。小样本不应做三分法。" |
| 用户说"直接训练就行" | "在训练之前，我需要先做 Phase 1 队列检查。这是 TRIPOD+AI 和 PROBAST+AI 的要求。大约 30 秒就能完成。" |
| 用户的特征中有 ICD/diagnosis 编码列 | "⚠️ 如果 ICD 编码列包含结局疾病的诊断码，这是定义变量泄漏。需要排除。" |
| 模型训练完成后 | "建议运行鲁棒性压力测试 (robustness_stress_test)，检查模型对异常值和噪声的稳定性。" |
| 评估完成后 | "校准斜率应接近 1.0，截距接近 0。如果偏离较大，建议做 Platt scaling 校准。" |
| 用户代码在某 gate 失败时 | 读取 `references/peer_reviews/peer-review-kb.json`，按失败 gate 名称在 `mlgg_gates` 字段中匹配相关 concerns。告诉用户："X 位 NC 审稿人在 Y 篇论文中指出过相同问题。典型修复方案：..." 并引用具体的 concern_id 和 author_response。 |
| 用户说"审查我的代码"/"帮我 review" | 先识别代码中的问题 category 和 tags，然后读取 peer-review-kb.json 按 tags/category 匹配。引用 top-3 真实审稿意见原文作为论据，格式："[PEER-REVIEW] PR-XXX-CYY: Reviewer 指出 '...' — 作者修复方案：'...'"。 |
| 审稿人/用户问"这种问题常见吗" | 读取 `references/peer_reviews/peer-review-kb-stats.json`，引用统计数据。例如："107 篇 NC 论文中，119/375 (31.7%) 的审稿意见涉及评估指标不完整，其中 missing_calibration 出现 12+ 次。" |

---

## AI 操作指引（Quick Dispatch）

当用户提出请求时，按以下决策树选择操作路径：

### 用户意图 → 操作命令

| 用户说的 | 你该做的 |
|---------|---------|
| "帮我训练一个模型" / "跑一下预测" | `python3 scripts/orchestration/mlgg.py play` — 启动交互向导 |
| "用我的数据训练" / "我有一个 CSV" | `python3 scripts/orchestration/mlgg.py play` → 选"使用自己的数据集" |
| "查看训练结果" / "结果怎么样" | `python3 scripts/tools/quick_summary.py <output_dir>` |
| "下载一个测试数据集" | `python3 examples/download_real_data.py <name>` (heart/breast/pima/mammographic/thyroid/eeg_eye/vitaldb/framingham/diabetes130/diabetes130_full/rhc/sepsis_survival) |
| "下载 CDC 数据集" | `python3 examples/download_cdc_data.py <name>` (brfss/nhis/covid/all) |
| "下载 NHANES 数据集" | `python3 examples/download_nhanes.py --cycles both --output examples/nhanes_diabetes.csv` |
| "下载 NCI 癌症数据" | `python3 examples/download_nci_gdc.py --output examples/nci_gdc_cancer_survival.csv` |
| "审查论文 Methods (Qwen)" | `DASHSCOPE_API_KEY=sk-... python3 experiments/paper/review_methods_llm.py --pmcid PMCxxxxxx` |
| "Methods vs Code 比对" | `python3 experiments/paper/compare_methods_vs_code.py --methods-dir ... --audit-log ... --blind-list ... --output ...` |
| "统计分析" | `python3 experiments/paper/statistical_analysis.py --output experiments/paper/output/statistical_results.json` |
| "过夜批量跑 pipeline" | `nohup bash experiments/overnight_pipeline_run.sh > experiments/overnight_run.log 2>&1 &` |
| "严格审计" / "出版级验证" | `python3 scripts/orchestration/mlgg.py workflow --strict` |
| "检查环境" / "安装有问题" | `python3 scripts/orchestration/mlgg.py doctor` |
| "初始化项目" | `python3 scripts/orchestration/mlgg.py onboarding` |
| "对比两次运行" | `python3 scripts/tools/compare_runs.py --run-a <dir1> --run-b <dir2>` |
| "生成修复计划" | `python3 scripts/tools/remediation_plan.py --evidence-dir <dir>` |
| "解释某个 gate 失败" | `python3 scripts/tools/explain_gate.py --report <gate_report.json>` |
| "检查代码是否有数据泄漏" | `python3 scripts/orchestration/mlgg.py lint check <file.py>` |
| "检查代码（JSON 给 agent）" | `python3 scripts/orchestration/mlgg.py lint check <file.py> --format json` |
| "检查代码（CI 门控）" | `python3 scripts/orchestration/mlgg.py lint check <dir> --exit-code` |
| "SHAP 可解释性" / "特征重要性" | `python3 scripts/gates/shap_interpretability_gate.py --model-pool evidence/model_pool.pkl --train-data data/train.csv --test-data data/test.csv --target-col y --report evidence/shap_interpretability_report.json` |
| "数据探索" / "样本量够不够" / "EPV" | `python3 scripts/gates/cohort_definition_gate.py --data data.csv --target-col y --id-col patient_id --report evidence/cohort_report.json` |
| "横截面数据" / "survey 数据" / "NHANES" | `python3 scripts/tools/split_data.py --input data.csv --strategy stratified_grouped --cross-sectional --patient-id-col patient_id --target-col y --output-dir data/` |
| "校准怎么样" / "calibration slope" | 查看 `calibration_metrics()` in `_gate_utils.py`：校准截距/斜率/O:E/ECE/Hosmer-Lemeshow/Brier Skill Score |
| "NRI IDI" / "模型比较改善" | 调用 `compute_nri_idi(y_true, y_old, y_new)` in `_gate_utils.py`：分类 NRI、连续 NRI、IDI |
| "学习曲线" / "数据量够不够" | 调用 `learning_curve_data(estimator, X_train, y_train, X_test, y_test)` in `_gate_utils.py` |
| "VIF" / "共线性" / "多重共线性" | 调用 `compute_vif(X, feature_names)` in `_gate_utils.py`：VIF>5 警告，>10 严重 |
| "非线性" / "线性假设" / "spline" | 调用 `check_nonlinearity(X, y, feature_names)` in `_gate_utils.py`：LR test + BH FDR 校正（默认）|
| "MNAR" / "缺失不随机" / "敏感性分析" | 调用 `mnar_sensitivity_analysis(...)` in `_gate_utils.py`：δ-adjustment + tipping point |
| "时序漂移" / "校准漂移" / "concept drift" | 调用 `temporal_drift_analysis(y_true, y_score, times)` in `_gate_utils.py`：CUSUM 检测 |
| "Model Card" / "模型文档" | 调用 `generate_model_card(...)` in `_gate_utils.py`：自动生成 Markdown |
| "插补敏感性" / "换插补方法" | 调用 `imputation_sensitivity(X_raw, y, estimator, features)` in `_gate_utils.py` |
| "亚组 DCA" / "公平性净效用" | 调用 `subgroup_dca(y_true, y_score, groups)` in `_gate_utils.py`：equity gap |
| "baseline 对比" / "比随机好多少" | 调用 `baseline_comparisons(y_true, y_score, y_pred)` in `_gate_utils.py`：AUROC over random + BSS |
| "消融实验" / "ablation" / "去掉特征" | 调用 `feature_ablation(estimator, X_train, y_train, X_test, y_test, features)` in `_gate_utils.py` |
| "训练时间" / "计算资源" / "硬件" | 调用 `compute_resource_report(t0, t1, model_name, n_train, n_features)` in `_gate_utils.py` |
| "查看 lint 规则列表" | `python3 scripts/orchestration/mlgg.py lint rules` |
| "评审一篇论文（从 metadata）" | `python3 scripts/tools/score_paper_metadata.py --metadata <metadata.json>` |
| "批量评审论文" | `python3 scripts/tools/score_paper_metadata.py --batch-dir papers/` |
| "从 PMC 收集有代码的论文" | `python3 experiments/paper/collect_papers_with_code.py --output <out.jsonl>` |
| "验证论文 repo 质量" | `python3 experiments/paper/verify_repos.py --input <in.jsonl> --output <out.jsonl>` |
| "批量扫描论文代码泄漏" | `python3 experiments/paper/scan_published_repos.py --manifest <verified.jsonl> --output <out.json>` |
| "这种问题审稿人会怎么看？" | 读取 peer-review-kb.json 按问题 tags 匹配，返回同行审稿人的原始意见和作者修复方案。 |
| "NC 审稿人通常要求什么？" | 读取 peer-review-kb-stats.json，返回统计摘要：top 类别、severity 分布、最常见 tags。 |
| "查找相关审稿案例" | 按用户描述的问题在 peer-review-kb.json 中按 dimension/category/tags 匹配，返回 top-3 案例。 |
| "这个 gate 以前抓过什么？" | 在 peer-review-kb.json 中按 mlgg_gates 字段匹配，展示该 gate 关联的真实审稿案例。 |

### Peer Review Evidence-Based Review（始终激活）

Agent 审查代码时，**必须**查阅 `references/peer_reviews/peer-review-kb.json`（107 篇 NC 论文，375 条结构化审稿意见）和 `references/peer_reviews/peer-review-kb-stats.json`（统计摘要）。

> **核心原则**：每一条审查建议都应尽可能引用真实同行评审案例作为论据，而非仅凭规则输出。
> 审稿人的原话比规则更有说服力——"NC Reviewer #2 在类似论文中指出了完全相同的问题"。

#### 知识库结构

peer-review-kb.json 中每条 concern 包含：
- `concern_id`：唯一标识（PR-XXX-CYY）
- `category`：问题类别（evaluation_metrics / study_design / reporting / preprocessing / ...）
- `severity`：CRITICAL / HIGH / MEDIUM / LOW
- `mlgg_dimension`：MLGG 12 维度编号（1-12）
- `mlgg_gates`：关联的 gate 脚本列表
- `tags`：语义标签列表（missing_calibration / temporal_leakage / no_external_validation / ...）
- `concern_text`：审稿人原文
- `author_response`：作者修复方案
- `_paper_id` / `_year` / `_domain`：论文信息

#### 检索策略

Agent 根据当前场景选择检索维度：

| 场景 | 检索字段 | 示例 |
|------|----------|------|
| Gate 失败 | `mlgg_gates` 包含该 gate | leakage_gate → 找所有被这个 gate 捕获的案例 |
| 发现具体问题 | `tags` 匹配 | 发现缺校准 → tags=["missing_calibration"] |
| Phase checkpoint | `mlgg_dimension` 匹配 | Phase 3 完成 → dimension=3 (Pipeline Isolation) |
| 领域相关 | `_domain` 匹配 | 用户做癌症预测 → domain="oncology" |
| 严重度过滤 | `severity` 过滤 | 只看 CRITICAL 级问题 |

#### 引用格式

```
[PEER-REVIEW] PR-XXX-CYY (Nature Communications, 20XX)
  审稿人指出: "..."
  作者修复: "..."
  维度: X | Gate: xxx_gate | 标签: [...]
  KB 中类似问题: N/375 (X%)
```

#### 统计引用

当建议某个改进时，引用 peer-review-kb-stats.json 中的数据增强说服力：
- "107 篇 NC 论文中，119/375 (31.7%) 的审稿意见要求完善评估指标"
- "25 条 CRITICAL 级问题中，最常见的是数据泄漏(3)和结局定义错误(5)"
- "只报 AUC 不报校准是 NC 审稿人最常提出的 HIGH 级问题（出现 12+ 次）"
- "81/375 (21.6%) 的意见涉及研究设计——审稿人最关心队列定义和结局变量"

#### 辅助 CLI（供用户手动查询）

```bash
python3 scripts/tools/peer_review_lookup.py --stats
python3 scripts/tools/peer_review_lookup.py --dimension 5 --severity HIGH
python3 scripts/tools/peer_review_lookup.py --gate leakage_gate
python3 scripts/tools/peer_review_lookup.py --tags "missing_calibration,no_dca"
python3 scripts/tools/peer_review_lookup.py --category evaluation_metrics --limit 3
```

### 五条常用命令（覆盖 90% 场景）

```bash
# 1. 新手一键体验（推荐入口）
python3 scripts/orchestration/mlgg.py play

# 2. 快速查看结果
python3 scripts/tools/quick_summary.py ~/Desktop/MLGG_Output/breast_cancer

# 3. 下载真实数据集
python3 examples/download_real_data.py breast --output /tmp/breast.csv

# 4. 严格出版级流程
python3 scripts/orchestration/mlgg.py onboarding && python3 scripts/orchestration/mlgg.py workflow --strict

# 5. 环境诊断
python3 scripts/orchestration/mlgg.py doctor
```

### 添加新数据集的操作步骤

1. 在 `examples/download_real_data.py` 的 `URLS` 字典中添加下载 URL
2. 创建 `prepare_<name>()` 函数（参考现有函数格式）
3. 调用 `add_patient_id_and_time(df, seed=N)`（种子必须唯一）
4. 输出列顺序：`patient_id, event_time, y, features...`
5. 添加到 `PREPARE` 字典和 CLI `choices`
6. 在 `scripts/orchestration/mlgg_pixel.py` 中添加 i18n 字符串 + `PLAY_DOWNLOAD_DATASETS` 条目
7. 测试：`python3 examples/download_real_data.py <name> --output /tmp/test.csv`

### 添加新模型族的操作步骤

修改 `scripts/tools/train_select_evaluate.py` 的 5 个位置：
1. `SUPPORTED_MODEL_FAMILIES` 集合
2. `_family_grid()` — 超参数网格
3. `_build_estimator_for_family()` — Pipeline 构建
4. `_family_base_complexity()` — 复杂度排名
5. `_family_friendly_name()` — 显示名称

修改 `scripts/orchestration/mlgg_pixel.py` 的 4 个位置：
6. `MODEL_POOL` 列表
7. `BASE_FAMILY_GRID_SIZES` 字典
8. `_T` i18n 字符串
9. `MODEL_PROFILE_PRESETS`（balanced/comprehensive）

### 添加新 Gate 的操作步骤

所有 gate 脚本必须遵循统一 CLI 契约：

1. **CLI 参数**：使用 `add_common_arguments(parser)` 或手动添加 `--report`、`--strict`、`--timeout`
2. **计时**：入口调用 `start_gate_timer()`
3. **报告输出**：使用 `build_report_envelope()` 生成标准信封格式
4. **终端输出**：使用 `print_gate_summary()` 打印结构化摘要
5. **退出逻辑**：`should_fail = bool(failures) or (args.strict and bool(warnings))`，返回 `2 if should_fail else 0`
6. **注册**：在 `_gate_registry.py` 中注册 gate 名称和路径
7. **无需手动同步 gate 列表**：以下工具脚本已从 `_gate_registry.py` 动态获取 gate 列表，添加新 gate 后自动生效：
   - `scripts/tools/report_health_check.py` → `EXPECTED_REPORTS`
   - `scripts/tools/remediation_plan.py` → `GATE_ORDER`
   - `scripts/tools/evidence_digest.py` → `gate_files`
   - `scripts/tools/compare_runs.py` → `REPORT_FILES`
   - 仍需手动更新：`scripts/tools/render_user_summary.py` → `DEFAULT_GATE_FILES`（仅展示子集）、`scripts/orchestration/run_strict_pipeline.py` → `gate_script_inputs`（manifest 指纹）
8. **测试**：在 `tests/` 中创建对应测试文件，覆盖率 ≥85%

**严禁**：
- 自定义 strict-mode 逻辑（如 `warning_is_blocking()` 过滤器）
- 跳过 `--strict` 对 warnings 的影响
- 手动提升 warnings 到 failures 列表（应由 `should_fail` 逻辑统一处理）

### 添加新 Lint 规则 (R0xx) 的操作步骤

1. 在 `plugin/mlgg_lint/rules/` 创建 `r0xx_rule_name.py`，继承 `BaseRule`
2. 设置 `id`、`name`、`severity`、`description`、`remediation`、`tags`
3. 在 `plugin/tests/samples/` 创建 `r0xx_bad.py`（触发诊断）和 `r0xx_good.py`（无诊断）
4. 在 `plugin/tests/test_engine.py` 添加 `test_r0xx_bad_has_diagnostics()` 和 `test_r0xx_good_no_r0xx()`
5. 运行 `python3 -m pytest plugin/tests/test_engine.py -v` 验证

**规则实现清单**：每个新规则合并前必须同时提供 bad + good 测试样本。

### 常见错误恢复

| 错误信息 | 根因 | 修复 |
|---------|------|------|
| `Unsupported model family` | 新模型未加到 `SUPPORTED_MODEL_FAMILIES` | 更新白名单（见上方 5 个位置） |
| `candidate_pool_too_small` | 候选模型少于 3 个 | 增加模型族或提高 `--max-trials-per-family` |
| `NaN to integer` | numpy 整数数组赋 NaN | 用 `DataFrame.loc[mask, col] = np.nan` |
| 训练超时（>20min） | 大数据集 + 多模型 + bootstrap | 减少模型数/trials/用保守预设 |
| `FileNotFoundError` | 路径错误或前序步骤未执行 | 检查 `data/` 目录下 CSV 是否存在 |
| R001 FP on utility files | 文件中无 train_test_split 但有 fit() | R001 已修复：skip_line is None 时跳过 (ERR-089) |
| R005 FP on unused thresholds | roc_curve 单变量捕获但未用 result[2] | R005 已修复：检查 index-2 access (ERR-090) |
| 空 metadata 通过验证 | validate_metadata({}) 返回 0 issues | 已修复：添加 REQUIRED 字段检查 (ERR-092) |
| BRFSS ZIP 文件名有空格 | CDC ZIP 中文件名尾部有空格 | 已修复：.strip() 处理 (ERR-098) |
| NCI GDC disease_type 是 list | API 返回 list 而非 string | 已修复：取 [0] 或 default (ERR-097) |

### 可用数据集清单（14 个，526K 行）

| 数据集 | 行数 | 来源 | 下载命令 | Gate 覆盖 |
|--------|------|------|---------|----------|
| Sepsis Survival | 129K | UCI | `download_real_data.py sepsis_survival` | C (39%) |
| Diabetes 130 Full | 102K | UCI | `download_real_data.py diabetes130_full` | A (94%) |
| BRFSS 2022 | 100K | CDC | `download_cdc_data.py brfss` | B (81%) |
| COVID-19 | 100K | CDC | `download_cdc_data.py covid` | C (39%) |
| NHIS 2022 | 28K | CDC | `download_cdc_data.py nhis` | A (94%) |
| NCI GDC Cancer | 25K | NCI/NIH | `download_nci_gdc.py` | A (94%) |
| NHANES | 16K | CDC | `download_nhanes.py --cycles both` | A (94%) |
| SUPPORT2 | 9K | Vanderbilt | 已下载 | A (94%) |
| RHC | 5.7K | Vanderbilt | `download_real_data.py rhc` | A (94%) |
| 4 × UCI 小型 | <1K | UCI | `download_real_data.py heart/breast/pima/ckd` | B (68-84%) |

Gate 覆盖: A=29/31可测, B=21-26/31, C=12/31。详见 `references/dataset-gate-coverage-matrix.md`。

### Gate 严格性 Profile

| Profile | 适用场景 | EPV 下限 | 最小事件数 | L3 可达？ |
|---------|---------|---------|-----------|----------|
| `standard` | N≥1000, 患病率≥10% | 10 | 100 | ✅ |
| `small_cohort` | N=200-1000 | 7 | 50 | ⚠️ 需注明 |
| `rare_disease` | N<200, 患病率<5% | 5 | 20 | ❌ |
| `exploratory` | 可行性研究 | 5 | 20 | ❌ |

在 `request.json` 中指定: `"thresholds": {"profile": "rare_disease"}`。详见 `references/gate-strictness-profiles.md`。

### 数据泄漏 & 学术诚信检测覆盖

本项目的 33 道 gate 覆盖以下学术诚信风险：

**数据泄漏检测（4 道 gate）**：
- `leakage_gate`: 行级重叠、患者 ID 重叠、时序穿越（训练数据晚于测试数据）
- `split_protocol_gate`: 分割协议验证（患者不重叠、时序有序、种子锁定）
- `definition_variable_guard`: 表型定义中的未来信息泄漏（用未来事件定义当前标签）
- `feature_lineage_gate`: 特征来源链路追溯（特征是否包含标签信息或未来数据）

**调优泄漏 / p-hacking（3 道 gate）**：
- `tuning_leakage_gate`: 超参搜索是否使用了测试数据、模型选择数据源验证
- `model_selection_audit_gate`: 候选池大小、选择标准、是否存在选择偏倚
- `evaluation_quality_gate`: 主指标是否有 CI、是否优于基线（防止挑选性报告）

**过拟合 & 泛化性（4 道 gate）**：
- `generalization_gap_gate`: train-test 性能差距是否超过阈值
- `covariate_shift_gate`: 训练/测试特征分布是否漂移
- `robustness_gate`: 时间切片和分组的性能稳健性
- `seed_stability_gate`: 不同随机种子下结果是否稳定

**统计严谨性（3 道 gate）**：
- `permutation_significance_gate`: 置换检验 p-value（模型是否优于随机）
- `ci_matrix_gate`: Bootstrap CI 完整性（所有指标都有置信区间）
- `prediction_replay_gate`: 预测结果是否可精确重现（防止结果篡改）

**临床有效性 & 报告完整性（3 道 gate）**：
- `calibration_dca_gate`: 概率校准质量 + 决策曲线分析
- `reporting_bias_gate`: TRIPOD+AI / PROBAST+AI / STARD-AI 清单合规
- `clinical_metrics_gate`: 混淆矩阵一致性、完整临床指标面板

**出版级聚合（2 道 gate）**：
- `publication_gate`: 聚合所有 gate 结果 + 执行签名验证
- `self_critique_gate`: 全局质量评分 + 审稿人级自我批评

### 缺失值插补 & Pipeline 隔离

**缺失值处理**（`train_select_evaluate.py`）：
- `SimpleImputer`（默认）：中位数填充 + 缺失指示器列
- `IterativeImputer` (MICE)：多重迭代插补（`--imputation-strategy mice`）
- 插补器在 sklearn Pipeline 内部，**只在训练集上 fit**，验证/测试集只做 transform
- 特征过滤阈值：strict 模式丢弃缺失率 >60% 的特征

**Pipeline 隔离保证**：
每个候选模型的 Pipeline 结构为 `imputer → scaler → classifier`：
- imputer 的统计量（中位数/参数）只从训练集计算
- scaler 的均值/标准差只从训练集计算
- classifier 只在训练集上拟合
- 验证/测试集只做 transform + predict，不影响任何参数

**超参数搜索隔离**（由 `tuning_leakage_gate` 强制检查）：
- `model_selection_data`: 只允许 `valid` / `cv_inner` / `nested_cv`（禁止 `test`）
- `early_stopping_data`: 只允许 `none` / `valid` / `cv_inner`（禁止 `test`）
- `preprocessing_fit_scope`: 必须是 `train_only`
- `feature_selection_scope`: 必须是 `train_only`
- `final_model_refit_scope`: 只允许 `train_only` / `train_plus_valid_no_test`

以上全部是 fail-closed 检查——违反任何一条即判定失败。

### 安全加固（Security Hardening）

本项目内置多层防御机制，覆盖以下攻击面：

**模型工件安全**：
- HMAC-SHA256 签名：训练完成后自动对 `.pkl` 文件生成签名（`.pkl.sig`）
- 安全加载：`SecureModelLoader` 在反序列化前验证签名，拒绝加载被篡改的模型
- 大小限制：模型文件超过 500MB 自动拒绝（防止 zip bomb 攻击）

**证据完整性**：
- 训练结束自动生成 SHA256 清单（`.manifest.json`），记录每个证据文件的哈希值和大小
- 可随时验证：`python3 scripts/core/_security.py audit evidence/`
- 检测篡改、缺失、敏感数据暴露

**输入验证**：
- `safe_path()` / `resolve_path()`: 路径穿越防护（null byte 注入、`..` 逃逸、系统目录封锁、沙箱 `Path.relative_to()` 强制检查）
- `safe_load_json()`: JSON 大小限制（100MB）+ 嵌套深度限制（50层）防止栈溢出/内存耗尽
- `check_csv_row_limit()`: CSV 行数限制防止内存耗尽 DoS

**密码学安全**：
- 所有 HMAC/签名比较必须使用 `hmac.compare_digest()`（常量时间比较，防止计时攻击）
- 禁止使用 `==` / `!=` 进行任何密码学值比较

**隐私防护**：
- `perturb_predictions()`: Laplace 机制扰动预测概率，防御成员推理攻击
- 敏感数据扫描：审计工具自动扫描证据文件中的 API key / password / token / PEM 私钥 / 医疗标识符（MRN/insurance_id）等

**供应链验证**：
- `verify_critical_imports()`: 运行时验证 sklearn/numpy/pandas 是否为真实库（非 monkey-patch）
- `.mlgg_model_key` 自动生成、权限 600、已加入 `.gitignore`

**CLI 工具**：`python3 scripts/core/_security.py [sign|verify|manifest|audit|check-deps]`

### 能力边界

**能做的**：
- 表格型医学二分类预测（EHR/临床/注册数据）
- 自动防泄漏分割 + 模型训练 + 评估 + 出版级审计
- 9 个真实数据集 + 自定义 CSV（支持中文列名）
- 20 个 sklearn 模型族 + 4 个可选后端
- 安全加固：HMAC 签名 + 证据清单 + 路径穿越防护 + 成员推理防御

**做不了的**：
- 图像/文本/时序等非表格数据
- 多分类/回归任务（仅二分类）
- 深度学习模型（TabNet/Transformer 等）
- 模型部署/API serving
- 交互式可视化 dashboard

---

## Objective (Goal Clarity)
Solve one narrow problem: produce leakage-safe, publication-grade medical prediction evidence.

Success is binary:
- `pass`: all hard gates pass and self-critique score reaches threshold.
- `fail`: any hard gate fails or strict review conditions are not met.

Never produce publication-grade claims without machine-checkable evidence artifacts.

## Input Contract (Structured Input)
Accept a structured request JSON, not free-form text.

Data input modes:
- **Pre-split mode**: user provides separate train/valid/test CSV files.
- **Single-file mode**: user provides one complete CSV; use `scripts/tools/split_data.py` to auto-split with patient-level disjoint, temporal ordering, and prevalence checks. The interactive wizard (`mlgg interactive --command train`) and onboarding (`mlgg onboarding --input-csv`) support this mode natively.

Required fields:
- `study_id`
- `run_id`
- `target_name`
- `prediction_unit`
- `index_time_col`
- `label_col`
- `patient_id_col`
- `primary_metric`
- `claim_tier_target` (`leakage-audited` or `publication-grade`)
- `phenotype_definition_spec`
- `split_paths.train`
- `split_paths.test`

Publication-grade required fields:
- `feature_lineage_spec`
- `feature_group_spec`
- `split_protocol_spec`
- `imbalance_policy_spec`
- `missingness_policy_spec`
- `tuning_protocol_spec`
- `performance_policy_spec`
- `reporting_bias_checklist_spec`
- `execution_attestation_spec`
- `model_selection_report_file`
- `feature_engineering_report_file`
- `distribution_report_file`
- `robustness_report_file`
- `seed_sensitivity_report_file`
- `evaluation_report_file`
- `prediction_trace_file`
- `external_cohort_spec`
- `external_validation_report_file`
- `ci_matrix_report_file`
- `evaluation_metric_path`
- `permutation_null_metrics_file`
- `actual_primary_metric`
- `primary_metric` must be `pr_auc` for publication-grade strict mode.
- `evaluation_metric_path` terminal token must match `primary_metric` (after normalization).

Optional threshold keys under `thresholds`:
- `alpha` and `min_delta` for permutation significance gate.
- `min_baseline_delta`, `ci_min_resamples`, and `ci_max_width` for evaluation quality gate.

Path semantics:
- All relative paths in request JSON are resolved relative to the request file directory.

Template:
- `references/request-schema.example.json`
- `references/feature-lineage.example.json`
- `references/split-protocol.example.json`
- `references/imbalance-policy.example.json`
- `references/missingness-policy.example.json`
- `references/tuning-protocol.example.json`
- `references/performance-policy.example.json`
- `references/external-cohort-spec.example.json`
- `references/reporting-bias-checklist.example.json`
- `references/execution-attestation.example.json`
- `references/attestation-payload.example.json`
- `references/key-revocations.example.json`
- `references/attestation-timestamp-record.example.json`
- `references/attestation-transparency-record.example.json`
- `references/attestation-execution-receipt-record.example.json`
- `references/attestation-execution-log-record.example.json`
- `references/attestation-witness-record.example.json`
- `references/evaluation-report.example.json`
- `references/external-validation-report.example.json`
- `references/prediction-trace.example.csv`

Validate request first:

```bash
python3 scripts/gates/request_contract_gate.py \
  --request configs/request.json \
  --report evidence/request_contract_report.json \
  --strict
```

## Hidden Workflow (Internal, Fail-Closed)
Use this internal sequence in order:
1. Validate request contract.
2. Lock data/config fingerprints (`manifest_lock.py`).
3. Run execution attestation gate (`execution_attestation_gate.py`).
4. Run split/time leakage gate (`leakage_gate.py`).
5. Run split protocol gate (`split_protocol_gate.py`).
6. Run covariate-shift gate (`covariate_shift_gate.py`).
7. Run reporting/bias checklist gate (`reporting_bias_gate.py`).
8. Run phenotype-definition leakage gate (`definition_variable_guard.py`).
9. Run lineage leakage gate (`feature_lineage_gate.py`).
10. Run imbalance policy gate (`imbalance_policy_gate.py`).
11. Run missingness policy gate (`missingness_policy_gate.py`).
12. Run tuning leakage gate (`tuning_leakage_gate.py`).
13. Run model-selection audit gate (`model_selection_audit_gate.py`).
14. Run feature-engineering audit gate (`feature_engineering_audit_gate.py`).
15. Run clinical-metrics gate (`clinical_metrics_gate.py`).
16. Run prediction-replay gate (`prediction_replay_gate.py`).
17. Run distribution-generalization gate (`distribution_generalization_gate.py`).
18. Run generalization-gap gate (`generalization_gap_gate.py`).
19. Run robustness gate (`robustness_gate.py`).
20. Run seed-stability gate (`seed_stability_gate.py`).
21. Run external-validation gate (`external_validation_gate.py`).
22. Run calibration+DCA gate (`calibration_dca_gate.py`).
23. Run CI-matrix gate (`ci_matrix_gate.py`).
24. Run metric consistency gate (`metric_consistency_gate.py`).
25. Run evaluation quality gate (`evaluation_quality_gate.py`).
26. Run permutation falsification gate (`permutation_significance_gate.py`).
27. Aggregate publication gate (`publication_gate.py`).
28. Run self-critique scoring gate (`self_critique_gate.py`).
29. Run security audit gate (`security_audit_gate.py`).
30. Run fairness & equity gate (`fairness_equity_gate.py`).
31. Run sample size adequacy gate (`sample_size_gate.py`).
32. Emit final report only if all strict gates pass.

Treat execution-attestation failures (signature/fingerprint/key-revocation/timestamp/transparency/execution-receipt/execution-log/witness-quorum/cross-role-authority-distinctness), disease-definition leakage, lineage ambiguity, metric-source ambiguity, split protocol violations, covariate-shift anomalies, class-imbalance misuse, missingness/imputation misuse, and tuning/test leakage as critical failures in strict mode.

## Output Contract (Machine-Parseable)
Produce these deterministic artifacts:
1. `evidence/request_contract_report.json`
2. `evidence/manifest.json`
3. `evidence/execution_attestation_report.json`
4. `evidence/reporting_bias_report.json`
5. `evidence/leakage_report.json`
6. `evidence/split_protocol_report.json`
7. `evidence/covariate_shift_report.json`
8. `evidence/definition_guard_report.json`
9. `evidence/lineage_report.json`
10. `evidence/imbalance_policy_report.json`
11. `evidence/missingness_policy_report.json`
12. `evidence/tuning_leakage_report.json`
13. `evidence/model_selection_audit_report.json`
14. `evidence/feature_engineering_audit_report.json`
15. `evidence/clinical_metrics_report.json`
16. `evidence/prediction_replay_report.json`
17. `evidence/distribution_generalization_report.json`
18. `evidence/generalization_gap_report.json`
19. `evidence/robustness_gate_report.json`
20. `evidence/seed_stability_report.json`
21. `evidence/external_validation_gate_report.json`
22. `evidence/calibration_dca_report.json`
23. `evidence/ci_matrix_gate_report.json`
24. `evidence/metric_consistency_report.json`
25. `evidence/evaluation_quality_report.json`
26. `evidence/permutation_report.json`
27. `evidence/publication_gate_report.json`
28. `evidence/self_critique_report.json`
29. `evidence/security_audit_gate_report.json`
30. `evidence/fairness_equity_report.json`
31. `evidence/sample_size_report.json`
32. `evidence/dag_pipeline_report.json`

Report status from each file must be machine-readable (`pass` or `fail`) with issue codes.

## Quality Control (Self-Critique)
Do not stop at initial gate pass.
Run `self_critique_gate.py` to score evidence quality and produce recommendations.

Publication-grade readiness requires:
- Strict-mode component reports.
- No blocking failures.
- Self-critique score at or above threshold (default `95`).

## Composability (Workflow Node Ready)
Each script is a composable node:
- Deterministic CLI interface.
- Deterministic JSON output.
- Deterministic exit code (`0` pass, `2` fail).

Use one-command orchestration for production use:

```bash
python3 scripts/orchestration/run_strict_pipeline.py \
  --request configs/request.json \
  --evidence-dir evidence \
  --compare-manifest evidence/manifest_baseline.json \
  --strict
```

Productized one-command wrapper:

```bash
python3 scripts/orchestration/run_productized_workflow.py \
  --request configs/request.json \
  --evidence-dir evidence \
  --allow-missing-compare \
  --strict
```

Novice onboarding wrapper (guided 8-step flow):

```bash
python3 scripts/orchestration/mlgg.py onboarding \
  --project-root /tmp/mlgg_demo \
  --mode guided \
  --yes
```

Onboarding contract:
- `scripts/orchestration/mlgg_onboarding.py` is strict-only (no policy downgrade path).
- Failure behavior:
  - default `--stop-on-fail` (fail-fast)
  - optional `--no-stop-on-fail` (collect full diagnostics while keeping fail-closed result)
  - guided mode without interactive stdin fails closed with `onboarding_interactive_input_unavailable` (use `--yes` or `--mode auto`)
  - wrapper route-conflict failure code: `authority_preset_route_override_forbidden`
- Modes:
  - `guided`: step-by-step command preview + confirmation.
  - `preview`: print the full 8-step command plan only; report includes `preview_only=true` and `display_status=preview`.
  - `auto`: execute all steps non-interactively.
- Step order is fixed:
  1. `env_doctor.py`
  2. `init_project.py`
  3. `generate_demo_medical_dataset.py`
  4. config alignment to demo schema (`request/lineage/group/external spec`)
  5. `train_select_evaluate.py`
  6. `generate_execution_attestation.py` (+ keypair bootstrap if needed)
  7. `run_productized_workflow.py --strict --allow-missing-compare`
  8. `run_productized_workflow.py --strict --compare-manifest ...`
- Required report:
  - `evidence/onboarding_report.json` (`contract_version=onboarding_report.v2`)
  - report fields include `stop_on_fail`, `termination_reason`, `failure_codes`, `next_actions`, `copy_ready_commands`, `preview_only`, `display_status`
  - `copy_ready_commands` uses absolute `mlgg.py` path so commands are runnable from any working directory.
- Offline demo data artifacts:
  - `data/train.csv`, `data/valid.csv`, `data/test.csv`
  - `data/external_2025_q4.csv` (`cross_period`)
  - `data/external_site_b.csv` (`cross_institution`)

This wrapper runs:
1. `env_doctor.py`
2. `schema_preflight.py`
3. `run_strict_pipeline.py`
4. `render_user_summary.py`

For first-run baseline bootstrap, you may omit `--compare-manifest` only with:
- `--allow-missing-compare`
- `run_strict_pipeline.py` always enforces `--strict` for publication-grade execution.
- `--allow-missing-compare` is bootstrap-only for artifact generation; publication-grade readiness still fails until baseline manifest comparison exists.
- `run_strict_pipeline.py` is publication-grade only; non-publication claim tiers are rejected.

## Personal UX Quickstart (Signed Attestation)
Create keypair once:

```bash
mkdir -p keys
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/attestation_priv.pem
openssl pkey -in keys/attestation_priv.pem -pubout -out keys/attestation_pub.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/timestamp_priv.pem
openssl pkey -in keys/timestamp_priv.pem -pubout -out keys/timestamp_pub.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/execution_priv.pem
openssl pkey -in keys/execution_priv.pem -pubout -out keys/execution_pub.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/execution_log_priv.pem
openssl pkey -in keys/execution_log_priv.pem -pubout -out keys/execution_log_pub.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/witness_a_priv.pem
openssl pkey -in keys/witness_a_priv.pem -pubout -out keys/witness_a_pub.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/witness_b_priv.pem
openssl pkey -in keys/witness_b_priv.pem -pubout -out keys/witness_b_pub.pem
```

Generate payload + signature + spec in one command:

```bash
python3 scripts/tools/generate_execution_attestation.py \
  --study-id sepsis-risk-icu-v1 \
  --run-id sepsis-risk-icu-v1-train-2026-02-24-001 \
  --payload-out evidence/attestation_payload.json \
  --signature-out evidence/attestation.sig \
  --spec-out configs/execution_attestation.json \
  --private-key-file keys/attestation_priv.pem \
  --public-key-file keys/attestation_pub.pem \
  --timestamp-private-key-file keys/timestamp_priv.pem \
  --timestamp-public-key-file keys/timestamp_pub.pem \
  --execution-private-key-file keys/execution_priv.pem \
  --execution-public-key-file keys/execution_pub.pem \
  --execution-log-private-key-file keys/execution_log_priv.pem \
  --execution-log-public-key-file keys/execution_log_pub.pem \
  --require-independent-timestamp-authority \
  --require-independent-execution-authority \
  --require-independent-log-authority \
  --require-witness-quorum \
  --min-witness-count 2 \
  --require-independent-witness-keys \
  --require-witness-independence-from-signing \
  --witness "witness-a|keys/witness_a_pub.pem|keys/witness_a_priv.pem" \
  --witness "witness-b|keys/witness_b_pub.pem|keys/witness_b_priv.pem" \
  --command "python train.py --config configs/train_config.json --seed 42" \
  --artifact training_log=evidence/train.log \
  --artifact training_config=configs/train_config.json \
  --artifact model_artifact=models/model_v1.bin \
  --artifact evaluation_report=evidence/evaluation_report.json \
  --artifact prediction_trace=evidence/prediction_trace.csv.gz \
  --artifact external_validation_report=evidence/external_validation_report.json
```

This command also creates:
- `configs/key_revocations.json` (bootstrapped if missing)
- `evidence/attestation_timestamp_record.json` + `.sig`
- `evidence/attestation_transparency_record.json` + `.sig`
- `evidence/attestation_execution_receipt_record.json` + `.sig`
- `evidence/attestation_execution_log_record.json` + `.sig`
- `evidence/attestation_witness_record_1.json` + `.sig`
- `evidence/attestation_witness_record_2.json` + `.sig`

## Manual Strict Execution Order
If orchestration is unavailable, run in this exact order:
1. `request_contract_gate.py`
2. `manifest_lock.py` (with optional `--compare-with`)
3. `execution_attestation_gate.py`
4. `leakage_gate.py`
5. `split_protocol_gate.py`
6. `covariate_shift_gate.py`
7. `reporting_bias_gate.py`
8. `definition_variable_guard.py`
9. `feature_lineage_gate.py`
10. `imbalance_policy_gate.py`
11. `missingness_policy_gate.py`
12. `tuning_leakage_gate.py`
13. `model_selection_audit_gate.py`
14. `feature_engineering_audit_gate.py`
15. `clinical_metrics_gate.py`
16. `prediction_replay_gate.py`
17. `distribution_generalization_gate.py`
18. `generalization_gap_gate.py`
19. `robustness_gate.py`
20. `seed_stability_gate.py`
21. `external_validation_gate.py`
22. `calibration_dca_gate.py`
23. `ci_matrix_gate.py`
24. `metric_consistency_gate.py`
25. `evaluation_quality_gate.py`
26. `permutation_significance_gate.py`
27. `publication_gate.py`
28. `self_critique_gate.py`
29. `security_audit_gate.py`
30. `fairness_equity_gate.py`
31. `sample_size_gate.py`

Note: Steps 30-31 run in METRIC_VALIDATION layer (parallel with steps 16-26 in DAG mode). In manual sequential mode, run them after step 29 to ensure all dependencies are available.

If any step returns non-zero, stop and block claim release.

## Medical Non-Negotiable Rules
- Never tune on test data.
- Never fit preprocessors on combined train+validation+test.
- Never apply resampling/SMOTE on validation or test splits.
- Never select thresholds or calibrate probabilities on test split.
- Never fit imputers on validation/test distributions.
- Never use target/outcome information for feature imputation.
- Never run MICE at oversized scale without audited fallback evidence (`mice_with_scale_guard`).
- Never ignore severe train-vs-holdout distribution separability without explicit mitigation and downgrade.
- Never perform model ranking/selection with any test-derived signal.
- Never release without full split-level clinical metrics (accuracy/precision/PPV/NPV/sensitivity/specificity/F1/F2-beta/ROC-AUC/PR-AUC/Brier).
- Never ignore train/valid/test gap breaches beyond configured fail thresholds.
- Never claim publication-grade without signed execution attestation proving run command, timing, and artifact hashes.
- Never reuse revoked/expired/over-age signing keys for publication-grade claims.
- Never omit trusted timestamp or transparency-log records for publication-grade claims.
- Never omit signed execution-receipt proof (with exit code and timing consistency) for publication-grade claims.
- Never omit signed execution-log attestation binding `training_log` to payload hash for publication-grade claims.
- Never omit witness-quorum evidence with independent witness keys and minimum validated witness count for publication-grade claims.
- Never claim publication-grade if TRIPOD+AI/PROBAST+AI checklist has unmet required items.
- Never accept publication-grade primary metrics from non-test evaluation splits; evaluation report must explicitly declare `split=test`.
- Never claim publication-grade without valid primary-metric confidence interval and explicit baseline comparison in the evaluation artifact.
- Never include variables used to define the disease label as model predictors.
- Never include derived features whose lineage contains disease-defining variables.
- Never include post-index features for pre-index prediction tasks.
- Never report point estimates without uncertainty and robustness checks.
- Never claim causality from predictive associations.
- Never publish subgroup predictions without fairness/equity assessment (equalized odds, disparate impact).
- Never claim adequate sample size without EPV ≥ 10 justification (Riley et al. 2019).
- Never omit IDI/NRI when comparing against baseline models for top-tier journals.
- Never use ICD diagnostic codes from the same admission as predictors without verifying temporal precedence.
- Never claim TRIPOD+AI adherence without the 2024 expanded 27-item checklist (BMJ 2024;385:e078378).

## Resources

### scripts/
- `scripts/orchestration/run_strict_pipeline.py`: single-entry strict orchestrator.
- `scripts/gates/request_contract_gate.py`: request schema/path validation and publication-policy anti-downgrade checks.
- `scripts/orchestration/mlgg.py`: unified command entrypoint (`onboarding`, `interactive`, `init`, `train`, `workflow`, ...).
- `scripts/orchestration/mlgg_onboarding.py`: novice-guided strict onboarding flow and report emitter.
- `scripts/tools/split_data.py`: split a single CSV into train/valid/test with patient-level disjoint, temporal ordering, prevalence safety checks, NaN patient_id/target exclusion, row count preservation, SHA256 input fingerprint, min 10 pos/neg per split, min 5 patients per split, and prevalence shift warning.
- `scripts/tools/generate_demo_medical_dataset.py`: offline reproducible demo dataset generator.
- `scripts/gates/manifest_lock.py`: dataset/protocol/evaluation/gate-script fingerprint and baseline comparison.
- `scripts/gates/execution_attestation_gate.py`: signed run-attestation and artifact-hash verification gate.
- `scripts/tools/generate_execution_attestation.py`: one-command payload/signature/spec/timestamp/transparency/execution-receipt/execution-log/witness-quorum generator for personal users.
- `scripts/gates/reporting_bias_gate.py`: TRIPOD+AI / PROBAST+AI / STARD-AI checklist hard gate.
- `scripts/gates/leakage_gate.py`: split contamination, ID overlap, and temporal boundary checks.
- `scripts/gates/split_protocol_gate.py`: enforce split protocol consistency and temporal/group safeguards.
- `scripts/gates/covariate_shift_gate.py`: train-vs-holdout covariate-shift and split separability risk gate.
- `scripts/gates/definition_variable_guard.py`: hard gate against disease-definition variable leakage.
- `scripts/gates/feature_lineage_gate.py`: hard gate against lineage-derived leakage.
- `scripts/gates/imbalance_policy_gate.py`: validate class-imbalance strategy and train-only resampling policy.
- `scripts/gates/missingness_policy_gate.py`: validate missing-data strategy, large-scale method suitability, and imputer isolation policy.
- `scripts/gates/tuning_leakage_gate.py`: validate hyperparameter tuning/test-isolation protocol.
- `scripts/gates/model_selection_audit_gate.py`: validate candidate pool, one-SE replay, and test-isolated model selection.
- `scripts/gates/feature_engineering_audit_gate.py`: validate feature-group provenance, train-only engineering scope, stability evidence, and reproducibility fields.
- `scripts/gates/clinical_metrics_gate.py`: validate clinical metric completeness and confusion-matrix consistency per split.
- `scripts/gates/distribution_generalization_gate.py`: train-vs-holdout distribution shift, split separability, and transport-readiness gate.
- `scripts/gates/generalization_gap_gate.py`: fail-closed overfitting gap checks across train/valid/test.
- `scripts/gates/ci_matrix_gate.py`: bootstrap CI matrix gate for primary metric and transport-drop CI on internal and external cohorts.
- `scripts/gates/metric_consistency_gate.py`: extract and validate metric from evaluation report.
- `scripts/gates/evaluation_quality_gate.py`: enforce primary-metric CI quality and baseline improvement checks.
- `scripts/gates/permutation_significance_gate.py`: falsification significance gate.
- `scripts/gates/publication_gate.py`: aggregate fail-closed publication gate.
- `scripts/gates/self_critique_gate.py`: quality scoring and reviewer-grade self-critique gate.
- `scripts/tools/train_select_evaluate.py`: terminal-ready training, model selection, threshold selection, and evaluation artifact generator.
- `scripts/tools/train_select_evaluate.py` model-pool controls: `--model-pool`, `--include-optional-models`, `--max-trials-per-family`, `--hyperparam-search`, `--n-jobs`.
- `scripts/tools/train_select_evaluate.py` optional model backends: `xgboost` and `catboost` are auto-detected and fail-closed when explicitly requested but unavailable.
- `scripts/tools/init_project.py`: one-command initialization for `configs/`, `data/`, `evidence/`, `models/`, `keys/`, plus `configs/request.json`.
- `scripts/tools/schema_preflight.py`: train/valid/test schema checks with semantic column auto-mapping report.
- `scripts/tools/env_doctor.py`: dependency and environment diagnostics with optional-backend checks.
- `scripts/tools/render_user_summary.py`: user-facing markdown/json summary from strict evidence artifacts.
- `scripts/orchestration/run_productized_workflow.py`: full UX wrapper (doctor -> preflight -> strict pipeline -> user summary).
- `scripts/orchestration/mlgg_interactive.py`: terminal interactive wizard for core commands (`init/workflow/train/authority`) with command preview, confirm-before-run, and profile save/load.
- `scripts/orchestration/mlgg_pixel.py`: pixel-art interactive CLI wizard (`mlgg.py play`) for guided pipeline setup and execution with bilingual (en/zh) support, dataset-size-aware defaults, small-sample strict mode, and play-mode quick-readiness card.
- `scripts/core/_gate_utils.py`: shared utility functions (`add_issue`, `load_json`, `write_json`, `to_float`) for gate scripts.
- `scripts/core/_security.py`: security hardening module — HMAC model signing, path traversal protection, secure JSON loading, artifact integrity manifest, membership inference defense, dependency verification, security audit CLI.
- `scripts/gates/security_audit_gate.py`: 29th pipeline gate (FINAL layer) — verifies model HMAC signatures, evidence manifest integrity, dependency authenticity, file permissions, sensitive data exposure, artifact sizes.
- `scripts/gates/fairness_equity_gate.py`: 30th pipeline gate (METRIC_VALIDATION layer) — equalized odds gap across demographic/clinical subgroups, disparate impact ratio (four-fifths rule), per-subgroup PR-AUC validation.
- `scripts/gates/sample_size_gate.py`: 31st pipeline gate (METRIC_VALIDATION layer) — EPV (Riley et al. 2019/2025), shrinkage factor, minimum events/non-events adequacy.
- `scripts/tools/policy_generator.py`: generate recommended `performance_policy.json` from evidence reports with configurable margin and presets.
- `scripts/tools/gate_timeline.py`: analyze gate execution timeline, identify bottleneck gates, compute wall-clock span.
- `scripts/tools/gate_coverage_matrix.py`: scan evidence directory against full gate registry to produce coverage matrix.
- `scripts/tools/evidence_comparator.py`: compare two evidence directories side-by-side showing improved/regressed/new/removed gates.
- `scripts/tools/evidence_digest.py`: generate compact one-page summary from evidence directory.
- `scripts/tools/report_health_check.py`: scan all gate reports for completeness and pass rate.
- `scripts/tools/remediation_plan.py`: generate prioritized remediation plan from gate failures.
- `scripts/tools/threshold_sensitivity.py`: analyze how close metrics sit to pass/fail thresholds.
- `scripts/tools/compare_runs.py`: compare two pipeline runs side-by-side.
- `scripts/tools/export_latex.py`: generate LaTeX tables from evaluation/CI/model-selection reports.
- `scripts/tools/explain_gate.py`: explain a single gate result in human-readable form.
- `scripts/tools/quick_summary.py`: one-command training results viewer with key metrics, overfitting risk, model selection top-10.
- `scripts/tools/audit_external_project.py`: 10-dimension quantitative audit tool for evaluating medical ML projects (100-point scale) with journal-specific gap analysis.
- `scripts/gates/fairness_equity_gate.py`: fail-closed fairness and equity gate — equalized odds gap, disparate impact ratio (four-fifths rule), per-subgroup PR-AUC validation.
- `scripts/gates/sample_size_gate.py`: fail-closed sample size adequacy gate — EPV (Riley et al. 2019/2025), shrinkage factor, min events/non-events.
- `scripts/tools/batch_journal_review.py`: batch audit N projects in parallel with comparison matrix, cross-cutting analysis, and aggregated remediation priorities.
- `experiments/authority-e2e/scan_stress_diabetes_feasibility.py`: stress-case diabetes feasibility scanner across target modes and row caps; outputs a fail-closed feasibility report.

### plugin/
- `plugin/mlgg_lint/`: AST-based static analysis for ML Python code (10 rules: R001–R010, 57 tests).
- R001 fit-before-split (ERROR), R002 scaler-on-test (ERROR), R003 resample-on-test (ERROR), R004 split-without-group (WARNING), R005 threshold-on-test (ERROR), R006 feature-selection-on-full (ERROR), R007 target-as-feature (ERROR), R008 temporal-split-shuffle (WARNING), R009 no-confidence-intervals (INFO), R010 train-metric-as-final (WARNING).
- Detection: keyword args (`fit(X=X_test)`), chained calls (`SMOTE().fit_resample()`), DataFrame origin tracking + `.drop()` re-assignment, Pipeline exclusion, word-boundary variable classification.
- CLI: `python3 scripts/orchestration/mlgg.py lint check [--format text|json|sarif] [--exit-code] [--severity warning] [--disable R004,R008] PATH...`
- Supports `# noqa: R001` / `# noqa` inline suppression and `.mlgg-lint.toml` config auto-discovery.
- Output: relative paths (no absolute path leakage), ANSI-stripped in no-color mode.
- Security: 16 MB file limit, 1 MB config limit, symlink skip, stat-error handling, malformed TOML graceful fallback.
- VS Code extension at `plugin/vscode/` (SARIF-based diagnostics on save/open).
- Pre-commit hook at `plugin/.pre-commit-hooks.yaml`.

### examples/
- `examples/download_real_data.py`: download and prepare 9 real medical datasets (UCI/PhysioNet/GitHub) + 2 synthetic generators.
  - Real datasets: heart(297), breast(569), pima(768), mammographic(961), framingham(4240), vitaldb(6388), thyroid(7200), diabetes130(10000), eeg_eye(14980).
  - All produce pipeline-ready CSV with `patient_id`, `event_time`, `y` columns.

### tests/
- `tests/`: 2905+ pytest unit tests covering all gate scripts and analysis tools.
  - Direct `main()` tests for 20+ gate scripts (bypass subprocess for in-process coverage).
  - All gate modules ≥86% coverage; publication_gate 97%, evaluation_quality_gate 94%.
  - Run: `python3 -m pytest tests/ -q --tb=short` (~10 min for full suite).

### references/
- `references/Beginner-Quickstart.md`: bilingual novice quickstart (minimal loop + publication-grade loop).
- `references/Troubleshooting-Top20.md`: high-frequency failure code to diagnosis/fix/verify mapping.
- `references/request-schema.example.json`: structured request template.
- `references/feature-lineage.example.json`: lineage map template.
- `references/split-protocol.example.json`: split protocol template.
- `references/imbalance-policy.example.json`: class-imbalance policy template.
- `references/missingness-policy.example.json`: missing-data/imputation policy template.
- `references/tuning-protocol.example.json`: hyperparameter tuning protocol template.
- `references/performance-policy.example.json`: metric panel/threshold/gap policy template.
- `references/reporting-bias-checklist.example.json`: TRIPOD+AI / PROBAST+AI / STARD-AI checklist template.
- `references/execution-attestation.example.json`: signed execution-attestation spec template.
- `references/attestation-payload.example.json`: signed payload template with artifact hashes.
- `references/key-revocations.example.json`: key revocation list template.
- `references/attestation-timestamp-record.example.json`: trusted timestamp record template.
- `references/attestation-transparency-record.example.json`: transparency log record template.
- `references/attestation-execution-receipt-record.example.json`: execution receipt record template.
- `references/attestation-execution-log-record.example.json`: execution-log attestation record template.
- `references/attestation-witness-record.example.json`: witness attestation record template.
- `references/feature-group-spec.example.json`: feature group specification template (groups, train-only scope).
- `references/feature-engineering-report.example.json`: feature-engineering audit report template.
- `references/distribution-report.example.json`: distribution/shift report template.
- `references/ci-matrix-report.example.json`: CI matrix report template.
- `references/external-validation-report.example.json`: external validation report template.
- `references/evaluation-report.example.json`: evaluation metrics report template.
- `references/interactive-profile.example.json`: interactive CLI profile contract example (`contract_version/command/saved_at_utc/argument_values/python/cwd`).
- `references/benchmark-registry.json`: frozen benchmark dataset registry (contract `benchmark_registry.v1`).
- `references/stress-seed-search-report.v2.example.json`: stress seed/profile search contract template.
- `references/medical-disease-leakage.md`: medical phenotype leakage patterns and controls.
- `references/leakage-taxonomy.md`: leakage classes, red flags, and mitigations.
- `references/top-tier-rigor-checklist.md`: submission-grade hard gates.
- `references/external-benchmark-comparison.md`: external tool/guideline comparison and gap map.
- `references/release-benchmark-suite.md`: structured benchmark profile matrix and pass contract.
- `references/report-template.md`: reporting template for methods/results/robustness.
- `references/error-knowledge-base.json`: self-improving error pattern database with 25 known patterns, agent-appendable.
- `references/journal-rigor-standards.json`: top-tier journal requirements mapped to gates (Nature Medicine, Lancet DH, JAMA, BMJ, npj DM).
- `references/literature-knowledge-base.json`: curated top-journal literature database (30 entries, LIT-001–LIT-030), searchable by category/gate/dimension.
- `references/mlgg-review-standard.json`: independent MLGG Medical ML Review Standard — 10 dimensions × 73 criteria across 3 review levels (quick/standard/comprehensive).
- `references/batch-manifest.example.json`: batch manifest template for multi-project review.

## Authority E2E Execution Notes
- Recommended single-entry CLI:
  - `python3 scripts/orchestration/mlgg.py <command> [command-args]`
  - Examples:
    - `python3 scripts/orchestration/mlgg.py init --project-root /tmp/mlgg_demo`
    - `python3 scripts/orchestration/mlgg.py train --interactive`
    - `python3 scripts/orchestration/mlgg.py interactive --command workflow --profile-name demo --save-profile`
    - `python3 scripts/orchestration/mlgg.py workflow --request /tmp/mlgg_demo/configs/request.json --strict --allow-missing-compare`
    - `python3 scripts/orchestration/mlgg.py authority --include-stress-cases`
    - `python3 scripts/orchestration/mlgg.py benchmark-suite --profile release` (recommended multi-dataset stability verdict)
    - `python3 scripts/orchestration/mlgg.py benchmark-suite --profile release --repeat 3 --registry-file references/benchmark-registry.json`
    - `python3 scripts/orchestration/mlgg.py authority-release` (recommended release stress path)
    - `python3 scripts/orchestration/mlgg.py authority-research-heart --stress-seed-min 20250003 --stress-seed-max 20250060` (research/high-pressure mode)
    - preset wrappers are fixed-route; conflicting route flags are rejected fail-closed
    - add `--error-json` for machine-readable failures (`contract_version=mlgg_error.v1`)

- New-user order of operations:
  - `init` -> place split CSVs -> `train` (emit required evidence artifacts) -> `workflow --strict --allow-missing-compare`.
  - Follow-up reproducible runs should pass `--compare-manifest <project>/evidence/manifest_baseline.bootstrap.json`.

- Interactive wizard defaults:
  - Supports `init/workflow/train/authority`.
  - Preview command before execution, then require one confirm step.
  - Train wizard defaults `--include-optional-models` to off; enable manually only when optional backends are installed.
  - Train wizard defaults `--n-jobs` to `1` for cross-platform stability; increase manually for multi-core runs.
  - Train wizard default artifact outputs are auto-scoped to split project base (`<project>/evidence`) inferred from train split path.
  - Train wizard emits `--external-validation-report-out` only when `external_cohort_spec` is provided.
  - Train wizard emits `--feature-engineering-report-out` only when `feature_group_spec` is provided.
  - Profile reuse:
    - `--profile-name <name> --save-profile`
    - `--profile-name <name> --load-profile`
    - `--accept-defaults` for non-blocking execution with defaults/profile values
  - Profile path defaults to `~/.mlgg/profiles` (override with `--profile-dir`).
  - For workflow wizard, `--strict` is always injected and cannot be bypassed by interactive mode.
  - Workflow wizard first-run default enables `--allow-missing-compare` when no baseline manifest is provided/found.
  - Workflow wizard now auto-suggests evidence output under request project base (`<project>/evidence` when request is under `configs/`).
  - Authority wizard now defaults to release-grade stress path (`--include-stress-cases --stress-case-id uci-chronic-kidney-disease`);
    selecting `uci-heart-disease` is treated as advanced research/high-pressure mode.

- Use isolated output paths in concurrent runs:
  - `--summary-file`
  - `--stress-seed-cache-file`
  - `--stress-selection-file`
- Optional benchmark case switches:
  - `--include-ckd-case` (UCI Chronic Kidney Disease)
  - `--include-large-cases` (Diabetes130 large-cohort path)
  - `--diabetes-target-mode {lt30,gt30,any}` and `--diabetes-max-rows`
- Stress dataset selection:
  - `--stress-case-id {uci-diabetes-130-readmission,uci-heart-disease,uci-chronic-kidney-disease,uci-breast-cancer-wdbc}`
  - default is `uci-chronic-kidney-disease` (most stable publication-grade stress path in current benchmark set)
- Release benchmark blocking suites are `authority_release_core` + `adversarial_fail_closed`; `authority_release_extended` (Diabetes130) is kept as observational/non-blocking in release profile.
- Non-blocking authority failures are summarized as `observational_diagnostics` in matrix report and written to `*.observational_diagnostics.json` sidecar.
- Case-specific training configuration is enabled in authority E2E:
  - larger cohorts (e.g., Diabetes130) use expanded model pool (includes `xgboost` when installed), higher `max-trials-per-family`, and multi-core `--n-jobs`.
- Use `--run-tag` to bind all generated stress artifacts to a unique execution token.
- Stress seed-search profile bundles are selected with `--stress-profile-set` (default `strict_v1`).
- `--stress-seed-search` applies only to `--stress-case-id uci-heart-disease`; other stress cases run without seed search.
- CI coverage:
  - `.github/workflows/ci-smoke.yml` (push/PR/workflow_dispatch)
  - `.github/workflows/ci-full.yml` (nightly/workflow_dispatch release blocking benchmark-suite)
  - `.github/workflows/ci-extended.yml` (weekly/workflow_dispatch extended observational benchmark-suite)
- Optional diabetes feasibility auto-scan on failure:
  - `--auto-scan-diabetes-feasibility`
  - `--diabetes-feasibility-target-modes`
  - `--diabetes-feasibility-max-rows-options`
  - `--diabetes-feasibility-summary-dir`
  - `--diabetes-feasibility-report-file`
- Summary rows now include strict-pipeline root-cause fields for failed cases:
  - `root_failure_code_primary`
  - `root_failure_codes`
  - `failed_steps`
- Summary rows now also include `clinical_floor_gap_summary` with internal/external floor margins
  (`observed - required_min`) for `sensitivity/npv/specificity/ppv`.
- `stress_seed_search_report` v2 contract requires:
  - `contract_version`
  - `run_tag`
  - `policy_sha256`
  - `search_profile_set`
  - `selected_profile`
  - `dataset_fingerprint`
  - `code_revision_hint`

## Deep Review Fix Log

### Session 1 (Fixes applied to request_contract_gate.py, train_select_evaluate.py)

**Fix 1 — `request_contract_gate.py`: wrong error code in `validate_feature_engineering_report_shape`**
- The `except` block for JSON parse failure used `feature_group_spec_missing_or_invalid` instead of `feature_engineering_report_invalid`.
- Fixed: error code now correctly reflects `feature_engineering_report_invalid`.

**Fix 2 — `train_select_evaluate.py`: misleading hard-coded CI bounds in `transport_drop_ci`**
- `ci_95` and `ci_width` in the transport drop block were hard-coded to `[0.0, 0.0]` / `0.0`, falsely implying CIs were bootstrapped.
- Fixed: replaced with `null` and added `ci_note: "not_computed_point_estimate_only"`.
- Verified: `ci_matrix_gate.py` independently recomputes these CIs from prediction traces; downstream not affected.

### Session 2 (Fixes applied to feature_engineering_audit_gate.py, generalization_gap_gate.py, robustness_gate.py, seed_stability_gate.py)

**Fix 3 — `feature_engineering_audit_gate.py`: wrong error code for `feature_engineering_report` parse failure**
- Mirror of Fix 1: the `except` block used `feature_group_spec_missing_or_invalid` when parsing `feature_engineering_report` JSON.
- Fixed: error code now correctly set to `feature_engineering_report_invalid`.

**Fix 4 — `feature_engineering_audit_gate.py`: `to_float` missing `math.isfinite` guard**
- `to_float` accepted `inf` and `nan` as valid float values, inconsistent with all other gate scripts.
- Fixed: added `math.isfinite` guard and added `import math`.

**Fix 5 — `generalization_gap_gate.py`: `finish()` ignored `--strict` for warning escalation**
- `should_fail = bool(failures)` silently swallowed warnings even in strict mode.
- Fixed: `should_fail = bool(failures) or (args.strict and bool(warnings))`.

**Fix 6 — `robustness_gate.py`: same strict-mode bug as Fix 5**
- Fixed: `should_fail = bool(failures) or (args.strict and bool(warnings))`.

**Fix 7 — `seed_stability_gate.py`: same strict-mode bug as Fix 5**
- Fixed: `should_fail = bool(failures) or (args.strict and bool(warnings))`.

### Verified clean (no bugs found)
- `execution_attestation_gate.py`: `finish()` already correct; all validation logic and key/timestamp/transparency/receipt/log/witness-quorum checks are robust.
- `generalization_gap_gate.py`: `to_float` already had `math.isfinite`.
- All 27 gate scripts now uniformly use `bool(failures) or (args.strict and bool(warnings))` in `finish()`.
- All 11 `to_float` implementations across gate scripts now reject `inf`/`nan`.

## Agent Skill Protocol (Agent 技能协议)

本节定义 AI Agent 如何使用本项目作为 skill 快速构建和审计医疗 ML 项目。

### 三种操作模式

#### 模式 A：从零构建科研项目 (Build)
当用户说"帮我做一个预测模型"或"build a medical prediction project"时：

**标准化 8 步流程**：
```
Step 1: 环境检查     → python3 scripts/orchestration/mlgg.py doctor
Step 2: 项目初始化   → python3 scripts/orchestration/mlgg.py init --project-root <dir>
Step 3: 数据准备     → 下载数据集或放入用户数据，用 split_data.py 分割
Step 4: 配置对齐     → 确保 request.json + 所有 spec 文件正确
Step 5: 模型训练     → python3 scripts/orchestration/mlgg.py train ...
Step 6: 执行认证     → python3 scripts/tools/generate_execution_attestation.py ...
Step 7: 严格审计     → python3 scripts/orchestration/mlgg.py workflow --strict
Step 8: 质量报告     → python3 scripts/tools/quick_summary.py + python3 scripts/tools/audit_external_project.py
```

**Agent 决策点**：
- Step 3 数据不足 (<100行)？→ 警告并建议更大数据集
- Step 5 候选模型不足？→ 自动扩大 model-pool
- Step 7 某个 gate 失败？→ 查询 `references/error-knowledge-base.json` 定位修复方案
- Step 8 得分 <90？→ 生成 remediation_plan 并逐项修复

#### 模式 B：审计他人项目 (Audit)
当用户说"帮我审查这个项目"或"review this ML project"时：

```bash
# 1. 量化评分
python3 scripts/tools/audit_external_project.py --project-dir <dir> --target-journal nature_medicine --json

# 2. 如果已有 evidence 目录，运行完整 gate
python3 scripts/tools/report_health_check.py --evidence-dir <dir>/evidence

# 3. 生成修复计划
python3 scripts/tools/remediation_plan.py --evidence-dir <dir>/evidence
```

**审计输出**：12 维度量化评分 (满分100) + 期刊差距分析 + 优先修复清单

#### 模式 C：增量修复 (Fix)
当某个 gate 失败时：

```
1. 读取 gate report JSON → 提取 failure codes
2. 在 references/error-knowledge-base.json 中查找 → 获取修复方案
3. 如果找不到 → 诊断根因 → 应用修复 → 追加到 error-knowledge-base.json
4. 重跑失败的 gate → 验证通过
5. 重跑 publication_gate → 验证全链路通过
```

#### 模式 D：LLM 评审 Skill（零部署，带自己的 LLM）
当用户说"帮我生成评审 prompt"、"我想用 ChatGPT/Gemini 评审" 或 "export review prompt"时：

```bash
# 1. 快速红线检查 prompt（18条，粘贴到任意 LLM）
python3 scripts/tools/export_review_prompt.py --level quick --output review_prompt_quick.md

# 2. 标准评审 prompt（53条）
python3 scripts/tools/export_review_prompt.py --level standard --output review_prompt.md

# 3. 顶刊级 prompt，附 Nature Medicine 特定要求
python3 scripts/tools/export_review_prompt.py --level comprehensive \
  --journal nature_medicine --output review_prompt_nm.md

# 4. JSON 格式（适合 API 调用）
python3 scripts/tools/export_review_prompt.py --level standard --format json \
  --journal jama --output review_payload.json

# 5. 附文献引用
python3 scripts/tools/export_review_prompt.py --level comprehensive \
  --include-literature --output review_with_refs.md
```

用法：将生成的 `.md` 文件内容粘贴到任意 LLM 对话框（Claude、GPT-4、Gemini 均可），然后粘贴论文 PDF 的文字内容，LLM 将输出结构化 JSON 评分报告。

**支持的期刊** `--journal` 参数：`nature_medicine` · `jama` · `lancet_digital_health` · `bmj` · `npj_digital_medicine`

#### 模式 E：批量评审 (Batch Review)
当用户说"帮我批量评审"或"review these projects"时：

```bash
# 1. 准备评审清单 (参考 references/batch-manifest.example.json)
# 2. 运行批量评审
python3 scripts/orchestration/mlgg.py batch-review \
  --manifest batch_manifest.json \
  --target-journal nature_medicine \
  --workers 4 \
  --format json \
  --output batch_report.json

# 3. 可选：输出 CSV 摘要
python3 scripts/orchestration/mlgg.py batch-review \
  --manifest batch_manifest.json \
  --summary-csv batch_summary.csv
```

**批量评审输出**：
- 对比矩阵：每个项目的 12 维度评分 + 总分 + 等级
- 跨项目分析：最常失败的维度 + 最普遍的差距
- 聚合修复优先级：去重后按严重性 × 影响项目数排序

**文献检索协议**：
- 查询 `references/literature-knowledge-base.json`（30 条顶刊文献）
- 按类别 (`category`)、实现的门控 (`gates_implementing`)、影响维度 (`dimensions_affected`) 搜索
- 在评审报告中引用 `LIT-NNN` 编号
- 新增文献须符合：IF>10 期刊 / EQUATOR 指南 / PRISMA 系统评价

### 12 维度量化评分标准 (100分制)

用于量化评判任何医疗 ML 项目的质量：

| # | 维度 | 权重 | 评分要点 |
|---|------|------|---------|
| 1 | 数据完整性 | 12 | Split 隔离、患者级不重叠、时序有序、无行重叠 |
| 2 | 防泄漏 | 15 | 无目标泄漏、无定义变量泄漏、无谱系泄漏、无未来特征 |
| 3 | 流水线隔离 | 12 | 预处理器仅在训练集 fit、插补器隔离、重采样仅在训练集 |
| 4 | 模型选择严谨性 | 10 | 候选池≥3、one-SE 规则、不窥探测试集、有基线比较 |
| 5 | 统计有效性 | 12 | Bootstrap CI、置换检验、校准、DCA、指标一致性 |
| 6 | 泛化证据 | 10 | Train-test gap、外部队列、Transport-drop CI、种子稳定性 |
| 7 | 临床完整性 | 7 | 完整指标面板、混淆矩阵一致性、阈值可行性 |
| 8 | 报告标准 | 7 | TRIPOD+AI、PROBAST+AI、STARD-AI、排除标准文档、局限性文档 |
| 9 | 可重复性 | 6 | 种子记录、版本追踪、执行认证、清单锁定 |
| 10 | 安全与溯源 | 3 | 模型签名、工件完整性、敏感数据保护 |
| 11 | 公平性与公正 | 3 | 均等化优势差距、差异影响比率、亚组性能最低标准 |
| 12 | 样本量充分性 | 3 | EPV≥10、收缩因子≥0.90、最小事件/非事件数≥100 |

**评分解读**：
- 90-100: 顶刊级 (Publication-grade) — 可直接投稿 Nature Medicine / Lancet DH / JAMA / BMJ
- 75-89: 有基础但需补充 (Solid but gaps) — 需要补充特定维度
- 60-74: 重大缺陷 (Major issues) — 需要系统性修复
- <60: 不可发表 (Not publishable) — 需要重新设计

### 顶刊级标准映射

各顶级期刊的核心要求已映射到本框架的 gate：
- 详见 `references/journal-rigor-standards.json`
- 支持期刊：Nature Medicine, Lancet Digital Health, JAMA, BMJ, npj Digital Medicine
- Agent 可自动运行差距分析：`audit_external_project.py --target-journal <name>`

### 自改进错误知识库协议

本项目维护一个结构化的错误模式数据库 (`references/error-knowledge-base.json`)：

**Agent 操作规范**：
1. 遇到新错误 → 先查知识库是否已有记录
2. 已有记录 → 按 `fix` 字段操作 → 验证修复
3. 未找到 → 诊断根因 → 应用修复 → 验证 → 追加新条目（ERR-NNN 格式）
4. 提交：`git commit -m "knowledge-base: add ERR-NNN <description>"`

**条目结构**：
```json
{
  "id": "ERR-NNN",
  "code": "error_code_string",
  "symptom": "用户看到的症状",
  "root_cause": "根因分析",
  "fix": "具体修复步骤",
  "prevention": "如何预防此类问题",
  "category": "data|leakage|pipeline|model|gate|config|environment|attestation|security|statistical",
  "severity": "CRITICAL|ERROR|WARNING|INFO",
  "affected_files": ["file1.py"],
  "first_seen": "YYYY-MM",
  "resolved": true
}
```

### Agent 快速参考卡

```
┌─────────────────────────────────────────────────────────────┐
│  ML Leakage Guard — Agent Quick Reference                   │
├─────────────────────────────────────────────────────────────┤
│  构建新项目:  python3 scripts/orchestration/mlgg.py onboarding --mode auto│
│  审计项目:    python3 scripts/tools/audit_external_project.py     │
│  错误查询:    references/error-knowledge-base.json          │
│  期刊标准:    references/journal-rigor-standards.json       │
│  修复计划:    python3 scripts/tools/remediation_plan.py           │
│  健康检查:    python3 scripts/tools/report_health_check.py        │
│  证据对比:    python3 scripts/tools/evidence_comparator.py        │
│  阈值敏感:    python3 scripts/tools/threshold_sensitivity.py      │
│  LaTeX导出:   python3 scripts/tools/export_latex.py               │
├─────────────────────────────────────────────────────────────┤
│  评分工具:    audit_external_project.py --target-journal X  │
│  支持期刊:    nature_medicine | lancet_digital_health |     │
│               jama | bmj | npj_digital_medicine             │
├─────────────────────────────────────────────────────────────┤
│  Gate 失败?   1. 读报告 2. 查知识库 3. 修复 4. 重跑         │
│  得分 <90?    1. 运行 remediation_plan 2. 逐项修复          │
│  新增错误?    追加到 error-knowledge-base.json               │
└─────────────────────────────────────────────────────────────┘
```

### 标准化交付物清单 (Publication-Ready Deliverables)

Agent 完成完整流程后应产出以下交付物：

```
<project>/
├── data/
│   ├── train.csv, valid.csv, test.csv          # 分割后数据
│   └── external_*.csv                          # 外部验证队列
├── configs/
│   ├── request.json                            # 实验请求合同
│   ├── execution_attestation.json              # 执行认证规范
│   └── *.json                                  # 各类 spec 文件
├── evidence/
│   ├── *_report.json (×33)                     # 33 个 gate 报告
│   ├── manifest.json                           # SHA256 工件清单
│   ├── prediction_trace.csv.gz                 # 行级预测追踪
│   ├── evaluation_report.json                  # 评估指标报告
│   ├── model_selection_report.json             # 模型选择报告
│   └── audit_report.json                       # 12维量化审计报告
├── models/
│   ├── model.pkl + model.pkl.sig               # 签名模型工件
│   └── .mlgg_model_key                         # HMAC 密钥
├── keys/
│   └── *.pem                                   # 认证密钥对
└── results/
    ├── summary.md                              # 人类可读摘要
    └── tables.tex                              # LaTeX 表格
```

---

## 方法论快速参考

### Phase 1 Agent 引导协议

当用户说"帮我分析数据"/"我有一个 CSV"/"开始建模"时，Agent 必须按以下顺序**逐步引导**，不要跳过任何步骤。每步收集到答案后构建 `cohort_definition_gate.py` 的参数。

**Step 1: 基本信息确认**
```
问: 你的数据文件路径是什么？
问: 目标变量（要预测的结局）是哪一列？
问: 患者/个体 ID 列是哪一列？（如果没有，我会为你生成）
```
→ 得到 `--data`, `--target-col`, `--id-col`

**Step 2: 数据来源与抽样设计**
```
问: 这个数据来自哪里？
  a) 公共调查数据库（NHANES / BRFSS / NHIS / MEPS）→ 有复杂抽样设计
  b) 医院 EHR / 电子病历系统
  c) 临床试验 / 前瞻性队列
  d) 行政索赔 / 医保数据
  e) 疾病登记库（癌症登记、糖尿病登记）
  f) 其他

如果是 (a): 问是否有抽样权重列（如 NHANES 的 WTMEC2YR），
  提醒: "标准 ML 模型不使用调查权重，这会在论文 Limitations 中声明。"
  → 设置 --weight-col, --survey-source

如果是 (b)-(e): 问是单中心还是多中心？数据时间跨度？
```
→ 得到 `--weight-col`, `--survey-source`

**Step 3: 结局定义（最关键）**

这是审稿人第一个会质疑的点。必须引导用户给出**精确的临床定义**。

```
问: 你要预测的结局（y=1）的临床定义是什么？
  请告诉我以下信息：

  1. 诊断标准来自哪些来源？（可多选）
     □ ICD 编码（请给出具体码，如 E11 = T2D）
     □ 实验室指标（如 HbA1c ≥ 6.5% 或 ≥ 48 mmol/mol）
     □ 空腹血糖 ≥ 7.0 mmol/L
     □ 医生诊断记录
     □ 患者自报（问卷）
     □ 用药记录（如服用降糖药）
     □ 疾病登记库确认
     □ 其他: ___

  2. 如果使用了多个来源，如何判定？
     □ 任一来源满足即为阳性（敏感，可能假阳性多）
     □ 至少两个来源一致（UKB 金标准，推荐）
     □ 所有来源都满足（极严格）

  3. 疾病亚型是什么？
     例: 2 型糖尿病（排除 1 型、妊娠期、继发性、MODY）

  4. 排除标准：哪些人应该被排除？
     例: 1 型糖尿病(E10) / 妊娠期糖尿病(O24) / 年龄<18

  5. 时间窗口：
     □ 基线时已患病（prevalent）
     □ 随访期间新发（incident），随访 ___ 年
     □ 事件性结局（如 30 天再入院）
```

收集完毕后构建 JSON:
```json
{
  "criteria": [
    {"source": "icd", "codes": ["E11"], "system": "ICD-10"},
    {"source": "lab", "test": "HbA1c", "threshold": ">=6.5%"},
    {"source": "medication", "drugs": ["metformin", "insulin"]}
  ],
  "adjudication": "at_least_two",
  "subtype": "type_2_diabetes",
  "exclusions": ["type_1_E10", "gestational_O24", "age_under_18"],
  "time_window": "prevalent_at_baseline",
  "ascertainment": ["hospital_ehr", "lab_system"],
  "validation": "cross_source_concordance"
}
```
→ 传给 `--outcome-definition`

**Step 3b: 入排标准与 CONSORT 流程**
```
问: 你的入组标准是什么？（哪些人被纳入研究？）
  例: 年龄 ≥ 18 岁、有 ≥ 1 次住院记录、基线无目标疾病

问: 排除了哪些人？每条排除标准各排了多少人？
  这将用于 CONSORT/STROBE 流程图。请按顺序列出:
  排除标准 1: ___ → 排除 ___ 人
  排除标准 2: ___ → 排除 ___ 人
  ...
  最终纳入: ___ 人

  (如不清楚，Phase 1 报告会提供总行数和缺失统计，
   但具体排除逻辑需要你根据临床知识决定)
```

**Step 3c: 预测时间点与特征时间归属 (MLGG-F05)**
```
问: 你的模型在什么时间点做预测？
  a) 入院时（只能用入院前已知的信息）
  b) 出院时（可以用住院期间的信息）
  c) 门诊就诊时（只能用当次就诊前的数据）
  d) 随访中某个固定时间点

问: 你的特征中，哪些在预测时间点之后才能知道？
  这些是"未来信息"——绝对不能用作预测特征!
  
  例如:
  - 入院时模型 → 出院诊断、手术类型、住院天数 都是"未来信息"
  - 出院时模型 → 30天后的复诊结果 是"未来信息"
  
  请将这些"未来信息"列名告诉我，我会帮你排除。
```

**Step 4: 定义变量泄漏检查**
```
问: 上面这些用于定义结局的变量（如 HbA1c、ICD 码），
  它们是否也出现在你的特征列中？

  如果 HbA1c 用于定义糖尿病（y=1 当 HbA1c >= 6.5%），
  那么 HbA1c 绝不能作为预测特征——它 IS 结局本身。

  请列出所有用于定义结局的列名:
```
→ 得到 `--definition-cols`
→ 这些列会被自动排除出特征集

**Step 5: 运行门控**

收集完上述信息后，构建并运行命令:
```bash
python3 scripts/gates/cohort_definition_gate.py \
  --data <path> \
  --target-col <col> \
  --id-col <col> \
  --outcome-definition '<JSON>' \
  --definition-cols <cols> \
  --weight-col <col> \
  --survey-source <source> \
  --report evidence/cohort_definition_report.json \
  --output-dir evidence/
```

**Step 6: 解读结果并引导下一步**

根据报告中的 warnings/failures 向用户解释:
- Riley 样本量是否充足 → 不足则建议减少特征或收集更多数据
- 疾病定义质量评级 → single source 建议增加验证来源
- 定义变量泄漏 → 明确哪些列被排除了
- 调查权重 → 提醒在论文中声明

然后说: "Phase 1 完成。现在进入 Phase 2: 数据划分。你的数据是纵向的还是横截面的？"

### 疾病定义知识库 (RAG 检索源)

当用户提到要预测某种疾病时，Agent 应该**立即查阅** `references/disease-definition-knowledge-base.json`，获取该疾病的：
- ICD-10 编码列表
- 实验室诊断标准（阈值、单位）
- 常用药物列表（用于药物记录作为辅助证据源）
- 排除标准（容易混淆的疾病）
- 必须排除的定义变量列表（`definition_variables_to_exclude`）
- 推荐的裁决策略
- 疾病分型信息

知识库覆盖 **10 种常见疾病**：
T2D · 高血压 · 冠心病 · CKD · 心衰 · 脑卒中 · COPD · 抑郁症 · 癌症(多部位) · 心房颤动 · 30天再入院

使用方法：
```python
# Agent 在引导 Step 3 时读取知识库
import json
kb = json.load(open("references/disease-definition-knowledge-base.json"))
disease = kb["diseases"]["type_2_diabetes"]
# → 获取 ICD codes, lab criteria, medications, exclusions, definition_variables_to_exclude
```

如果用户的疾病不在知识库中，Agent 应该按 `general_guidance.choosing_definition` 中的 7 条原则引导用户自行构建定义。

### 常见疾病定义模板（快速参考）

Agent 可以直接提供以下模板给用户参考：

**2 型糖尿病 (T2D)**:
```json
{"criteria":[{"source":"icd","codes":["E11"],"system":"ICD-10"},{"source":"lab","test":"HbA1c","threshold":">=6.5% or >=48mmol/mol"},{"source":"lab","test":"FPG","threshold":">=7.0mmol/L"},{"source":"medication","drugs":["metformin","glipizide","glimepiride","insulin"]},{"source":"self_report","question":"doctor_diagnosed_diabetes"}],"adjudication":"at_least_two","subtype":"type_2_diabetes","exclusions":["type_1_E10","gestational_O24","MODY","secondary","age_under_18"],"time_window":"prevalent_at_baseline"}
```

**高血压 (Hypertension)**:
```json
{"criteria":[{"source":"icd","codes":["I10","I11","I12","I13","I15"],"system":"ICD-10"},{"source":"measurement","test":"SBP","threshold":">=140mmHg"},{"source":"measurement","test":"DBP","threshold":">=90mmHg"},{"source":"medication","drugs":["amlodipine","lisinopril","losartan","hydrochlorothiazide"]},{"source":"self_report","question":"doctor_diagnosed_hypertension"}],"adjudication":"at_least_two","subtype":"essential_hypertension","exclusions":["secondary_hypertension","white_coat","pregnancy_induced"],"time_window":"prevalent_at_baseline"}
```

**冠心病 (CHD/CAD)**:
```json
{"criteria":[{"source":"icd","codes":["I20","I21","I22","I23","I24","I25"],"system":"ICD-10"},{"source":"procedure","codes":["CABG","PCI","coronary_angiography"]},{"source":"medication","drugs":["aspirin","clopidogrel","statin","nitroglycerin"]},{"source":"self_report","question":"doctor_diagnosed_heart_disease"}],"adjudication":"at_least_two","subtype":"coronary_artery_disease","exclusions":["heart_failure_only","valvular","congenital"],"time_window":"prevalent_at_baseline"}
```

**慢性肾病 (CKD)**:
```json
{"criteria":[{"source":"icd","codes":["N18"],"system":"ICD-10"},{"source":"lab","test":"eGFR","threshold":"<60mL/min/1.73m2"},{"source":"lab","test":"UACR","threshold":">=30mg/g"},{"source":"medication","drugs":["SGLT2_inhibitors","ACE_inhibitors"]}],"adjudication":"at_least_two","subtype":"CKD_stage_3_plus","exclusions":["acute_kidney_injury","dialysis_dependent"],"time_window":"prevalent_at_baseline"}
```

**30 天再入院 (30-day Readmission)**:
```json
{"criteria":[{"source":"administrative","definition":"unplanned_admission_within_30_days_of_discharge"}],"adjudication":"any_one","subtype":"all_cause_readmission","exclusions":["planned_readmission","death_before_30_days","transfer","left_AMA"],"time_window":"30_day_post_discharge"}
```

### 样本量（Phase 1）

Riley 2019 三准则（`riley_sample_size()` in `cohort_definition_gate.py`）：
- C1: 收缩因子 S ≥ 0.9 → n ≥ p / ((1-S) × φ)
- C2: R² optimism ≤ 0.05 → n ≥ p / 0.05
- C3: 风险精度 CI 半宽 ≤ 0.05 → n ≥ φ(1-φ) / (0.05/1.96)²
- 取三者最大值。**作为参考建议，不硬性阻断**：
  - EPV < 5 → WARNING（强烈建议减特征或增数据，结论标注 exploratory）
  - EPV 5-10 → INFO（在 Limitations 中声明）
  - Riley 不满足 → INFO（解释风险，不阻断）
  - 注：Riley 对小样本/罕见病过于严格，NC/NM 发表的论文也常达不到

### 划分（Phase 2）

**三种策略**：`grouped_temporal`（纵向）、`grouped_random`（横截面）、`stratified_grouped`（横截面+保证正类率一致）。横截面数据用 `--cross-sectional` flag，自动跳过时序检查。

**三种划分模式**（根据数据量选择）：

| 模式 | 参数 | 适用场景 | 模型选择方式 |
|------|------|---------|-------------|
| 三分法 | `--train-ratio 0.6 --valid-ratio 0.2 --test-ratio 0.2` | 大样本 (n > 5000) | valid 集调参 + test 集评估 |
| 两分法 | `--train-ratio 0.8 --valid-ratio 0.0 --test-ratio 0.2` | 中等样本 (n 1000-5000) | CV 调参 + test 集评估 |
| 仅CV | `--train-ratio 1.0 --valid-ratio 0.0 --test-ratio 0.0` | 小样本 (n < 1000) | Nested CV / Bootstrap 内部验证 |

Agent 引导时应根据 Phase 1 报告的样本量自动推荐：
```
n > 5000  → "样本量充足，推荐三分法 (60/20/20)"
n 1000-5000 → "中等样本，推荐两分法 (80/20) + 5折CV替代验证集"
n < 1000  → "小样本，考虑全量训练 + Nested CV 或 Bootstrap 内部验证"
n < 200   → "⚠️ 样本量可能不足，优先考虑 Riley 样本量检查结果"
```

**下游兼容性**：
- 两分法 (valid_ratio=0)：`train_select_evaluate.py` 自动切换 `--selection-data=cv_inner`，用 5 折 CV 替代 valid 集做模型选择
- CV-only (test_ratio=0)：Phase 6 评估使用 Bootstrap optimism correction 替代 test 集评估
- `--valid` 和 `--test` 参数已改为可选（不再 required）

**时序 CV**：
- 纵向数据（grouped_temporal 划分）应使用 `--temporal-cv` flag
- 此 flag 将 CV 从 StratifiedKFold(shuffle=True) 切换为 TimeSeriesSplit
- 防止 CV 内 future-to-past 泄漏（Steyerberg 2019 Ch.5 推荐）
- 横截面数据不需要此 flag

**已知限制**：
- MIN_POSITIVE_PER_SPLIT=10 对罕见病 (<3% 患病率) 可能过严，可通过 `--min-rows-per-split` 调整

### 编码（Phase 3）

自动检测（`encode_categorical_features()`）：
- Binary (2值) → 0/1 映射，OOD → 0.5 sentinel（中性值，不添加额外列）
- Categorical (3-15值) → OneHot，OOD → 全零行
- Numeric (>15值) → 保持原值

### 特征选择（Phase 4）

**设计哲学**：Harrell 2015 和 Steyerberg 2019 推荐"临床先验预指定 + 惩罚收缩"，而非数据驱动筛选。但当候选特征远超临床知识时，MLGG 提供以下有控制的筛选路径。

**方法流水线**：
```
NZV 过滤 → Ridge 基线(CV调优) → Stability Selection(Elastic Net + Group LASSO) → 对比决策 → EPV 重检
```

**关键方法学决策及文献依据**：

| 决策 | MLGG 做法 | 文献 | 常见审稿人质疑 |
|------|----------|------|----------------|
| 正则化类型 | Elastic Net (α∈{0.1-1.0}) 而非纯 L1 | Zou & Hastie 2005 JRSS-B | "为什么不用 LASSO?" → Elastic Net 处理共线性更好 |
| 稳定性选择 | 100 次子采样，阈值 0.6 | Meinshausen & Buhlmann 2010 JRSS-B | "特征选择稳定吗?" → 提供误选界 E[V] |
| 分组选择 | OneHot dummy 列同进同退 | Yuan & Lin 2006 JRSS-B (Group LASSO) | "race_White 保留但 race_Asian 丢弃?" → Group LASSO 防止 |
| Ridge 对照 | 全量特征 + L2 收缩作为 baseline | Harrell 2015 RMS Ch.4 | "为什么要做特征选择?" → 如果 Ridge 更好就不选 |
| 对比指标 | PR-AUC 而非 AUROC | Saito & Rehmsmeier 2015 | "为什么不用 AUROC?" → 类别不平衡下 PR-AUC 更灵敏 |
| 回退阈值 | 选择后 PR-AUC 降 >0.005 就回退 Ridge | 保守原则 | "选择反而更差?" → 自动回退全量模型 |
| 废弃方法 | 不用单因素 p 值筛选 | Heinze 2018 Biometrical Journal | "为什么不做单因素分析?" → 多重比较 + 丢弃联合有效特征 |

**MLGG 规则检查清单**：
- **MLGG-F01** [CRITICAL]: 标签/结局变量不得出现在特征中
- **MLGG-F02** [CRITICAL]: 预测时间点之后的信息不得作为特征
- **MLGG-F03** [CRITICAL]: 特征选择只在训练集上进行
- **MLGG-F04** [WARNING]: 不得使用单因素 p 值筛选（Heinze 2018）
- **MLGG-F06** [WARNING]: 必须与 Ridge 全量模型对照
- **MLGG-Z01** [WARNING]: 选择后 EPV 建议 ≥ 10（不满足需在 Limitations 声明，不硬性阻断）

**Peer Review 证据**（来自 peer-review-kb.json）：
- 107 篇 NC 论文中，审稿人对特征选择的常见质疑：
  - "为什么不和简单模型（age + sex + BMI only）比较?" (PR-001-C03, PR-067-C01)
  - "24 个参数 vs 87 个样本，模型过参数化" (PR-016-C01, CRITICAL)
  - "特征选择在整个数据集上做的，不是训练集" (PR-010-C01, CRITICAL — 导致性能虚高)
  - "OneHot 后 dummy 列被选择性保留/丢弃" (无 Group LASSO)
  - "没有报告哪些特征被选中及理由" (PR-054-C01)

**输出**：
- `selected_data.npz` — 选择后的 train/valid/test
- `selected_features.json` — 最终特征列表
- `stability_selection.csv` — 每个特征的入选概率
- `selection_report.json` — 完整审计留痕（方法、参数、Ridge PR-AUC、选择后 PR-AUC、E[V]、EPV）

### 模型选择（Phase 5）

Validation PR-AUC 最优 + one-SE rule 破平局。不用 train-test gap。Bootstrap optimism correction 内部验证。学习曲线评估收敛性。

### 评估（Phase 6）

5 域完整面板（`calibration_metrics()` + `metric_panel()` + `compute_nri_idi()` in `_gate_utils.py`）：
- 区分度: AUROC, AUPRC
- 校准: 截距(→0), 斜率(→1), O:E(→1), ECE, Hosmer-Lemeshow
- 整体: Brier, Brier Skill Score (>0=优于基线)
- 分类: MCC, LR+/LR-, Sensitivity, Specificity, PPV, NPV
- 临床: DCA 净效用, NRI (categorical + continuous), IDI

### p 值与多重检验策略

| 场景 | 测试次数 | 校正方法 | 理由 |
|------|---------|---------|------|
| check_nonlinearity | N 个特征 | **BH FDR（默认）** | 20 个特征各测一次 → 期望 1 个假阳性 |
| SHAP Kendall tau | C(K,2) 对 | 不校正 | 主要看 tau 值，不做假设检验决策 |
| DeLong AUC 比较 | 1 次 | 不校正 | 单一假设检验 |
| 置换检验 | 1 次 | 不校正 | 单一假设检验（模型 vs 随机） |
| Hosmer-Lemeshow | 1 次 | 不校正 | 单一校准检验 |

**原则**：
- **多特征/多亚组同时检验** → 必须 BH FDR（Benjamini & Hochberg 1995）
- **单一预设假设** → 不需要校正
- **探索性分析**（SHAP 排名一致性）→ 不做校正，但明确标注为探索性
- `check_nonlinearity(fdr_method="fdr_bh")` 默认启用 BH，可选 `"holm"` / `"bonferroni"` / `None`

**Peer Review 证据**：PR-042-C02 审稿人要求 "multiple testing adjustment should be considered"。
PR-025-C04 审稿人指出 "no clear adjustment for multiple comparisons"。

### SHAP（Phase 7）

多模型 SHAP（`shap_interpretability_gate.py`）：
- 逐族计算 → L1 归一化为比例(sum=1) → 等权平均
- TreeExplainer(RF/XGB/CatBoost/LGBM), LinearExplainer(LR), KernelExplainer(其他)
- 一致性: Kendall tau + Top-N Jaccard
- 输出: Table A(集成排名), B(逐模型明细), C(一致性), D(个案解释)

### 公平性与亚组分析（Phase 8）

**顶刊要求**：Nature Medicine / Lancet DH / JAMA / BMJ 四大刊均**强制要求**公平性分析。PROBAST+AI 2025 D5.3 明确要求按保护属性进行亚组公平性分析。

**保护属性覆盖**（必须分析的维度）：
- **age**：按临床有意义的区间分组（如 <65 / ≥65）
- **sex/gender**：按生物性别或自我认同性别
- **race/ethnicity**：按数据集可用的人种/族群分类
- **可选**：保险状态、社会经济状态、地理区域

> ⚠️ 如果数据集中缺少某个保护属性（如无种族数据），**必须在 Limitations 中声明**，而非忽略不提。
> Peer Review 证据：43/375 NC 审稿意见涉及公平性，其中 11 条专门指出缺少人口统计数据。

**6 项公平性指标**（`fairness_equity_gate.py`）：

| 指标 | 阈值 | 严重度 | 说明 |
|------|------|--------|------|
| 均等化优势差距 (Equalized Odds Gap) | < 0.15 | HIGH | 亚组间 sensitivity 最大差异 |
| 差异影响比 (Disparate Impact Ratio) | > 0.80 | HIGH | 四分之五规则，法律/监管标准 |
| FPR 均等差距 | < 0.15 | HIGH | 假阳性率在亚组间的差异 |
| FNR 均等差距 | < 0.15 | HIGH | 假阴性率在亚组间的差异 |
| 亚组最低 PR-AUC | > 0.40 | MEDIUM | 防止"平均好但少数群体极差" |
| 亚组 DCA 净效用差异 | 报告 | INFO | equity gap = max - min 净效用 |

**亚组样本量要求**（不硬性阻断，而是分级标注）：
- n < 20 → 标记为"不可靠"，不基于此做公平性声明
- n 20-49 → 标记为"不稳定"，需报告宽 CI
- n ≥ 50 → 可靠，正常报告

**偏差检测后的应对**（D11.5）：
当任一公平性指标超过阈值时，Agent 应引导用户考虑：
1. 亚组特异性阈值校准（不同亚组用不同 Youden 阈值）
2. 公平约束优化（如等化 FPR）
3. 在论文中如实报告差异并讨论原因
4. **不强制要求消除所有差异**——有些差异有临床意义（如年龄对疾病严重度的影响）

**不可能定理声明**（D11.8）：
当同时报告 ≥3 个公平性指标时，必须说明优先考虑哪个以及为什么——三个指标不可能同时满足（Chouldechova 2017）。

**Peer Review 常见关切**（来自 peer-review-kb.json）：
- "性别分布不均可解释全部结果" → 需要多变量调整 (PR-012)
- "缺少种族数据，但研究声称模型普适" → 在 Limitations 声明 (PR-003)
- "未对亚组进行 DCA" → 模型可能帮助多数但伤害少数 (PR-020)
- "Hispanic 不是 ancestry，是 ethnicity" → 人口统计变量分类需准确 (PR-045)

### 报告与合规（Phase 9）

- TRIPOD+AI 2024: 27 项逐项核对 (Collins 2024 BMJ)
- PROBAST+AI 2025: 4 域偏倚评估 (Moons 2025 BMJ)
- 局限性讨论: 数据来源 / 时间有效性 / 外部效度 / 公平性局限
- Model Card 自动生成
- 12 维评分 (0-100)

---

## Gate 失败恢复工作流

当任何 gate 失败时，按以下步骤排查：

```
1. 查看失败报告:
   python3 scripts/tools/explain_gate.py --report evidence/<gate_name>_report.json

2. 识别错误代码:
   报告中 failures[].code → 查 references/error-knowledge-base.json

3. 常见错误快速修复:
   - patient_id_overlap     → 检查 split_data.py 的 --patient-id-col
   - temporal_leakage       → 确认 train 时间 < valid < test
   - feature_name_suspicious → 检查 feature_lineage_spec
   - calibration_poor       → 添加 Platt scaling (calibrate.py)
   - seed_instability       → 增加模型正则化强度
   - permutation_not_significant → 模型无效，考虑更换特征集
   - SHAP_RANK_DISAGREEMENT → 模型间 Kendall tau 低，检查特征交互
   - COHORT_EPV_CRITICAL    → 减少候选特征数 或 收集更多数据
   - COHORT_RILEY_UNDERPOWERED → 同上，参考 Riley 2019 三准则

4. 修复后重跑:
   python3 scripts/orchestration/mlgg.py workflow --request configs/request.json --strict

5. 仍然失败 → 检查完整知识库:
   cat references/error-knowledge-base.json | python3 -m json.tool | grep -A5 "<error_code>"
```
