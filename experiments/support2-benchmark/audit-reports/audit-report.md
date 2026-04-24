# ML Governance Guard — External Project Audit Report

**Project**: `support2-benchmark`  
**Path**: `/Volumes/Seagate/Skill/ml-leakage-guard/experiments/support2-benchmark`  
**Generated**: 2026-04-24T05:05:47.252836+00:00  
**MLGG Version**: 1.0 (33-gate pipeline)  
**Standard References**: TRIPOD+AI 2024, PROBAST+AI 2025, STARD-AI 2021

---

## Overall Score

| Metric | Value |
|--------|-------|
| **Total Score** | **37.2 / 100** |
| Grade | Not publishable / 不可发表 |
| Score Bar | `███████░░░░░░░░░░░░░` 37.2% |

> **Not publishable**: Fundamental flaws detected. Comprehensive rework required.

## 12-Dimension Scores

| # | Dimension | Score | Max | Grade |
|---|-----------|-------|-----|-------|
| 1 | Data Integrity | 12.0 | 12 | ✓ |
| 2 | Leakage Prevention | 0.0 | 15 | ✗ |
| 3 | Pipeline Isolation | 12.0 | 12 | ✓ |
| 4 | Model Selection Rigor | 0.0 | 10 | ✗ |
| 5 | Statistical Validity | 12.0 | 12 | ✓ |
| 6 | Generalization Evidence | 0.0 | 10 | ✗ |
| 7 | Clinical Completeness | 0.0 | 7 | ✗ |
| 8 | Reporting Standards | 0.0 | 7 | ✗ |
| 9 | Reproducibility | 0.0 | 6 | ✗ |
| 10 | Security & Provenance | 1.2 | 3 | ✗ |
| 11 | Fairness & Equity | 0.0 | 3 | ✗ |
| 12 | Sample Size Adequacy | 0.0 | 3 | ✗ |

## TRIPOD+AI 2024 Coverage

**Reference**: Collins et al. BMJ 2024;385:e078378  
**Coverage**: 1/17 required items (5%)  

| Item ID | Label | AI-Specific | Status |
|---------|-------|-------------|--------|
| 1 | Title |  | ? Not Assessed |
| 4 | Source of Data |  | ✓ Covered |
| 5 | Participants |  | ? Not Assessed |
| 6a | Item 6a |  | ? Not Assessed |
| 6b | Item 6b |  | ? Not Assessed |
| 7 | Sample Size |  | ? Not Assessed |
| 8 | Missing Data |  | ? Not Assessed |
| 10 | Model Development | ★ | ? Not Assessed |
| 11 | Internal Validation |  | ? Not Assessed |
| 12 | Fairness and Equity Assessment | ★ | ? Not Assessed |
| 15b | Item 15b |  | ? Not Assessed |
| 16 | Model Specification |  | ? Not Assessed |
| 17 | Model Performance |  | ? Not Assessed |
| 18 | Model Uncertainty | ★ | ? Not Assessed |
| 20 | Fairness Results | ★ | ? Not Assessed |
| 21 | Limitations |  | ? Not Assessed |
| 27 | Funding, Conflicts of Interest, and Data/Code Availability | ★ | ? Not Assessed |

## PROBAST+AI 2025 Risk-of-Bias Assessment

**Reference**: Wolff et al. PROBAST+AI 2025  
**Overall Risk of Bias**: ? **UNCLEAR**  

| Domain | ROB Status | Gates Assessed |
|--------|-----------|----------------|
| Participant Selection | ✓ low | `split_protocol_gate, external_validation_gate, sample_size_gate` |
| Predictors / Features | ? unclear | `leakage_gate, definition_variable_guard, feature_lineage_gate` |
| Outcome | ? unclear | `reporting_bias_gate, clinical_metrics_gate` |
| Analysis | ✓ low | `leakage_gate, tuning_leakage_gate, split_protocol_gate` |

## Issues Found

**Total**: 35 issues (35 critical/error, 0 warning, 0 info)

### Critical / Error Issues

#### [ERROR] Temporal boundary violation detected.

**Source**: Gate: `leakage`  
**Error Code**: `temporal_overlap`  
**Root Cause**: Gate leakage failed: Temporal boundary violation detected.  

**Fix**: Review gate requirements for leakage and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Temporal boundary violation detected.

**Source**: Gate: `leakage`  
**Error Code**: `temporal_overlap`  
**Root Cause**: Gate leakage failed: Temporal boundary violation detected.  

**Fix**: Review gate requirements for leakage and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Temporal boundary violation detected.

**Source**: Gate: `leakage`  
**Error Code**: `temporal_overlap`  
**Root Cause**: Gate leakage failed: Temporal boundary violation detected.  

