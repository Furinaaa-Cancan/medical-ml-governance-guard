# mlgg-lint

Static analysis tool for ML Python code — detects data leakage, improper preprocessing, and evaluation malpractice.

Part of [ML Leakage Guard](https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard).

## Install

```bash
cd plugin
pip install -e .
```

## Usage

```bash
# Check files
mlgg-lint check path/to/code.py

# JSON output (for AI agents)
mlgg-lint check code.py --format json

# SARIF output (for IDE integration)
mlgg-lint check code.py --format sarif

# CI gate (exit 1 on errors)
mlgg-lint check code.py --exit-code

# List all rules
mlgg-lint rules

# Via parent CLI
python3 scripts/mlgg.py lint check code.py
```

## Rules

| ID | Severity | Name | Description |
|----|----------|------|-------------|
| R001 | ERROR | fit-before-split | Preprocessor fit/fit_transform before train_test_split |
| R002 | ERROR | scaler-fit-on-test | Preprocessor .fit() on test/validation data |
| R003 | ERROR | resample-on-test | SMOTE/resampling on validation/test data |
| R004 | WARNING | split-without-group | train_test_split without groups= for patient data |
| R005 | ERROR | threshold-on-test | Threshold selection using test data |
| R006 | ERROR | feature-selection-on-full | Feature selection before split |
| R007 | ERROR | target-as-feature | Target column in feature matrix |
| R008 | WARNING | temporal-split-shuffle | Shuffled split on temporal data |
| R009 | INFO | no-confidence-intervals | Metrics without bootstrap CI |
| R010 | WARNING | train-metric-as-final | Training metrics reported as final |

## Inline Suppression

```python
X_scaled = scaler.fit_transform(X)  # noqa: R001
X_scaled = scaler.fit_transform(X)  # noqa  (suppresses all rules)
```

## Configuration

Create `.mlgg-lint.toml` in your project root:

```toml
[mlgg-lint]
severity-threshold = "warning"

[mlgg-lint.rules]
R004 = false
R009 = false
```

## Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard
    rev: main
    hooks:
      - id: mlgg-lint
```

## VS Code Extension

See `vscode/` directory. The extension calls `mlgg-lint check --format sarif` on save and maps results to editor diagnostics.
