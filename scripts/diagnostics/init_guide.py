#!/usr/bin/env python3
"""
Generate MLGG methodology guide for any ML project.

Creates a .mlgg/ directory with AI-consumable rules and a CLAUDE.md snippet
that instructs Claude Code / Cursor to guide users through rigorous medical
binary classification following MLGG standards.

Usage:
    python3 scripts/diagnostics/init_guide.py --output /path/to/my_project
    python3 scripts/mlgg.py init-guide -- --output /path/to/my_project
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Rules database — distilled from 33 gates + 20 lint rules
# ---------------------------------------------------------------------------

RULES: List[Dict[str, Any]] = [
    # ── Data Splitting ────────────────────────────────────────────────────
    {
        "id": "MLGG-S01",
        "category": "data_splitting",
        "severity": "CRITICAL",
        "name": "patient_level_disjoint_split",
        "rule": "训练/验证/测试集必须按患者 ID 划分，同一患者的所有记录只能出现在一个集合中。",
        "rule_en": "Split by patient ID — all records from one patient must stay in one split.",
        "why": "患者内记录高度相关，跨集合会导致数据泄漏，AUC 虚高 5-15%。",
        "bad_example": "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
        "good_example": "from sklearn.model_selection import GroupShuffleSplit\ngss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)\ntrain_idx, test_idx = next(gss.split(X, y, groups=patient_ids))",
        "lint_rule": "R004",
        "gates": ["split_protocol_gate", "leakage_gate"],
    },
    {
        "id": "MLGG-S02",
        "category": "data_splitting",
        "severity": "CRITICAL",
        "name": "temporal_ordering",
        "rule": "测试集的时间必须晚于训练集，不得随机打散时序数据。",
        "rule_en": "Test set time must be after training set — never shuffle temporal data randomly.",
        "why": "临床预测模型用于预测未来，随机 split 等于偷看未来，AUC 虚高 10-30%。",
        "bad_example": "train_test_split(df, test_size=0.2, random_state=42)  # 时序数据随机 split",
        "good_example": "cutoff = df['event_time'].quantile(0.8)\ntrain = df[df['event_time'] <= cutoff]\ntest = df[df['event_time'] > cutoff]",
        "lint_rule": "R008",
        "gates": ["split_protocol_gate", "leakage_gate"],
    },
    # ── Preprocessing Isolation ───────────────────────────────────────────
    {
        "id": "MLGG-P01",
        "category": "preprocessing",
        "severity": "CRITICAL",
        "name": "fit_only_on_train",
        "rule": "所有预处理器（Scaler/Imputer/Encoder）只能在训练集上 fit，验证/测试集只做 transform。",
        "rule_en": "Fit preprocessors on training set ONLY. Validation/test sets get transform() only.",
        "why": "在全量数据上 fit 会泄漏测试集的均值/方差/分布信息到训练阶段。",
        "bad_example": "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)  # 全量数据\nX_train, X_test = train_test_split(X_scaled)",
        "good_example": "X_train, X_test = train_test_split(X)\nscaler = StandardScaler()\nX_train_scaled = scaler.fit_transform(X_train)\nX_test_scaled = scaler.transform(X_test)  # 只 transform",
        "lint_rule": "R001, R002",
        "gates": ["leakage_gate"],
    },
    {
        "id": "MLGG-P02",
        "category": "preprocessing",
        "severity": "CRITICAL",
        "name": "no_smote_on_test",
        "rule": "SMOTE/过采样只能应用于训练集，绝不能在验证/测试集上使用。",
        "rule_en": "Apply SMOTE/oversampling to training set ONLY — never on validation or test.",
        "why": "在测试集上过采样会生成合成样本，评估指标不再反映真实分布。",
        "bad_example": "X_res, y_res = SMOTE().fit_resample(X, y)  # 全量\nX_train, X_test = train_test_split(X_res, y_res)",
        "good_example": "X_train, X_test, y_train, y_test = train_test_split(X, y)\nX_train_res, y_train_res = SMOTE().fit_resample(X_train, y_train)",
        "lint_rule": "R003",
        "gates": ["imbalance_policy_gate"],
    },
    {
        "id": "MLGG-P03",
        "category": "preprocessing",
        "severity": "CRITICAL",
        "name": "no_global_clean_before_split",
        "rule": "不得在 split 前对全量数据做 dropna / clip / 分位数清洗。",
        "rule_en": "No dropna / clip / quantile cleaning on full data before splitting.",
        "why": "全局清洗会让训练集和测试集共享清洗阈值，间接泄漏信息。",
        "bad_example": "df = df.dropna()\ndf['age'] = df['age'].clip(lower=q1, upper=q99)\ntrain, test = train_test_split(df)",
        "good_example": "train, test = train_test_split(df)\ntrain = train.dropna(subset=['age'])\n# 用 train 的分位数 clip，transform 到 test",
        "lint_rule": "R020",
        "gates": ["leakage_gate"],
    },
    {
        "id": "MLGG-P04",
        "category": "preprocessing",
        "severity": "WARNING",
        "name": "imputation_fit_on_train",
        "rule": "缺失值插补器只能在训练集上 fit，中位数/均值等统计量来自训练集。",
        "rule_en": "Imputer statistics (median, mean) must come from training set only.",
        "why": "测试集的分布信息泄漏到插补参数中。",
        "bad_example": "imp = SimpleImputer(strategy='median')\nX = imp.fit_transform(X_all)  # 全量 fit",
        "good_example": "imp = SimpleImputer(strategy='median')\nX_train = imp.fit_transform(X_train)\nX_test = imp.transform(X_test)",
        "lint_rule": "R001",
        "gates": ["missingness_policy_gate"],
    },
    # ── Feature Engineering ───────────────────────────────────────────────
    {
        "id": "MLGG-F01",
        "category": "features",
        "severity": "CRITICAL",
        "name": "no_target_as_feature",
        "rule": "不得将目标变量（或由目标变量派生的特征）作为预测特征。",
        "rule_en": "Never use target variable (or target-derived features) as predictors.",
        "why": "直接使用标签信息，AUC 接近 1.0，是最严重的数据泄漏。",
        "bad_example": "features = df[['age', 'lab1', 'diagnosis_result']]  # diagnosis_result 是标签",
        "good_example": "target_col = 'diagnosis_result'\nfeatures = df.drop(columns=[target_col, 'patient_id', 'event_time'])",
        "lint_rule": "R007",
        "gates": ["definition_variable_guard", "feature_lineage_gate"],
    },
    {
        "id": "MLGG-F02",
        "category": "features",
        "severity": "CRITICAL",
        "name": "no_future_information",
        "rule": "特征只能使用预测时刻之前的信息，不得包含未来数据。",
        "rule_en": "Features must use only information available before the prediction time point.",
        "why": "使用诊断后的检查结果预测诊断，是时间泄漏，临床不可用。",
        "bad_example": "# 用入院后第 7 天的 lab 预测入院时的死亡风险\ndf['lab_day7'] = ...",
        "good_example": "# 只用入院时（prediction time）之前已知的数据\ndf_features = df[df['measure_time'] <= df['admission_time']]",
        "lint_rule": "manual_review",
        "gates": ["definition_variable_guard", "feature_lineage_gate"],
    },
    {
        "id": "MLGG-F03",
        "category": "features",
        "severity": "CRITICAL",
        "name": "feature_selection_on_train",
        "rule": "特征选择（mutual info / chi2 / LASSO）只能在训练集上进行。",
        "rule_en": "Feature selection must be done on training set only.",
        "why": "在全量数据上选特征，选择结果包含测试集信息，过拟合。",
        "bad_example": "selector = SelectKBest(chi2, k=10)\nX_selected = selector.fit_transform(X, y)  # 全量\ntrain, test = split(X_selected)",
        "good_example": "train, test = split(X)\nselector = SelectKBest(chi2, k=10)\nX_train_sel = selector.fit_transform(X_train, y_train)\nX_test_sel = selector.transform(X_test)",
        "lint_rule": "R006",
        "gates": ["feature_engineering_audit_gate"],
    },
    # ── Model Selection & Tuning ──────────────────────────────────────────
    {
        "id": "MLGG-M01",
        "category": "model_selection",
        "severity": "CRITICAL",
        "name": "never_tune_on_test",
        "rule": "超参数调优只能使用训练集/验证集/内层 CV，绝不能用测试集。",
        "rule_en": "Hyperparameter tuning must use train/valid/inner-CV only — NEVER test set.",
        "why": "测试集必须只用一次（最终评估），多次使用会乐观偏估泛化性能。",
        "bad_example": "for params in param_grid:\n    model.set_params(**params)\n    model.fit(X_train, y_train)\n    score = model.score(X_test, y_test)  # 用测试集选参数",
        "good_example": "cv = StratifiedKFold(n_splits=5)\ngrid = GridSearchCV(model, param_grid, cv=cv, scoring='roc_auc')\ngrid.fit(X_train, y_train)  # 内层 CV 选参数\nfinal_score = grid.score(X_test, y_test)  # 测试集只用一次",
        "lint_rule": "R017",
        "gates": ["tuning_leakage_gate"],
    },
    {
        "id": "MLGG-M02",
        "category": "model_selection",
        "severity": "CRITICAL",
        "name": "no_threshold_on_test",
        "rule": "分类阈值不得在测试集上调优。用验证集选阈值，测试集只做最终评估。",
        "rule_en": "Do not optimize classification threshold on test set. Use validation set.",
        "why": "在测试集上选阈值 = 间接调参，最终 F1/Sensitivity 会虚高。",
        "bad_example": "fpr, tpr, thresholds = roc_curve(y_test, y_pred_test)\nbest_t = thresholds[np.argmax(tpr - fpr)]  # 在测试集上选阈值",
        "good_example": "fpr, tpr, thresholds = roc_curve(y_valid, y_pred_valid)\nbest_t = thresholds[np.argmax(tpr - fpr)]  # 在验证集上选阈值\n# 用 best_t 在测试集上做最终评估",
        "lint_rule": "R005",
        "gates": ["evaluation_quality_gate"],
    },
    {
        "id": "MLGG-M03",
        "category": "model_selection",
        "severity": "WARNING",
        "name": "sufficient_candidate_models",
        "rule": "候选模型至少 3 个不同族（如 LR + RF + XGBoost），避免单模型偏倚。",
        "rule_en": "Evaluate at least 3 different model families to avoid single-model bias.",
        "why": "只报告一个模型的结果可能是 cherry-picking，审稿人会质疑。",
        "bad_example": "model = XGBClassifier()\nmodel.fit(X_train, y_train)  # 只试了一个模型",
        "good_example": "candidates = [\n    ('lr', LogisticRegression()),\n    ('rf', RandomForestClassifier()),\n    ('xgb', XGBClassifier()),\n]\nfor name, model in candidates:\n    scores[name] = cross_val_score(model, X_train, y_train, cv=5)",
        "lint_rule": "manual_review",
        "gates": ["model_selection_audit_gate"],
    },
    # ── Evaluation & Statistics ────────────────────────────────────────────
    {
        "id": "MLGG-E01",
        "category": "evaluation",
        "severity": "CRITICAL",
        "name": "confidence_intervals_required",
        "rule": "所有主要指标必须报告 95% 置信区间（Bootstrap 1000+ 次）。",
        "rule_en": "Report 95% CI for all primary metrics (bootstrap ≥1000 resamples).",
        "why": "没有 CI 的单点估计无法判断统计显著性，顶刊必定要求。",
        "bad_example": "auc = roc_auc_score(y_test, y_pred)\nprint(f'AUC: {auc:.3f}')  # 没有 CI",
        "good_example": "from sklearn.utils import resample\naucs = []\nfor _ in range(1000):\n    idx = resample(range(len(y_test)), random_state=_)\n    aucs.append(roc_auc_score(y_test[idx], y_pred[idx]))\nprint(f'AUC: {np.median(aucs):.3f} (95% CI: {np.percentile(aucs, 2.5):.3f}-{np.percentile(aucs, 97.5):.3f})')",
        "lint_rule": "R009",
        "gates": ["ci_matrix_gate", "evaluation_quality_gate"],
    },
    {
        "id": "MLGG-E02",
        "category": "evaluation",
        "severity": "CRITICAL",
        "name": "complete_metric_panel",
        "rule": "必须报告完整指标面板：AUC-ROC, AUC-PR, Sensitivity, Specificity, PPV, NPV, F1, Brier Score。",
        "rule_en": "Report full metrics: AUC-ROC, AUC-PR, Sensitivity, Specificity, PPV, NPV, F1, Brier.",
        "why": "只报 AUC 不够，临床需要 sensitivity/specificity tradeoff 信息。",
        "bad_example": "print(f'AUC: {roc_auc_score(y_test, y_pred):.3f}')  # 只报了一个指标",
        "good_example": "from sklearn.metrics import (roc_auc_score, average_precision_score,\n    confusion_matrix, brier_score_loss)\ncm = confusion_matrix(y_test, y_pred_binary)\ntn, fp, fn, tp = cm.ravel()\nmetrics = {\n    'auroc': roc_auc_score(y_test, y_pred_prob),\n    'auprc': average_precision_score(y_test, y_pred_prob),\n    'sensitivity': tp / (tp + fn),\n    'specificity': tn / (tn + fp),\n    'ppv': tp / (tp + fp),\n    'npv': tn / (tn + fn),\n    'f1': 2*tp / (2*tp + fp + fn),\n    'brier': brier_score_loss(y_test, y_pred_prob),\n}",
        "lint_rule": "manual_review",
        "gates": ["clinical_metrics_gate"],
    },
    {
        "id": "MLGG-E03",
        "category": "evaluation",
        "severity": "WARNING",
        "name": "calibration_check",
        "rule": "必须评估概率校准质量（ECE < 0.1），并提供校准曲线。",
        "rule_en": "Check probability calibration (ECE < 0.1) and provide calibration curve.",
        "why": "临床决策依赖概率可靠性，未校准的模型 output 不能作为风险概率使用。",
        "bad_example": "# 训练完就结束，没有检查校准\nmodel.predict_proba(X_test)",
        "good_example": "from sklearn.calibration import calibration_curve\nfraction_of_positives, mean_predicted = calibration_curve(y_test, y_pred_prob, n_bins=10)\n# ECE\nece = np.mean(np.abs(fraction_of_positives - mean_predicted))\nprint(f'ECE: {ece:.4f}')  # 应 < 0.1",
        "lint_rule": "manual_review",
        "gates": ["calibration_dca_gate"],
    },
    {
        "id": "MLGG-E04",
        "category": "evaluation",
        "severity": "WARNING",
        "name": "train_test_gap_check",
        "rule": "训练集和测试集的主指标差距不得超过 0.05（AUC 等），否则提示过拟合。",
        "rule_en": "Train-test metric gap must be < 0.05 for primary metric; larger gaps signal overfitting.",
        "why": "差距过大说明模型在训练集上过拟合，泛化能力不足。",
        "bad_example": "# Train AUC: 0.95, Test AUC: 0.72 → 差距 0.23，严重过拟合",
        "good_example": "train_auc = roc_auc_score(y_train, model.predict_proba(X_train)[:, 1])\ntest_auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])\ngap = train_auc - test_auc\nassert gap < 0.05, f'Overfitting: train-test gap = {gap:.3f}'",
        "lint_rule": "manual_review",
        "gates": ["generalization_gap_gate"],
    },
    # ── Sample Size & Power ───────────────────────────────────────────────
    {
        "id": "MLGG-Z01",
        "category": "sample_size",
        "severity": "WARNING",
        "name": "events_per_variable",
        "rule": "EPV（每个预测变量的事件数）≥ 10，严格模式 ≥ 20。",
        "rule_en": "Events per variable (EPV) ≥ 10, strict mode ≥ 20.",
        "why": "EPV 不足导致模型不稳定，系数方差大，过拟合风险高。Riley et al. (2020) 标准。",
        "bad_example": "# 50 个事件，30 个特征 → EPV = 1.67，远不够",
        "good_example": "n_events = y_train.sum()\nn_features = X_train.shape[1]\nepv = n_events / n_features\nif epv < 10:\n    print(f'WARNING: EPV={epv:.1f} < 10, reduce features or increase sample')",
        "lint_rule": "manual_review",
        "gates": ["sample_size_gate"],
    },
    # ── Reproducibility ───────────────────────────────────────────────────
    {
        "id": "MLGG-R01",
        "category": "reproducibility",
        "severity": "INFO",
        "name": "set_random_state",
        "rule": "所有涉及随机性的操作必须设置 random_state / seed。",
        "rule_en": "Set random_state/seed for all stochastic operations.",
        "why": "可复现性是科学研究的基本要求。",
        "bad_example": "model = RandomForestClassifier()  # 没设 random_state",
        "good_example": "model = RandomForestClassifier(n_estimators=100, random_state=42)",
        "lint_rule": "R016",
        "gates": ["seed_stability_gate"],
    },
    {
        "id": "MLGG-R02",
        "category": "reproducibility",
        "severity": "WARNING",
        "name": "seed_stability",
        "rule": "用至少 5 个不同随机种子验证结果稳定性，AUC 标准差应 < 0.02。",
        "rule_en": "Verify stability across ≥5 seeds; primary metric std should be < 0.02.",
        "why": "单种子结果可能是偶然的，多种子验证才能证明稳健性。",
        "bad_example": "# 只跑了 seed=42 一次就报结果",
        "good_example": "results = []\nfor seed in [42, 123, 456, 789, 1024]:\n    model = XGBClassifier(random_state=seed)\n    model.fit(X_train, y_train)\n    results.append(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))\nprint(f'AUC: {np.mean(results):.3f} ± {np.std(results):.3f}')",
        "lint_rule": "manual_review",
        "gates": ["seed_stability_gate"],
    },
    # ── Reporting Standards ───────────────────────────────────────────────
    {
        "id": "MLGG-T01",
        "category": "reporting",
        "severity": "WARNING",
        "name": "tripod_ai_compliance",
        "rule": "按 TRIPOD+AI 2024 清单报告所有必需项（数据来源、纳入排除标准、缺失值处理、模型开发过程等）。",
        "rule_en": "Follow TRIPOD+AI 2024 checklist for all required reporting items.",
        "why": "Collins et al. BMJ 2024 — 顶刊投稿必需，缺项会被直接退稿。",
        "bad_example": "# Methods 只写了 '我们用 XGBoost 训练了模型'",
        "good_example": "# Methods 应包含：\n# 1. 数据来源和采集时间范围\n# 2. 纳入排除标准\n# 3. 结局变量定义\n# 4. 特征选择过程\n# 5. 缺失值处理方法\n# 6. 模型开发和内部验证\n# 7. 外部验证（如有）\n# 8. 校准评估",
        "lint_rule": "manual_review",
        "gates": ["reporting_bias_gate", "publication_gate"],
    },
    # ── Fairness ──────────────────────────────────────────────────────────
    {
        "id": "MLGG-Q01",
        "category": "fairness",
        "severity": "WARNING",
        "name": "subgroup_analysis",
        "rule": "必须按性别、年龄组、种族等亚组评估模型性能，报告差异。",
        "rule_en": "Evaluate and report model performance across subgroups (sex, age, race).",
        "why": "整体 AUC 良好不代表各亚组均受益，可能存在公平性问题。",
        "bad_example": "# 只报了总体 AUC，没有分组分析",
        "good_example": "for group in ['male', 'female']:\n    mask = df_test['sex'] == group\n    auc = roc_auc_score(y_test[mask], y_pred[mask])\n    print(f'{group}: AUC = {auc:.3f}')",
        "lint_rule": "manual_review",
        "gates": ["fairness_equity_gate"],
    },
]

# ---------------------------------------------------------------------------
# Checklist template (Markdown)
# ---------------------------------------------------------------------------

CHECKLIST_MD = textwrap.dedent("""\
    # MLGG 回顾性队列二分类预测检查清单 | Retrospective Cohort Binary-Classification Checklist

    > 基于 ML Governance Guard 33 道门控标准，TRIPOD+AI 2024 / PROBAST+AI 2025 合规。
    > Based on MLGG 33-gate standard. TRIPOD+AI 2024 / PROBAST+AI 2025 compliant.

    ## 1. 数据准备 | Data Preparation

    - [ ] 数据来源和采集时间范围已明确记录
    - [ ] 纳入排除标准已定义
    - [ ] 结局变量（标签）定义明确，无未来信息泄漏
    - [ ] 已检查特征中不包含标签变量或其衍生变量
    - [ ] 缺失值比例已统计，缺失率 >60% 的特征已处理

    ## 2. 数据分割 | Data Splitting

    - [ ] 按患者 ID 分割（同一患者不跨集合）
    - [ ] 时序数据按时间顺序分割（测试集时间晚于训练集）
    - [ ] 分割比例合理（推荐 60/20/20 或 70/15/15）
    - [ ] 各集合阳性率分布一致（差异 <5%）
    - [ ] 分割种子已锁定并记录

    ## 3. 预处理 | Preprocessing

    - [ ] Scaler/Imputer/Encoder 只在训练集上 fit
    - [ ] SMOTE/过采样只在训练集上使用
    - [ ] 没有在 split 前做全局 dropna/clip/分位数清洗
    - [ ] Pipeline 结构：imputer → scaler → classifier（隔离保证）

    ## 4. 特征工程 | Feature Engineering

    - [ ] 特征选择只在训练集上进行
    - [ ] 无未来信息泄漏（所有特征在预测时刻前可获得）
    - [ ] EPV ≥ 10（事件数 / 特征数）

    ## 5. 模型训练 | Model Training

    - [ ] 至少比较了 3 个不同模型族
    - [ ] 超参数调优使用内层 CV 或验证集（非测试集）
    - [ ] 阈值选择在验证集上完成
    - [ ] 所有随机操作设置了 random_state
    - [ ] Early stopping 使用验证集（非测试集）

    ## 6. 评估 | Evaluation

    - [ ] 完整指标面板：AUC-ROC, AUC-PR, Sensitivity, Specificity, PPV, NPV, F1, Brier
    - [ ] 所有主指标有 95% CI（Bootstrap ≥1000 次）
    - [ ] Train-test gap < 0.05
    - [ ] 概率校准已评估（ECE < 0.1）
    - [ ] 多种子稳定性验证（≥5 seeds, std < 0.02）

    ## 7. 外部验证 | External Validation

    - [ ] 如有条件，在独立队列上验证
    - [ ] 跨时间段验证（temporal validation）
    - [ ] 跨机构验证（external center）

    ## 8. 亚组分析 | Subgroup Analysis

    - [ ] 按性别分析性能差异
    - [ ] 按年龄组分析性能差异
    - [ ] 其他临床相关亚组

    ## 9. 报告 | Reporting

    - [ ] TRIPOD+AI 2024 清单已对照
    - [ ] PROBAST+AI 2025 偏倚风险已评估
    - [ ] 数据和代码可复现性已保证
    - [ ] 局限性已讨论

    ## 评分参考 | Scoring Reference

    | 等级 | 分数 | 说明 |
    |------|------|------|
    | 顶刊级 | ≥90 | 所有关键项通过 |
    | 需补充 | 75-89 | 有缺项但无致命问题 |
    | 重大缺陷 | 60-74 | 存在数据泄漏或严重方法学缺陷 |
    | 不可发表 | <60 | 需要重做 |
