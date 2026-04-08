"""Tests for scripts/tools/init_guide.py.

Focused on: .mlgg/ directory creation, rules.json structure, CLAUDE.md
generation, --force overwrite, CLI --help, and metric naming consistency.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TOOL_SCRIPT = SCRIPTS_DIR / "tools" / "init_guide.py"

sys.path.insert(0, str(SCRIPTS_DIR / "core"))
sys.path.insert(0, str(SCRIPTS_DIR / "tools"))

import init_guide as ig


# ── .mlgg/ directory with rules.json ─────────────────────────────────────────

class TestMlggDirectory:
    def test_main_creates_mlgg_dir(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path)]
        rc = ig.main()
        assert rc == 0
        assert (tmp_path / ".mlgg").is_dir()

    def test_rules_json_exists(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        rules_path = tmp_path / ".mlgg" / "rules.json"
        assert rules_path.exists()

    def test_checklist_exists(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        assert (tmp_path / ".mlgg" / "checklist.md").exists()

    def test_examples_dir_exists(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        examples = tmp_path / ".mlgg" / "examples"
        assert examples.is_dir()
        assert (examples / "bad_leaky_pipeline.py").exists()
        assert (examples / "good_publication_grade.py").exists()


# ── rules.json structure ─────────────────────────────────────────────────────

class TestRulesJson:
    @pytest.fixture()
    def rules_data(self, tmp_path: Path) -> dict:
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        rules_path = tmp_path / ".mlgg" / "rules.json"
        return json.loads(rules_path.read_text(encoding="utf-8"))

    def test_valid_json(self, rules_data: dict):
        assert isinstance(rules_data, dict)

    def test_has_contract_version(self, rules_data: dict):
        assert "contract_version" in rules_data
        assert rules_data["contract_version"] == "mlgg_rules.v1"

    def test_has_rules_list(self, rules_data: dict):
        assert "rules" in rules_data
        assert isinstance(rules_data["rules"], list)
        assert len(rules_data["rules"]) > 0

    def test_total_rules_matches(self, rules_data: dict):
        assert rules_data["total_rules"] == len(rules_data["rules"])

    def test_severity_counts(self, rules_data: dict):
        counts = rules_data["severity_counts"]
        assert "CRITICAL" in counts
        assert "WARNING" in counts
        total = sum(counts.values())
        assert total == rules_data["total_rules"]

    def test_each_rule_has_required_fields(self, rules_data: dict):
        required = {"id", "category", "severity", "name", "rule", "rule_en"}
        for rule in rules_data["rules"]:
            missing = required - set(rule.keys())
            assert not missing, f"Rule {rule.get('id', '?')} missing fields: {missing}"

    def test_rule_ids_unique(self, rules_data: dict):
        ids = [r["id"] for r in rules_data["rules"]]
        assert len(ids) == len(set(ids)), "Duplicate rule IDs found"


# ── CLAUDE.md generation ─────────────────────────────────────────────────────

class TestClaudeMd:
    def test_claude_md_created(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text(encoding="utf-8")
        assert "MLGG" in content

    def test_no_claude_md_flag(self, tmp_path: Path):
        sys.argv = ["prog", "--output", str(tmp_path), "--no-claude-md"]
        ig.main()
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_append_to_existing_claude_md(self, tmp_path: Path):
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("# My Project\n\nSome content.\n", encoding="utf-8")
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        content = existing.read_text(encoding="utf-8")
        assert "My Project" in content
        assert "MLGG" in content


# ── --force overwrites existing files ────────────────────────────────────────

class TestForceOverwrite:
    def test_without_force_returns_nonzero(self, tmp_path: Path):
        mlgg_dir = tmp_path / ".mlgg"
        mlgg_dir.mkdir()
        sys.argv = ["prog", "--output", str(tmp_path)]
        rc = ig.main()
        assert rc != 0, "Should refuse to overwrite without --force"

    def test_force_overwrites(self, tmp_path: Path):
        # First run
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        # Modify rules.json to verify overwrite
        rules_path = tmp_path / ".mlgg" / "rules.json"
        rules_path.write_text("{}", encoding="utf-8")
        # Second run with --force
        sys.argv = ["prog", "--output", str(tmp_path), "--force"]
        rc = ig.main()
        assert rc == 0
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        assert "rules" in data, "rules.json was not overwritten by --force"


# ── Metric naming consistency: roc_auc not auroc ─────────────────────────────

class TestMetricNaming:
    def test_rules_reference_roc_auc(self, tmp_path: Path):
        """Generated rules should use 'roc_auc' metric naming, not 'auroc'."""
        sys.argv = ["prog", "--output", str(tmp_path)]
        ig.main()
        rules_path = tmp_path / ".mlgg" / "rules.json"
        content = rules_path.read_text(encoding="utf-8")
        data = json.loads(content)
        # Check good_example code snippets use roc_auc_score (sklearn naming)
        good_examples = [r.get("good_example", "") for r in data["rules"]]
        examples_with_auc = [e for e in good_examples if "auc" in e.lower()]
        for ex in examples_with_auc:
            if "roc_auc" in ex or "roc_auc_score" in ex:
                # Uses sklearn-standard naming -- good
                continue
            # Allow "auroc" only in dict key context for metric panels
            # but the sklearn function calls must be roc_auc_score
            assert "auroc" not in ex.replace("'auroc'", "").replace('"auroc"', ""), (
                f"Example uses 'auroc' outside dict key context: {ex[:80]}..."
            )


# ── CLI --help smoke test ────────────────────────────────────────────────────

class TestCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "output" in result.stdout.lower()
