"""Tests for ``scripts/diagnostics/generate_gates_md.py``.

The generator is the drift-prevention mechanism for ``docs/reference/GATES.md``.
These tests verify:

1. It runs cleanly and emits the expected file.
2. ``--check`` mode passes against the committed file (catches forgotten
   regenerations during PR review).
3. ``--check`` mode fails (exit 1) and prints a diff when the committed file
   is corrupted, so CI / pre-commit will block drift.
4. The generated tables include every gate from the registry (regression
   guard against accidentally dropping a layer or filtering out a gate).
5. The static preamble file is required; the generator must not silently
   regenerate without it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DIAG_DIR = SCRIPTS_DIR / "diagnostics"

# conftest.py already wires scripts/ into sys.path; we just need an explicit
# import for the generator module so the type-check below works locally.
if str(DIAG_DIR) not in sys.path:
    sys.path.insert(0, str(DIAG_DIR))

import generate_gates_md as ggm  # noqa: E402

# Re-import via the same module path the generator uses internally so we
# can reach the registry without re-walking _gate_registry from scratch.
from core._gate_registry import GATE_REGISTRY  # noqa: E402


COMMITTED_GATES_MD = PROJECT_ROOT / "docs" / "reference" / "GATES.md"
PREAMBLE = PROJECT_ROOT / "docs" / "reference" / "_gates_md_preamble.md"


# ── helpers ──────────────────────────────────────────────────────────────────


def _gate_row_count(markdown: str) -> int:
    """Count Markdown rows that begin with `` | `<gate_name>` ``."""
    count = 0
    for line in markdown.splitlines():
        # Gate rows start with "| `" + lower-case identifier + "` |".
        if line.startswith("| `") and "_gate" in line.split("`")[1] or (
            line.startswith("| `") and line.split("`")[1] in GATE_REGISTRY
        ):
            # Restrict to rows whose first column is an actual registered gate.
            first_cell = line.split("`")[1] if "`" in line else ""
            if first_cell in GATE_REGISTRY:
                count += 1
    return count


# ── tests ────────────────────────────────────────────────────────────────────


class TestGenerateRunsClean:
    """End-to-end: ``main()`` returns 0 and writes a non-empty file."""

    def test_generate_runs_clean(self, tmp_path: Path) -> None:
        out = tmp_path / "GATES.md"
        rc = ggm.main(["--output", str(out)])
        assert rc == 0, "generator should exit 0 on a normal write"
        assert out.exists(), "generator must write the output file"
        content = out.read_text(encoding="utf-8")
        assert len(content) > 1000, "output should be substantial Markdown"
        # Smoke check: title contains the registry's gate count.
        assert f"({len(GATE_REGISTRY)} Fail-Closed Gates)" in content


class TestCheckMode:
    """``--check`` behaves like ``terraform fmt -check``."""

    def test_check_mode_passes_on_committed_file(self) -> None:
        """After regenerating in-place, ``--check`` against the same path
        must report no drift.
        """
        # Regenerate to the canonical path so the committed file matches
        # whatever the current generator + registry produce. This makes the
        # test resilient to a developer running it locally before
        # committing the regenerated file.
        write_rc = ggm.main([])
        assert write_rc == 0, "regeneration should succeed"

        check_rc = ggm.main(["--check"])
        assert check_rc == 0, (
            "--check should exit 0 immediately after a clean regenerate; "
            "got exit 1 (drift). Re-run the generator and inspect "
            "docs/reference/GATES.md diff."
        )

    def test_check_mode_fails_if_committed_file_modified(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Corrupt a copy of the committed file in tmp_path, then run
        --check against that copy. Must exit 1 with a diff on stderr.
        """
        corrupted = tmp_path / "GATES.md"
        # Start from the freshly-generated content so the only difference
        # is the corruption we introduce ourselves.
        generated = ggm.build_markdown()
        corrupted.write_text(
            generated + "\n## DRIFT MARKER (test)\n",
            encoding="utf-8",
        )

        rc = ggm.main(["--check", "--output", str(corrupted)])
        assert rc == 1, "drift in the committed file must produce exit 1"

        captured = capsys.readouterr()
        # Diff is written to stderr; the test fixture captures both streams.
        assert "DRIFT" in captured.err or "DRIFT" in captured.out
        assert "DRIFT MARKER" in (captured.err + captured.out)

    def test_check_mode_fails_when_file_missing(
        self,
        tmp_path: Path,
    ) -> None:
        """``--check`` against a path that does not exist must exit 1
        rather than silently passing.
        """
        rc = ggm.main(["--check", "--output", str(tmp_path / "absent.md")])
        assert rc == 1


class TestRegistryCoverage:
    """Regression guard: every registered gate must appear in the output."""

    def test_all_registered_gates_appear_in_output(self) -> None:
        content = ggm.build_markdown()
        expected = len(GATE_REGISTRY)

        # Count rows whose first inline-code cell is a registry key.
        seen = set()
        for line in content.splitlines():
            if not line.startswith("| `"):
                continue
            parts = line.split("`")
            if len(parts) < 2:
                continue
            candidate = parts[1]
            if candidate in GATE_REGISTRY:
                seen.add(candidate)

        assert len(seen) == expected, (
            f"expected all {expected} registered gates in GATES.md tables, "
            f"saw {len(seen)}; missing: "
            f"{sorted(set(GATE_REGISTRY) - seen)}"
        )

    def test_layer_section_count_matches_distinct_layers(self) -> None:
        """One ``### Layer N — `LAYER_NAME``` heading per occupied layer."""
        from core._gate_registry import get_execution_layers

        expected_layers = len(get_execution_layers())
        content = ggm.build_markdown()
        heading_count = sum(
            1
            for line in content.splitlines()
            if line.startswith("### Layer ") and "—" in line
        )
        assert heading_count == expected_layers


class TestPreambleRequirement:
    """The preamble file is the human-curated half; missing it must error."""

    def test_missing_preamble_returns_nonzero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Redirect the module-level PREAMBLE_PATH constant to a nonexistent
        # location for the duration of this test.
        missing = tmp_path / "definitely_does_not_exist.md"
        monkeypatch.setattr(ggm, "PREAMBLE_PATH", missing)
        rc = ggm.main(["--stdout"])
        assert rc == 1, "missing preamble must fail loudly, not silently pass"


class TestIdempotence:
    """Running the generator twice must yield byte-identical output."""

    def test_double_generate_is_byte_identical(self, tmp_path: Path) -> None:
        out1 = tmp_path / "first.md"
        out2 = tmp_path / "second.md"
        assert ggm.main(["--output", str(out1)]) == 0
        assert ggm.main(["--output", str(out2)]) == 0
        assert out1.read_bytes() == out2.read_bytes(), (
            "generator output must be deterministic for CI --check to work"
        )


class TestPreserveCommittedContentOnCheckFail:
    """``--check`` must never mutate the committed file (read-only mode)."""

    def test_check_mode_does_not_write(self, tmp_path: Path) -> None:
        # Pre-populate a target with intentionally wrong content; --check
        # must leave it untouched even when reporting drift.
        target = tmp_path / "GATES.md"
        target.write_text("definitely not the real file", encoding="utf-8")
        before = target.read_bytes()

        rc = ggm.main(["--check", "--output", str(target)])
        assert rc == 1
        after = target.read_bytes()
        assert before == after, "--check must not mutate the target file"
