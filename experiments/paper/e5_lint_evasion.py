#!/usr/bin/env python3
"""
E5: Lint rule evasion test suite.

Tests whether MLGG lint rules can detect leakage when code uses
common real-world patterns that might bypass detection:
  1. Function boundary isolation
  2. Variable aliasing/renaming
  3. Conditional branches
  4. Pipeline wrapping
  5. Import-based utilities
  6. Loop-based processing

For each evasion pattern, generates a synthetic Python file,
runs MLGG lint, and records whether the leakage was detected.

Usage:
  python3 experiments/paper/e5_lint_evasion.py
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LINT_CMD = [
    "python3", str(REPO_ROOT / "scripts" / "mlgg.py"),
    "lint", "check", "--format", "json",
]


def run_lint(code: str) -> dict:
    """Write code to temp file, run MLGG lint, return results."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        path = f.name

    try:
        result = subprocess.run(
            LINT_CMD + [path],
            capture_output=True, text=True, timeout=30,
        )
        try:
            stdout = result.stdout.strip()
            # mlgg.py may append a command echo line; truncate at last ']'
            end = stdout.rfind("]")
            if end >= 0:
                stdout = stdout[: end + 1]
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"error": "parse_failed", "stdout": result.stdout[:500], "stderr": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    finally:
        Path(path).unlink(missing_ok=True)


def extract_rules(lint_result) -> set:
    """Extract fired rule IDs from lint result."""
    rules = set()
    if isinstance(lint_result, list):
        for finding in lint_result:
            if isinstance(finding, dict) and "rule_id" in finding:
                rules.add(finding["rule_id"])
    elif isinstance(lint_result, dict):
        if "error" in lint_result:
            return rules
        for file_results in lint_result.values():
            if isinstance(file_results, list):
                for finding in file_results:
                    if isinstance(finding, dict):
                        rules.add(finding.get("rule_id") or finding.get("rule", ""))
    return rules


# --------------------------------------------------------------------------
# Evasion patterns
# --------------------------------------------------------------------------

TESTS = []


def test(name: str, target_rule: str, should_detect: bool, code: str):
    TESTS.append({
        "name": name,
        "target_rule": target_rule,
        "should_detect": should_detect,
        "code": textwrap.dedent(code).strip(),
    })


# --- BASELINE: Direct patterns (should be detected) ---

test("baseline_R001_direct_fit_before_split", "R001", True, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)
""")

test("baseline_R002_direct_fit_on_test", "R002", True, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    scaler = StandardScaler()
    scaler.fit(X_test)
""")

test("baseline_R006_feature_selection_full", "R006", True, """
    import pandas as pd
    from sklearn.feature_selection import SelectKBest, f_classif
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    selector = SelectKBest(f_classif, k=10)
    X_selected = selector.fit_transform(X, y)

    X_train, X_test, y_train, y_test = train_test_split(X_selected, y, test_size=0.2)
""")

# --- EVASION 1: Function boundary ---

test("evasion_function_boundary_R001", "R001", False, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    def preprocess(X):
        scaler = StandardScaler()
        return scaler.fit_transform(X)

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    X_scaled = preprocess(X)
    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)
""")

test("evasion_function_boundary_R006", "R006", False, """
    import pandas as pd
    from sklearn.feature_selection import SelectKBest, f_classif
    from sklearn.model_selection import train_test_split

    def select_features(X, y, k=10):
        selector = SelectKBest(f_classif, k=k)
        return selector.fit_transform(X, y)

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    X_selected = select_features(X, y)
    X_train, X_test, y_train, y_test = train_test_split(X_selected, y, test_size=0.2)
""")

# --- EVASION 2: Variable aliasing ---

test("evasion_alias_R002", "R002", False, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    holdout_data = X_test  # Alias to obscure identity
    scaler = StandardScaler()
    scaler.fit(holdout_data)
""")

test("evasion_alias_R010", "R010", False, """
    import pandas as pd
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split
    from sklearn.linear_model import LogisticRegression

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    clf = LogisticRegression()
    clf.fit(X_train, y_train)

    train_labels = y_train  # Alias
    train_predictions = clf.predict(X_train)
    final_accuracy = accuracy_score(train_labels, train_predictions)
""")

# --- EVASION 3: Pipeline wrapping ---