""")


# ---------------------------------------------------------------------------
# CLAUDE.md template for user projects
# ---------------------------------------------------------------------------

CLAUDE_MD_TEMPLATE = textwrap.dedent("""\
    # MLGG — Medical ML Methodology Guide

    > 本文件由 ML Governance Guard 生成，指导 AI 按照发布级标准协助回顾性队列二分类预测分析。
    > Generated by ML Governance Guard for retrospective-cohort binary-classification. Instructs AI to follow publication-grade standards.

    ## 角色 | Role

    你是一个 Nature Methods / JAMA 级别的医学 ML 审稿人。在协助用户编写二分类预测代码时，你必须：

    1. **主动防泄漏**：在用户写出可能泄漏的代码前就提醒，而非事后纠正
    2. **量化评判**：每一步都对照 .mlgg/rules.json 中的规则检查
    3. **引用规则**：发现问题时引用具体规则 ID（如 MLGG-S01）和正确示例
    4. **不放水**：不因为用户不理解就降低标准，用通俗语言解释为什么必须这样做

    ## 工作流 | Workflow

    当用户要求进行二分类预测分析时，按以下顺序引导：

    ### Phase 1: 数据理解
    - 确认数据来源、采集时间范围、样本量
    - 确认结局变量定义（标签列）
    - 确认患者 ID 列和时间列
    - 计算阳性率、缺失率、EPV
    - **检查点**：EPV ≥ 10？样本量是否足够？（MLGG-Z01）

    ### Phase 2: 数据分割
    - 必须按患者 ID 分割（MLGG-S01）
    - 有时间列时必须按时间顺序（MLGG-S02）
    - 推荐 train/valid/test = 60/20/20
    - **检查点**：各集合阳性率一致？无患者跨集？

    ### Phase 3: 预处理
    - 所有 fit 操作只在训练集上（MLGG-P01）
    - SMOTE 只在训练集上（MLGG-P02）
    - 不得在 split 前全局清洗（MLGG-P03）
    - 推荐用 sklearn Pipeline 封装（imputer → scaler → classifier）
    - **检查点**：验证/测试集只做 transform？

    ### Phase 4: 模型训练
    - 至少比较 3 个模型族（MLGG-M03）
    - 超参调优用验证集或内层 CV（MLGG-M01）
    - 阈值选择用验证集（MLGG-M02）
    - 设置 random_state（MLGG-R01）
    - **检查点**：测试集是否被用于任何选择/调优？

    ### Phase 5: 评估
    - 报告完整指标面板（MLGG-E02）
    - 所有指标附 95% CI（MLGG-E01）
    - 检查 train-test gap（MLGG-E04）
    - 检查概率校准（MLGG-E03）
    - 多种子稳定性（MLGG-R02）
    - **检查点**：指标是否只来自测试集的单次最终评估？

    ### Phase 6: 报告
    - 对照 TRIPOD+AI 2024 清单（MLGG-T01）
    - 亚组分析（MLGG-Q01）
    - 讨论局限性

    ## 规则文件 | Rule Files

    - `.mlgg/rules.json` — 完整规则定义（机器可读）
    - `.mlgg/checklist.md` — 人类可读检查清单
    - `.mlgg/examples/` — 正确/错误代码示例

    ## 严重度定义 | Severity Levels

    - **CRITICAL**：必须修复，否则结果不可信（数据泄漏、标签泄漏等）
    - **WARNING**：强烈建议修复，顶刊审稿人会要求（CI 缺失、校准不足等）
    - **INFO**：最佳实践建议（random_state、代码风格等）

    ## 发现问题时的输出格式 | Issue Format

    ```
    ⚠ [MLGG-P01] CRITICAL: fit_only_on_train
    位置: analysis.py:42
    问题: StandardScaler.fit_transform() 在全量数据上调用
    修复: 先 split，再在训练集上 fit_transform，测试集只 transform
    ```