**Fix**: Review gate requirements for leakage and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Attestation is older than max-age-hours — possible replay.

**Source**: Gate: `execution_attestation`  
**Error Code**: `attestation_stale`  
**Root Cause**: Gate execution_attestation failed: Attestation is older than max-age-hours — possible replay.  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Referenced path escapes the attestation bundle sandbox.

**Source**: Gate: `execution_attestation`  
**Error Code**: `path_escapes_sandbox`  
**Root Cause**: Gate execution_attestation failed: Referenced path escapes the attestation bundle sandbox.  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Referenced path escapes the attestation bundle sandbox.

**Source**: Gate: `execution_attestation`  
**Error Code**: `path_escapes_sandbox`  
**Root Cause**: Gate execution_attestation failed: Referenced path escapes the attestation bundle sandbox.  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Referenced path escapes the attestation bundle sandbox.

**Source**: Gate: `execution_attestation`  
**Error Code**: `path_escapes_sandbox`  
**Root Cause**: Gate execution_attestation failed: Referenced path escapes the attestation bundle sandbox.  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Target not found in definition spec.

**Source**: Gate: `definition_guard`  
**Error Code**: `target_not_found`  
**Root Cause**: Gate definition_guard failed: Target not found in definition spec.  

**Fix**: Review gate requirements for definition_guard and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Target not found in definition spec.

**Source**: Gate: `lineage`  
**Error Code**: `target_not_found`  
**Root Cause**: Gate lineage failed: Target not found in definition spec.  

**Fix**: Review gate requirements for lineage and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

#### [ERROR] Feature missingness exceeds policy threshold.

**Source**: Gate: `missingness_policy`  
**Error Code**: `feature_missingness_too_high`  
**Root Cause**: Gate missingness_policy failed: Feature missingness exceeds policy threshold.  

**Fix**: Review gate requirements for missingness_policy and address the listed failure.  
**Prevention**: Run gates regularly during development, not just at publication.  

## Remediation Plan

Prioritized action list to reach publication-grade status:

### [P0] Temporal boundary violation detected.

**Severity**: ERROR  
**Error Code**: `temporal_overlap`  

**Fix**: Review gate requirements for leakage and address the listed failure.

### [P0] Temporal boundary violation detected.

**Severity**: ERROR  
**Error Code**: `temporal_overlap`  

**Fix**: Review gate requirements for leakage and address the listed failure.

### [P0] Temporal boundary violation detected.

**Severity**: ERROR  
**Error Code**: `temporal_overlap`  

**Fix**: Review gate requirements for leakage and address the listed failure.

### [P0] Attestation is older than max-age-hours — possible replay.

**Severity**: ERROR  
**Error Code**: `attestation_stale`  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.

### [P0] Referenced path escapes the attestation bundle sandbox.

**Severity**: ERROR  
**Error Code**: `path_escapes_sandbox`  

**Fix**: Review gate requirements for execution_attestation and address the listed failure.

### [P2] Improve Leakage Prevention dimension score (0.0/15)

**Severity**: INFO  

**Fix**: Address all failing checks in the Leakage Prevention dimension.

### [P2] Improve Model Selection Rigor dimension score (0.0/10)

**Severity**: INFO  

**Fix**: Address all failing checks in the Model Selection Rigor dimension.

### [P2] Improve Generalization Evidence dimension score (0.0/10)

**Severity**: INFO  

**Fix**: Address all failing checks in the Generalization Evidence dimension.

## Journal Gap Analysis

**Target Journal**: Nature Medicine  
**Minimum Score Required**: 92  
**Current Score**: 37.2  
**Meets Threshold**: ✗ No  
**Mandatory Compliance**: 2/12  

**Unmet Requirements**:

- ✗ Independent external validation on geographically/temporally distinct cohort
- ✗ Complete TRIPOD+AI checklist
- ✗ Calibration assessment (calibration plot + ECE)
- ✗ Decision curve analysis demonstrating clinical utility
- ✗ Comparison with established clinical models/scores
- ✗ Subgroup analysis across key demographics
- ✗ Clear temporal split preventing data leakage
- ✗ Transparent feature selection process
- ✗ Fairness & equity analysis: equalized odds gap <0.15, disparate impact ratio >0.80
- ✗ Sample size adequacy: EPV ≥10, shrinkage ≥0.90, ≥100 events

---

## Report Metadata

| Key | Value |
|-----|-------|
| Generated by | ML Governance Guard (MLGG) v1.0 |
| Report version | audit_report.v2 |
| Error KB entries | 107 |
| Literature KB entries | 67 |
| TRIPOD+AI items | 27 (Collins et al. BMJ 2024;385:e078378) |
| PROBAST+AI domains | 4 + AI supplementary (Wolff et al. 2025) |