test("evasion_pipeline_R001", "R001", False, """
    import pandas as pd
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    # Fit pipeline on full data (leakage!), then split
    pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression())])
    pipe.fit(X, y)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
""")

# --- EVASION 4: Conditional branches ---

test("evasion_conditional_R001", "R001", False, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    USE_GLOBAL_SCALING = True
    if USE_GLOBAL_SCALING:
        scaler = StandardScaler()
        X = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
""")

# --- EVASION 5: Loop-based processing ---

test("evasion_loop_R002", "R002", False, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    datasets = [X_train, X_test]
    for data in datasets:
        scaler = StandardScaler()
        scaler.fit(data)  # Fits on test in second iteration
""")

# --- EVASION 6: Method chaining ---

test("evasion_chaining_R020", "R020", False, """
    import pandas as pd
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")

    # Chain fillna with computed mean (leakage) in one line
    df_clean = df.assign(**{col: df[col].fillna(df[col].mean()) for col in df.select_dtypes(include="number").columns})

    X = df_clean.drop(columns=["y"])
    y = df_clean["y"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
""")

# --- CORRECT CODE: Should NOT trigger (false positive check) ---

test("correct_R001_fit_after_split", "R001", False, """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
""")

test("correct_R007_drop_target", "R007", False, """
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    df = pd.read_csv("data.csv")
    X = df.drop(columns=["y"])
    y = df["y"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    clf = LogisticRegression()
    clf.fit(X_train, y_train)
""")


def main() -> None:
    print("E5: LINT RULE EVASION TEST SUITE")
    print("=" * 70)

    results = []
    n_pass = n_fail = n_unexpected = 0

    for t in TESTS:
        lint_result = run_lint(t["code"])
        fired = extract_rules(lint_result)
        target = t["target_rule"]
        detected = target in fired

        if t["should_detect"]:
            # Expected: rule fires
            if detected:
                status = "✓ DETECTED"
                n_pass += 1
            else:
                status = "✗ MISSED (expected detection)"
                n_fail += 1
        else:
            # Expected: rule does NOT fire (evasion or correct code)
            if not detected:
                if "evasion" in t["name"]:
                    status = "⚠ EVADED (as expected)"
                    n_pass += 1
                else:
                    status = "✓ NO FALSE POSITIVE"
                    n_pass += 1
            else:
                if "evasion" in t["name"]:
                    status = "★ CAUGHT (better than expected!)"
                    n_unexpected += 1
                else:
                    status = "✗ FALSE POSITIVE"
                    n_fail += 1

        result = {
            "name": t["name"],
            "target_rule": target,
            "should_detect": t["should_detect"],
            "detected": detected,
            "all_rules_fired": sorted(fired),
            "status": status,
        }
        results.append(result)
        print(f"  {status:<35} {t['name']}")

    print(f"\n{'='*70}")
    print(f"SUMMARY: {n_pass} pass, {n_fail} fail, {n_unexpected} unexpected catches")
    print(f"{'='*70}")

    # Categorize
    baseline_tests = [r for r in results if r["name"].startswith("baseline")]
    evasion_tests = [r for r in results if r["name"].startswith("evasion")]
    correct_tests = [r for r in results if r["name"].startswith("correct")]

    baseline_detected = sum(1 for r in baseline_tests if r["detected"])
    evasion_evaded = sum(1 for r in evasion_tests if not r["detected"])
    correct_clean = sum(1 for r in correct_tests if not r["detected"])

    print(f"\nBaseline detection:   {baseline_detected}/{len(baseline_tests)} detected")
    print(f"Evasion success:      {evasion_evaded}/{len(evasion_tests)} evaded")
    print(f"False positive check: {correct_clean}/{len(correct_tests)} clean")

    summary = {
        "total_tests": len(results),
        "pass": n_pass,
        "fail": n_fail,
        "unexpected_catches": n_unexpected,
        "baseline_detection_rate": f"{baseline_detected}/{len(baseline_tests)}",
        "evasion_rate": f"{evasion_evaded}/{len(evasion_tests)}",
        "false_positive_rate": f"{len(correct_tests) - correct_clean}/{len(correct_tests)}",
        "tests": results,
    }

    out = OUTPUT_DIR / "e5_lint_evasion.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