""")


# ---------------------------------------------------------------------------
# Claude Code global slash command (/mlgg)
# ---------------------------------------------------------------------------

SLASH_COMMAND_MD = textwrap.dedent("""\
    # /mlgg — Medical ML Methodology Guide

    You are now operating as a **Nature Methods / JAMA-grade medical ML reviewer**.
    Guide the user through rigorous binary classification following MLGG standards.

    ## Your behavior

    1. **Proactive leak prevention**: Warn BEFORE the user writes leaky code, not after
    2. **Cite rules**: When flagging issues, cite the rule ID (e.g. MLGG-S01) with the correct example
    3. **No shortcuts**: Never lower standards because the user doesn't understand — explain in plain language why it matters
    4. **Quantitative**: Every checkpoint must have a measurable criterion

    ## Guided workflow

    When the user asks to build a binary classification model, follow these phases IN ORDER.
    Do not skip phases. At each checkpoint, verify before proceeding.

    ### Phase 1: Data Understanding
    - Confirm data source, collection period, sample size
    - Confirm outcome variable (label column) definition
    - Confirm patient ID column and time column
    - Calculate positive rate, missing rate, EPV (events per variable)
    - **Checkpoint**: EPV ≥ 10? Sample size sufficient? (MLGG-Z01)

    ### Phase 2: Data Splitting
    - MUST split by patient ID — same patient cannot appear in multiple splits (MLGG-S01)
    - If temporal data: test set time MUST be after training set (MLGG-S02)
    - Recommended: train/valid/test = 60/20/20
    - Handle patient overlap at time boundaries (assign to earlier split)
    - **Checkpoint**: No patient overlap? Positive rates consistent across splits?

    ### Phase 3: Preprocessing
    - ALL fit() calls on training set ONLY (MLGG-P01)
    - SMOTE/oversampling on training set ONLY (MLGG-P02)
    - NO global dropna/clip/quantile before split (MLGG-P03)
    - Imputer statistics from training set only (MLGG-P04)
    - Use sklearn/imblearn Pipeline: imputer → scaler → (SMOTE) → classifier
    - **Checkpoint**: Validation/test sets receive transform() only?

    ### Phase 4: Model Training
    - Compare ≥3 model families (e.g. LR + RF + XGBoost) (MLGG-M03)
    - Hyperparameter tuning on validation set or inner CV — NEVER test set (MLGG-M01)
    - Threshold selection on validation set (Youden's J) (MLGG-M02)
    - Feature selection on training set only (MLGG-F03)
    - Set random_state everywhere (MLGG-R01)
    - **Checkpoint**: Is test set used for ANY selection or tuning?

    ### Phase 5: Evaluation
    - Full metric panel: AUROC, AUPRC, Sensitivity, Specificity, PPV, NPV, F1, Brier (MLGG-E02)
    - 95% CI for ALL metrics via bootstrap ≥1000 (MLGG-E01)
    - Train-test gap < 0.05 (MLGG-E04)
    - Probability calibration: ECE < 0.1 (MLGG-E03)
    - Multi-seed stability: ≥5 seeds, std < 0.02 (MLGG-R02)
    - Decision Curve Analysis for clinical utility
    - **Checkpoint**: Metrics from single final test evaluation only?

    ### Phase 6: Reporting
    - TRIPOD+AI 2024 checklist (MLGG-T01)
    - Subgroup analysis by sex, age, etc. (MLGG-Q01)
    - Discuss limitations
    - Report threshold used and how it was selected

    ## Issue format

    When you find a problem, output:
    ```
    ⚠ [MLGG-P01] CRITICAL: fit_only_on_train
    Location: analysis.py:42
    Problem: StandardScaler.fit_transform() called on full data before split
    Fix: Split first, then fit_transform on train only, transform on test
    ```

    ## Severity levels
    - **CRITICAL**: Must fix — results untrustworthy (data leakage, label leakage)
    - **WARNING**: Strongly recommended — reviewers will require (missing CI, poor calibration)
    - **INFO**: Best practice (random_state, code style)

    ## Key rules quick reference

    | ID | Severity | Rule |
    |----|----------|------|
    | MLGG-S01 | CRITICAL | Split by patient ID — no patient overlap across splits |
    | MLGG-S02 | CRITICAL | Test set time must be after training set |
    | MLGG-P01 | CRITICAL | Fit preprocessors on training set ONLY |
    | MLGG-P02 | CRITICAL | SMOTE on training set ONLY |
    | MLGG-P03 | CRITICAL | No global cleaning before split |
    | MLGG-F01 | CRITICAL | Never use target as feature |
    | MLGG-F02 | CRITICAL | No future information in features |
    | MLGG-F03 | CRITICAL | Feature selection on training set only |
    | MLGG-M01 | CRITICAL | Never tune on test set |
    | MLGG-M02 | CRITICAL | Select threshold on validation set |
    | MLGG-E01 | CRITICAL | 95% CI for all primary metrics |
    | MLGG-E02 | CRITICAL | Full metric panel required |
    | MLGG-M03 | WARNING | Compare ≥3 model families |
    | MLGG-E03 | WARNING | Calibration ECE < 0.1 |
    | MLGG-E04 | WARNING | Train-test gap < 0.05 |
    | MLGG-Z01 | WARNING | EPV ≥ 10 |
    | MLGG-R02 | WARNING | Multi-seed stability |
    | MLGG-T01 | WARNING | TRIPOD+AI 2024 compliance |
    | MLGG-Q01 | WARNING | Subgroup analysis |
    | MLGG-R01 | INFO | Set random_state |

    ## If the project has .mlgg/ directory
    Read `.mlgg/rules.json` for full rule definitions with code examples.
    Read `.mlgg/checklist.md` for the progress checklist.
    Reference `.mlgg/examples/` for correct and incorrect patterns.

    Start by asking the user: "What dataset are you working with? Tell me about the outcome you want to predict, and I'll guide you through a publication-grade analysis."
""")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def write_rules_json(output_dir: Path) -> Path:
    """Write rules.json to .mlgg/ directory."""
    rules_path = output_dir / "rules.json"
    payload = {
        "contract_version": "mlgg_rules.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "ml-governance-guard/init_guide",
        "total_rules": len(RULES),
        "severity_counts": {
            "CRITICAL": sum(1 for r in RULES if r["severity"] == "CRITICAL"),
            "WARNING": sum(1 for r in RULES if r["severity"] == "WARNING"),
            "INFO": sum(1 for r in RULES if r["severity"] == "INFO"),
        },
        "rules": RULES,
    }
    rules_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rules_path


def write_checklist(output_dir: Path) -> Path:
    """Write checklist.md to .mlgg/ directory."""
    checklist_path = output_dir / "checklist.md"
    checklist_path.write_text(CHECKLIST_MD, encoding="utf-8")
    return checklist_path


def write_examples(output_dir: Path) -> Path:
    """Write code examples to .mlgg/examples/ directory."""
    examples_dir = output_dir / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    # Bad example: common leakage patterns
    bad_code = textwrap.dedent("""\
        \"\"\"
        ❌ BAD: Common data leakage patterns in medical ML.
        This file demonstrates what NOT to do.
        Each section is annotated with the MLGG rule it violates.
        \"\"\"

        import pandas as pd
        import numpy as np
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import roc_auc_score
        from imblearn.over_sampling import SMOTE

        df = pd.read_csv("patient_data.csv")

        # ❌ MLGG-P03: Global cleaning before split
        df = df.dropna()
        df['age'] = df['age'].clip(lower=df['age'].quantile(0.01),
                                   upper=df['age'].quantile(0.99))

        # ❌ MLGG-F01: Target column included as feature
        X = df.drop(columns=['patient_id'])  # forgot to drop 'outcome'
        y = df['outcome']

        # ❌ MLGG-P01: Scaler fit on full data before split
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # ❌ MLGG-S01: Random split without patient grouping
        X_train, X_test, y_train, y_test = train_test_split(
            X_scaled, y, test_size=0.2, random_state=42
        )

        # ❌ MLGG-P02: SMOTE on full data (already wrong, but even after split...)
        X_res, y_res = SMOTE().fit_resample(X_train, y_train)

        # ❌ MLGG-M03: Only one model, no comparison
        model = RandomForestClassifier()  # ❌ MLGG-R01: no random_state
        model.fit(X_res, y_res)

        # ❌ MLGG-M01: Tuning on test set
        for n in [50, 100, 200, 500]:
            model.n_estimators = n
            model.fit(X_res, y_res)
            score = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
            print(f"n={n}, AUC={score:.3f}")

        # ❌ MLGG-E01: No confidence interval
        # ❌ MLGG-E02: Only AUC reported, no full panel
        print(f"Final AUC: {roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]):.3f}")
    """)

    # Good example: proper methodology
    good_code = textwrap.dedent("""\
        \"\"\"
        ✅ GOOD: Publication-grade medical binary classification.
        Follows MLGG methodology — no data leakage, full evaluation.
        \"\"\"

        import pandas as pd
        import numpy as np
        from sklearn.pipeline import Pipeline
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import GroupShuffleSplit, StratifiedKFold, GridSearchCV
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier
        from xgboost import XGBClassifier
        from sklearn.metrics import (
            roc_auc_score, average_precision_score, brier_score_loss,
            confusion_matrix,
        )
        from sklearn.utils import resample
        from imblearn.over_sampling import SMOTE
        from imblearn.pipeline import Pipeline as ImbPipeline

        SEED = 42
        np.random.seed(SEED)

        # ── 1. Load data ─────────────────────────────────────────────────────
        df = pd.read_csv("patient_data.csv")
        target_col = "outcome"
        patient_id_col = "patient_id"
        time_col = "event_time"
        feature_cols = [c for c in df.columns
                        if c not in [target_col, patient_id_col, time_col]]

        print(f"Samples: {len(df)}, Features: {len(feature_cols)}")
        print(f"Positive rate: {df[target_col].mean():.3f}")
        print(f"EPV: {df[target_col].sum() / len(feature_cols):.1f}")  # MLGG-Z01

        # ── 2. Split by patient + temporal order (MLGG-S01, MLGG-S02) ────────
        # Step 1: temporal split
        df = df.sort_values(time_col)
        cutoff_train = df[time_col].quantile(0.6)
        cutoff_valid = df[time_col].quantile(0.8)

        train_mask = df[time_col] <= cutoff_train
        valid_mask = (df[time_col] > cutoff_train) & (df[time_col] <= cutoff_valid)
        test_mask = df[time_col] > cutoff_valid

        # Step 2: resolve patient overlap — assign borderline patients to earlier split
        train_pids = set(df.loc[train_mask, patient_id_col])
        valid_pids = set(df.loc[valid_mask, patient_id_col])
        test_pids = set(df.loc[test_mask, patient_id_col])
        # Patients in both train and valid → keep in train, remove from valid
        overlap_tv = train_pids & valid_pids
        if overlap_tv:
            valid_mask = valid_mask & ~df[patient_id_col].isin(overlap_tv)
            valid_pids -= overlap_tv
        # Patients in both valid and test → keep in valid, remove from test
        overlap_vt = valid_pids & test_pids
        if overlap_vt:
            test_mask = test_mask & ~df[patient_id_col].isin(overlap_vt)
            test_pids -= overlap_vt
        # Patients in both train and test → keep in train, remove from test
        overlap_tt = train_pids & test_pids
        if overlap_tt:
            test_mask = test_mask & ~df[patient_id_col].isin(overlap_tt)

        # Final verification
        train_pids = set(df.loc[train_mask, patient_id_col])
        valid_pids = set(df.loc[valid_mask, patient_id_col])
        test_pids = set(df.loc[test_mask, patient_id_col])
        assert not (train_pids & test_pids), "Patient overlap between train and test!"
        assert not (train_pids & valid_pids), "Patient overlap between train and valid!"
        assert not (valid_pids & test_pids), "Patient overlap between valid and test!"

        X_train = df.loc[train_mask, feature_cols]
        y_train = df.loc[train_mask, target_col]
        X_valid = df.loc[valid_mask, feature_cols]
        y_valid = df.loc[valid_mask, target_col]
        X_test = df.loc[test_mask, feature_cols]
        y_test = df.loc[test_mask, target_col]

        # ── 3. Build pipeline with SMOTE inside (MLGG-P01, MLGG-P02) ────────
        # SMOTE must come AFTER impute+scale so synthetic samples don't pollute
        # the imputer/scaler statistics. imblearn.Pipeline handles this correctly:
        # fit_resample is only called during fit(), not during predict().
        def make_pipeline(model):
            return ImbPipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("smote", SMOTE(random_state=SEED)),
                ("model", model),
            ])

        # ── 4. Compare ≥3 model families (MLGG-M03) ─────────────────────────
        candidates = {
            "lr": LogisticRegression(max_iter=1000, random_state=SEED),
            "rf": RandomForestClassifier(n_estimators=200, random_state=SEED),
            "xgb": XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.1,
                random_state=SEED, eval_metric="logloss",
            ),
        }

        best_model_name, best_auc, best_pipe = None, -1, None
        for name, model in candidates.items():
            pipe = make_pipeline(model)
            pipe.fit(X_train, y_train)  # imputer/scaler fit on real train only
            # Select on validation set, NOT test (MLGG-M01)
            auc = roc_auc_score(y_valid, pipe.predict_proba(X_valid)[:, 1])
            print(f"{name}: valid AUC = {auc:.3f}")
            if auc > best_auc:
                best_model_name, best_auc, best_pipe = name, auc, pipe

        print(f"\\nBest model: {best_model_name}")

        # ── 5. Select threshold on VALIDATION set (MLGG-M02) ────────────────
        from sklearn.metrics import roc_curve as _roc_curve
        y_valid_prob = best_pipe.predict_proba(X_valid)[:, 1]
        fpr_v, tpr_v, thresholds_v = _roc_curve(y_valid, y_valid_prob)
        youden_j = tpr_v - fpr_v
        best_threshold = float(thresholds_v[np.argmax(youden_j)])
        print(f"Optimal threshold (Youden's J on valid): {best_threshold:.3f}")

        # ── 6. Final evaluation on TEST set (one-time) ───────────────────────
        y_pred_prob = best_pipe.predict_proba(X_test)[:, 1]

        # ── 7. Full metric panel + bootstrap CI for ALL metrics (MLGG-E01, E02)
        def compute_metrics(y_true, y_prob, threshold):
            y_bin = (y_prob >= threshold).astype(int)
            tn, fp, fn, tp = confusion_matrix(y_true, y_bin).ravel()
            return {
                "roc_auc": roc_auc_score(y_true, y_prob),
                "pr_auc": average_precision_score(y_true, y_prob),
                "sensitivity": tp / (tp + fn) if (tp + fn) > 0 else 0,
                "specificity": tn / (tn + fp) if (tn + fp) > 0 else 0,
                "ppv": tp / (tp + fp) if (tp + fp) > 0 else 0,
                "npv": tn / (tn + fn) if (tn + fn) > 0 else 0,
                "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0,
                "brier": brier_score_loss(y_true, y_prob),
            }

        point_metrics = compute_metrics(y_test, y_pred_prob, best_threshold)

        # Bootstrap CI for all metrics (MLGG-E01)
        n_boot = 1000
        boot_results = {k: [] for k in point_metrics}
        for i in range(n_boot):
            idx = resample(range(len(y_test)), random_state=i)
            y_t, y_p = y_test.iloc[idx], y_pred_prob[idx]
            if len(set(y_t)) < 2:
                continue
            m = compute_metrics(y_t, y_p, best_threshold)
            for k in boot_results:
                boot_results[k].append(m[k])

        print(f"\\n{'='*60}")
        print(f"{'Metric':<15} {'Point':>8} {'95% CI':>20}")
        print(f"{'-'*15} {'-'*8} {'-'*20}")
        for k, v in point_metrics.items():
            ci_lo = np.percentile(boot_results[k], 2.5)
            ci_hi = np.percentile(boot_results[k], 97.5)
            print(f"{k:<15} {v:>8.3f} ({ci_lo:.3f} - {ci_hi:.3f})")

        # Train-test gap check (MLGG-E04)
        train_auc = roc_auc_score(y_train, best_pipe.predict_proba(X_train)[:, 1])
        gap = train_auc - point_metrics['roc_auc']
        print(f"\\nTrain AUC: {train_auc:.3f}, Test AUC: {point_metrics['roc_auc']:.3f}, Gap: {gap:.3f}")
        if gap > 0.05:
            print("WARNING: Train-test gap > 0.05, possible overfitting!")

        # Calibration check (MLGG-E03)
        from sklearn.calibration import calibration_curve
        frac_pos, mean_pred = calibration_curve(y_test, y_pred_prob, n_bins=10)
        ece = np.mean(np.abs(frac_pos - mean_pred))
        print(f"ECE: {ece:.4f} {'(PASS)' if ece < 0.1 else '(FAIL: > 0.1, consider recalibration)'}")

        # Decision Curve Analysis hint (MLGG-E03)
        # DCA evaluates clinical net benefit across threshold probabilities.
        # For full DCA, use: pip install dcurves
        #   from dcurves import dca, plot_graphs
        #   dca_results = dca(data=test_df, outcome='outcome', modelnames=['model'])
        #   plot_graphs(dca_results)
        print("\\nNote: Consider adding Decision Curve Analysis (DCA) for clinical utility assessment.")
    """)

    (examples_dir / "bad_leaky_pipeline.py").write_text(bad_code, encoding="utf-8")
    (examples_dir / "good_publication_grade.py").write_text(good_code, encoding="utf-8")
    return examples_dir


def write_claude_md(project_dir: Path, mlgg_dir_name: str) -> Path:
    """Write or append CLAUDE.md in the project root."""
    claude_md_path = project_dir / "CLAUDE.md"
    content = CLAUDE_MD_TEMPLATE

    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")
        if "MLGG" in existing:
            print(f"  CLAUDE.md already contains MLGG section, skipping: {claude_md_path}")
            return claude_md_path
        # Append to existing CLAUDE.md
        content = existing.rstrip() + "\n\n---\n\n" + content
        print(f"  Appended MLGG section to existing CLAUDE.md: {claude_md_path}")
    else:
        print(f"  Created CLAUDE.md: {claude_md_path}")

    claude_md_path.write_text(content, encoding="utf-8")
    return claude_md_path


def install_slash_command(force: bool = False) -> int:
    """Install /mlgg as a global Claude Code slash command."""
    commands_dir = Path.home() / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    target = commands_dir / "mlgg.md"
    if target.exists() and not force:
        print(f"[WARN] /mlgg command already installed at {target}")
        print("  Use --force to overwrite.")
        return 1

    # Prefer the canonical mlgg.md from the repo (single source of truth)
    repo_mlgg = Path(__file__).resolve().parent.parent.parent / ".claude" / "commands" / "mlgg.md"
    if repo_mlgg.exists():
        content = repo_mlgg.read_text(encoding="utf-8")
    else:
        # Fallback to embedded version if running outside the repo
        content = SLASH_COMMAND_MD

    target.write_text(content, encoding="utf-8")
    print(f"Installed /mlgg command: {target}")
    print()
    print("Usage: Open any project in Claude Code and type /mlgg")
    print("  Claude will guide you through publication-grade binary classification.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate MLGG methodology guide for your ML project.\n\n"
            "Two modes:\n"
            "  1. Project guide:  --output /path/to/project\n"
            "     Creates .mlgg/ + CLAUDE.md in your project\n\n"
            "  2. Global command: --install-command\n"
            "     Installs /mlgg slash command for Claude Code\n"
            "     (works in ANY project without init-guide)\n\n"
            "Examples:\n"
            "  python3 scripts/diagnostics/init_guide.py --output /path/to/my_project\n"
            "  python3 scripts/diagnostics/init_guide.py --install-command\n"
            "  python3 scripts/mlgg.py init-guide -- --output .\n"
            "  python3 scripts/mlgg.py init-guide -- --install-command\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Target project directory (will create .mlgg/ inside it).",
    )
    parser.add_argument(
        "--install-command",
        action="store_true",
        help="Install /mlgg as a global Claude Code slash command (~/.claude/commands/mlgg.md).",
    )
    parser.add_argument(
        "--no-claude-md",
        action="store_true",
        help="Skip generating/appending CLAUDE.md.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files.",
    )
    args = parser.parse_args()

    # Mode: install global slash command
    if args.install_command:
        rc = install_slash_command(force=args.force)
        # If also --output, continue to project guide
        if not args.output:
            return rc
        if rc not in (0, 1):
            return rc
        print()

    # Mode: project guide
    if not args.output:
        if not args.install_command:
            parser.error("Either --output or --install-command (or both) is required.")
        return 0

    project_dir = Path(args.output).expanduser().resolve()
    if not project_dir.is_dir():
        print(f"[FAIL] Target directory does not exist: {project_dir}", file=sys.stderr)
        return 2

    mlgg_dir = project_dir / ".mlgg"

    if mlgg_dir.exists() and not args.force:
        print(f"[WARN] .mlgg/ already exists at {mlgg_dir}")
        print("  Use --force to overwrite, or delete it manually.")
        return 1

    mlgg_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating MLGG methodology guide in: {project_dir}")
    print()

    # 1. Rules JSON
    rules_path = write_rules_json(mlgg_dir)
    print(f"  rules.json        — {len(RULES)} rules ({rules_path})")

    # 2. Checklist
    checklist_path = write_checklist(mlgg_dir)
    print(f"  checklist.md      — human-readable checklist ({checklist_path})")

    # 3. Code examples
    examples_dir = write_examples(mlgg_dir)
    print(f"  examples/         — bad + good code examples ({examples_dir})")

    # 4. CLAUDE.md
    if not args.no_claude_md:
        write_claude_md(project_dir, ".mlgg")

    print()
    print("Done! Next steps:")
    print(f"  1. Open {project_dir} in Claude Code or Cursor")
    print("  2. AI will automatically follow MLGG standards when helping you write code")
    print("  3. Check .mlgg/checklist.md as you progress through your analysis")
    print()
    print("Tip: Also run --install-command to get the /mlgg slash command globally.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
