# mlgg-lint

Static analysis tool for ML Python code — detects data leakage, improper preprocessing, and evaluation malpractice. 27 AST-level rules (R001-R027).

Part of [ML Governance Guard](https://github.com/Furinaaa-Cancan/medical-ml-governance-guard). This is an **independent sub-package** within the monorepo — it has its own `pyproject.toml` and can be installed separately. `pip install .` from the project root installs the main MLGG framework but does NOT include mlgg-lint; install it explicitly if needed.

## Install

```bash
# Option 1: Install as standalone package
cd plugin
pip install -e .

# Option 2: Use via MLGG CLI (no separate install needed)
cd ml-governance-guard
python3 scripts/orchestration/mlgg.py lint check <file.py>
```

## Usage

```bash
# Check a file
python3 scripts/mlgg.py lint check path/to/code.py

# Check a directory (recursively scans all .py files)
python3 scripts/mlgg.py lint check path/to/project/

# JSON output (for AI agents)
python3 scripts/mlgg.py lint check code.py --format json

# SARIF output (for IDE integration)
python3 scripts/mlgg.py lint check code.py --format sarif

# CI gate (exit 1 if any ERROR-severity findings)
python3 scripts/mlgg.py lint check code.py --exit-code

# Only show warnings and errors (hide info)
python3 scripts/mlgg.py lint check code.py --severity warning

# Disable specific rules
python3 scripts/mlgg.py lint check code.py --disable R004,R009

# List all rules
python3 scripts/mlgg.py lint rules

# Direct invocation (without parent CLI)
cd plugin && PYTHONPATH=. python3 -m mlgg_lint check <file.py>
```

## Rules

| ID | Severity | Name | Detects |
|----|----------|------|---------|
| R001 | ERROR | fit-before-split | `fit()`/`fit_transform()` called on full dataset before `train_test_split` |
| R002 | ERROR | scaler-fit-on-test | Preprocessor `.fit()` called with test/validation data (incl. keyword args) |
| R003 | ERROR | resample-on-test | SMOTE/oversampling applied to test/validation data (incl. chained calls) |
| R004 | WARNING | split-without-group | `train_test_split` without `groups=` in patient/subject context |
| R005 | ERROR | threshold-on-test | `roc_curve`/`precision_recall_curve` on test data for threshold selection |
| R006 | ERROR | feature-selection-on-full | Feature selector instantiated before split |
| R007 | ERROR | target-as-feature | Target column in feature matrix (tracks DataFrame origin + `.drop()`) |
| R008 | WARNING | temporal-split-shuffle | Shuffled `train_test_split` on temporal data |
| R009 | INFO | no-confidence-intervals | Metrics without bootstrap CI computation |
| R010 | WARNING | train-metric-as-final | Metrics computed on training data reported as final results |
| R011 | ERROR | cv-internal-smote | SMOTE/resampling with CV but not inside imblearn.Pipeline |
| R012 | WARNING | cv-accuracy-imbalanced | `scoring='accuracy'` in CV on imbalanced data |
| R013 | WARNING | hardcoded-threshold | Classification threshold hardcoded to 0.5 |
| R014 | WARNING | label-encoder-on-features | LabelEncoder used on feature columns (use OrdinalEncoder) |
| R015 | WARNING | small-test-set | `test_size < 0.1` produces unstable estimates |
| R016 | INFO | no-random-state | Stochastic function without `random_state=` |
| R017 | ERROR | early-stop-on-test | `eval_set` uses test data for early stopping |
| R018 | INFO | scaling-before-trees | Feature scaling applied before tree-based models |
| R019 | INFO | multiple-comparison | 3+ models compared without correction (Bonferroni/Holm) |
| R020 | WARNING | global-clean-before-split | `fillna(df.mean())` before split leaks test distribution |

### Coverage by category

| Category | Rules | Severity |
|----------|-------|----------|
| **Data leakage** | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split | ERROR |
| **Split issues** | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
| **Cross-validation** | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced | ERROR / WARNING |
| **Evaluation misuse** | R010 train-metric-as-final, R013 hardcoded-threshold | WARNING |
| **Preprocessing** | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING / INFO |
| **Reproducibility** | R016 no-random-state | INFO |
| **Statistical rigor** | R009 no-CI, R019 multiple-comparison | INFO |

### Detection capabilities

- **Keyword args**: `scaler.fit(X=X_test)` detected (not just positional)
- **Chained calls**: `SMOTE().fit_resample(X_test)` detected
- **DataFrame tracking**: R007 traces variable origin through `df.drop()` / `df[cols]` assignments
- **Re-assignment**: `X = df.drop(...)` then `X = df[cols]` correctly clears drop-derived status
- **Pipeline exclusion**: `Pipeline.fit(X_test)` is NOT flagged (intentional usage)
- **Relative paths**: Output uses relative paths to avoid leaking absolute paths

## Inline Suppression

```python
X_scaled = scaler.fit_transform(X)  # noqa: R001
X_scaled = scaler.fit_transform(X)  # noqa: R001, R002
X_scaled = scaler.fit_transform(X)  # noqa  (suppresses all rules on this line)
```

## Configuration

Create `.mlgg-lint.toml` in your project root:

```toml
[mlgg-lint]
severity-threshold = "warning"   # hide INFO findings

[mlgg-lint.rules]
R004 = false   # disable split-without-group
R009 = false   # disable no-confidence-intervals
```

The config file is auto-discovered by walking up from the target file's directory.

## Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Furinaaa-Cancan/medical-ml-governance-guard
    rev: main
    hooks:
      - id: mlgg-lint
```

## VS Code Extension

See `vscode/` directory. The extension:
1. Calls `mlgg-lint check --format sarif` on file save/open
2. Parses SARIF and maps results to VS Code diagnostics
3. Configurable via VS Code settings (`mlgg-lint.enable`, `mlgg-lint.severity`, etc.)

## Output Formats

| Format | Flag | Use case |
|--------|------|----------|
| text | `--format text` (default) | Human-readable, colored in terminal |
| json | `--format json` | AI agent consumption, CI parsing |
| sarif | `--format sarif` | IDE integration, GitHub Code Scanning |

## Security

- File size limit: 16 MB (prevents memory exhaustion)
- Config size limit: 1 MB
- Symlinks skipped during directory scanning
- Stat errors produce diagnostics (not silent skip)
- Output paths are relative (no absolute path leakage)
- ANSI escapes stripped from messages in no-color mode
- Malformed TOML configs handled gracefully (defaults used)

## Tests

```bash
cd plugin
PYTHONPATH=. python3 -m pytest tests/ -v
# 69+ tests, ~0.15s
```

## Architecture

```
mlgg_lint/
├── cli.py          # CLI: check, rules subcommands
├── engine.py       # File parsing, rule dispatch, noqa, severity filter
├── ast_utils.py    # Import resolution, taint tracking, call matching
├── config.py       # .mlgg-lint.toml discovery and parsing
├── models.py       # Diagnostic, Location, Severity dataclasses
├── formatters.py   # text/JSON/SARIF output
└── rules/
    ├── base.py     # BaseRule (ast.NodeVisitor subclass)
    └── r001–r020   # One file per rule, auto-discovered
```
