"""Tests for the analysis engine."""

from pathlib import Path

from mlgg_lint.config import LintConfig
from mlgg_lint.engine import analyze_file, analyze_paths

from pathlib import Path as _P

from mlgg_lint.engine import _build_taint_tracker
from mlgg_lint.ast_utils import build_import_map
import ast

SAMPLES_DIR = Path(__file__).parent / "samples"


def check_sample(name, config=None):
    from mlgg_lint.engine import analyze_file
    return analyze_file(SAMPLES_DIR / name, config=config or LintConfig())


def test_r001_bad_has_diagnostics():
    diags = check_sample("r001_bad.py")
    r001 = [d for d in diags if d.rule_id == "R001"]
    assert len(r001) >= 1
    assert "before" in r001[0].message.lower() or "fit" in r001[0].message.lower()


def test_r001_good_no_r001():
    diags = check_sample("r001_good.py")
    r001 = [d for d in diags if d.rule_id == "R001"]
    assert len(r001) == 0


def test_r002_bad_has_diagnostics():
    diags = check_sample("r002_bad.py")
    r002 = [d for d in diags if d.rule_id == "R002"]
    assert len(r002) >= 1
    assert "test" in r002[0].message.lower()


def test_r002_good_no_r002():
    diags = check_sample("r002_good.py")
    r002 = [d for d in diags if d.rule_id == "R002"]
    assert len(r002) == 0


def test_r003_bad_has_diagnostics():
    diags = check_sample("r003_bad.py")
    r003 = [d for d in diags if d.rule_id == "R003"]
    assert len(r003) >= 1


def test_r003_good_no_r003():
    diags = check_sample("r003_good.py")
    r003 = [d for d in diags if d.rule_id == "R003"]
    assert len(r003) == 0


def test_r004_bad_has_diagnostics():
    diags = check_sample("r004_bad.py")
    r004 = [d for d in diags if d.rule_id == "R004"]
    assert len(r004) >= 1
    assert "group" in r004[0].message.lower()


def test_r007_bad_has_diagnostics():
    diags = check_sample("r007_bad.py")
    r007 = [d for d in diags if d.rule_id == "R007"]
    assert len(r007) >= 1


def test_r008_bad_has_diagnostics():
    diags = check_sample("r008_bad.py")
    r008 = [d for d in diags if d.rule_id == "R008"]
    assert len(r008) >= 1
    assert "temporal" in r008[0].message.lower() or "shuffle" in r008[0].message.lower()


def test_r008_good_no_r008():
    diags = check_sample("r008_good.py")
    r008 = [d for d in diags if d.rule_id == "R008"]
    assert len(r008) == 0


def test_r010_bad_has_diagnostics():
    diags = check_sample("r010_bad.py")
    r010 = [d for d in diags if d.rule_id == "R010"]
    assert len(r010) >= 1
    assert "train" in r010[0].message.lower()


def test_disable_rule():
    config = LintConfig(disabled_rules={"R001"})
    diags = check_sample("r001_bad.py", config=config)
    r001 = [d for d in diags if d.rule_id == "R001"]
    assert len(r001) == 0


def test_severity_threshold():
    config = LintConfig(severity_threshold="error")
    diags = check_sample("r008_bad.py", config=config)
    # R008 is WARNING, should be filtered out
    r008 = [d for d in diags if d.rule_id == "R008"]
    assert len(r008) == 0


def test_analyze_directory(tmp_path):
    # Copy a sample to temp dir
    src = SAMPLES_DIR / "r001_bad.py"
    dst = tmp_path / "code.py"
    dst.write_text(src.read_text())
    diags = analyze_paths([tmp_path])
    assert len(diags) > 0


def test_syntax_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def (broken syntax")
    diags = analyze_file(bad)
    assert len(diags) == 1
    assert diags[0].rule_id == "E000"
