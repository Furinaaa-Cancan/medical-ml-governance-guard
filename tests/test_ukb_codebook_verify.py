"""Pins UKB codebook at its verified-complete state.

Any regression (upstream UKB change, stale local copy, DB corruption,
golden-seed field removal) fails CI with a clear pointer to
scripts/codebooks/verify_ukb_codebook.py for details.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "scripts" / "codebooks" / "verify_ukb_codebook.py"
VERIFY_LIVE = REPO_ROOT / "scripts" / "codebooks" / "verify_ukb_against_live.py"
UKB_DIR = REPO_ROOT / "references" / "codebooks" / "ukb"
DB = UKB_DIR / "ukb_codebook.sqlite"


@pytest.mark.skipif(not DB.exists(),
                    reason="UKB SQLite not present — run fetch + build first")
class TestUkbCodebookCompleteness:
    """Three layers, run via the verify script. Failures surface with
    the verify script's own error messages — inspect them directly.
    """

    def _run(self, *extra_args: str):
        return subprocess.run(
            [sys.executable, str(VERIFY), *extra_args],
            capture_output=True, text=True, timeout=60,
        )

    def test_full_verify_clean(self):
        """Combined L1 + L2 + L3 — the canonical gate."""
        r = self._run()
        assert r.returncode == 0, (
            f"UKB codebook verification failed.\n"
            f"Run: python3 scripts/codebooks/verify_ukb_codebook.py\n"
            f"stdout:\n{r.stdout}\n"
            f"stderr:\n{r.stderr}"
        )

    def test_source_manifest_pinned(self):
        """L1 alone — every .txt file matches its committed sha256."""
        r = self._run("--skip-l3")
        assert r.returncode == 0, (
            f"UKB source-file drift detected.\n{r.stdout}"
        )

    def test_golden_fields_present(self):
        """L3 alone — every golden seed survives."""
        r = self._run("--skip-l1")
        assert r.returncode == 0, (
            f"UKB golden-seed field regression.\n{r.stdout}"
        )

    def test_full_cell_by_cell_faithfulness(self):
        """L2c — strongest "no hallucination" guarantee.

        Compares every persisted cell of every source row against the
        DB. Runs ~3s. If any source→DB divergence exists (column swap,
        string mangling, silent drop), this fails loudly.
        """
        r = subprocess.run(
            [sys.executable, str(VERIFY), "--full-faithfulness"],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, (
            f"UKB codebook NOT faithful to source .txt files.\n"
            f"Run: python3 scripts/codebooks/verify_ukb_codebook.py --full-faithfulness\n"
            f"stdout:\n{r.stdout}\n"
        )


@pytest.mark.skipif(not DB.exists(),
                    reason="UKB SQLite not present")
class TestUkbDocumentedGaps:
    """Verify KNOWN_GAPS.md statements still reflect reality.

    If upstream UKB adds Olink NPX as individual fields, or if we
    start covering WES/WGS, this test fails — intentionally — so
    the gap doc gets updated instead of silently becoming wrong.
    """

    def test_olink_npx_still_only_metadata(self):
        import sqlite3
        with sqlite3.connect(str(DB)) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM fields WHERE main_category=1839;"
            )
            n = cur.fetchone()[0]
        assert n <= 20, (
            f"Olink cat 1839 field count jumped to {n}. "
            "Good news — UKB may be releasing NPX via Showcase directly. "
            "Update KNOWN_GAPS.md and consider extending golden-seed."
        )

    def test_nmr_cat_220_exactly_251_fields(self):
        import sqlite3
        with sqlite3.connect(str(DB)) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM fields WHERE main_category=220;"
            )
            n = cur.fetchone()[0]
        assert n == 251, f"NMR cat 220 has {n} fields, expected 251."


@pytest.mark.skipif(not DB.exists(), reason="UKB SQLite not present")
class TestContentFacetHashes:
    """Meta-review layer: content-facet hashes.

    classify_field() rule changes routinely shift thousands of field
    classifications. L1 pins upstream .txt files; L2 pins specific
    counts/facts; neither can see "1000 fields quietly moved from
    baseline to online_followup". These four hashes make every such
    shift visible in CI logs and support optional strict pinning via
    source_manifest.json's content_hashes block.
    """

    def test_compute_is_deterministic(self):
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import compute_content_hashes
        with sqlite3.connect(str(DB)) as conn:
            a = compute_content_hashes(conn)
        with sqlite3.connect(str(DB)) as conn:
            b = compute_content_hashes(conn)
        assert a == b, "compute_content_hashes must be deterministic across runs"

    def test_four_facets_with_hex_sha256(self):
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import compute_content_hashes
        with sqlite3.connect(str(DB)) as conn:
            h = compute_content_hashes(conn)
        assert set(h.keys()) == {
            "source_titles", "classification", "encoding_values", "aliases",
        }
        for key, value in h.items():
            assert len(value) == 64, f"{key}: expected 64-char sha256, got {len(value)}"
            int(value, 16)  # must be valid hex — raises ValueError otherwise

    def test_print_flag_outputs_pasteable_json(self):
        r = subprocess.run(
            [sys.executable, str(VERIFY), "--print-content-hashes"],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr
        import json
        payload = json.loads(r.stdout)
        assert "content_hashes" in payload
        assert set(payload["content_hashes"].keys()) == {
            "source_titles", "classification", "encoding_values", "aliases",
        }

    def test_drift_detection_against_fake_manifest(self, tmp_path):
        # Write a manifest with deliberately WRONG pinned hashes; drift
        # detection must report all four facets as drifted.
        import json
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import (
            compute_content_hashes, check_content_hash_drift,
        )
        with sqlite3.connect(str(DB)) as conn:
            computed = compute_content_hashes(conn)
        fake_manifest = tmp_path / "manifest.json"
        fake_manifest.write_text(json.dumps({
            "content_hashes": {k: "0" * 64 for k in computed},
        }))
        warnings, detail = check_content_hash_drift(computed, fake_manifest)
        assert len(warnings) == 4
        assert all("drifted to" in w for w in warnings)

    def test_no_drift_when_manifest_lacks_content_hashes(self, tmp_path):
        # Manifest without a content_hashes block → no warnings, no drift.
        # Supports the rollout path where content hashes are reported for
        # a while before the user decides to pin them.
        import json
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import (
            compute_content_hashes, check_content_hash_drift,
        )
        with sqlite3.connect(str(DB)) as conn:
            computed = compute_content_hashes(conn)
        unpinned_manifest = tmp_path / "manifest.json"
        unpinned_manifest.write_text(json.dumps({"files": {}}))
        warnings, detail = check_content_hash_drift(computed, unpinned_manifest)
        assert warnings == []
        assert detail["pinned"] == {}

    def test_source_manifest_has_content_hashes_pinned(self):
        """Once pinned, future commits must keep the four facets pinned.

        If someone removes the content_hashes block entirely,
        --strict-content-hashes silently degrades to a no-op because
        check_content_hash_drift returns no warnings for unpinned
        facets. This test catches that regression.
        """
        import json
        manifest = json.loads(
            (REPO_ROOT / "references" / "codebooks" / "ukb" / "source_manifest.json")
            .read_text()
        )
        assert "content_hashes" in manifest, (
            "source_manifest.json lost its content_hashes block — pinning "
            "was intentional; regenerate via --print-content-hashes."
        )
        assert set(manifest["content_hashes"].keys()) == {
            "source_titles", "classification", "encoding_values", "aliases",
        }
        for key, h in manifest["content_hashes"].items():
            assert isinstance(h, str) and len(h) == 64, (
                f"content_hashes[{key!r}] is not a 64-char sha256: {h!r}"
            )

    def test_strict_flag_exits_nonzero_on_drift(self, tmp_path):
        """--strict-content-hashes must make drift a hard failure.

        Builds a fake manifest with wrong content_hashes and empty
        `files` block (so L1 passes vacuously with --skip-l1), points
        verify at it with --strict-content-hashes, asserts exit 2.
        """
        import json
        fake = tmp_path / "fake_manifest.json"
        fake.write_text(json.dumps({
            "schema_version": "fake",
            "content_hashes": {
                "source_titles":   "0" * 64,
                "classification":  "0" * 64,
                "encoding_values": "0" * 64,
                "aliases":         "0" * 64,
            },
            "files": {},
        }))
        r = subprocess.run(
            [sys.executable, str(VERIFY),
             "--manifest", str(fake),
             "--skip-l1", "--skip-l3", "--skip-disease-kb",
             "--strict-content-hashes"],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 2, (
            f"expected strict drift to exit 2, got {r.returncode}\n"
            f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        assert "content-hash" in r.stdout, (
            "drift was not reported as a content-hash issue"
        )


@pytest.mark.skipif(not DB.exists(), reason="UKB SQLite not present")
class TestVerifierSilentFailureGuards:
    """Round-9 strict-review regression guards — L3 must loudly fail
    on three silent-failure shapes that previously returned ✅:
      - empty / all-comments YAML (None parse → silent fallback to [])
      - wrong top-level structure (dict instead of list)
      - per-entry typo key (e.g., 'field_idx' silently skipped)
      - entry count dropping below committed floor
    """

    def test_empty_golden_file_raises(self, tmp_path):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import _load_golden
        empty = tmp_path / "empty.yaml"
        empty.write_text("# just comments\n")
        with pytest.raises(ValueError, match="empty|all-comments"):
            _load_golden(empty)

    def test_non_list_golden_file_raises(self, tmp_path):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import _load_golden
        as_dict = tmp_path / "as_dict.yaml"
        as_dict.write_text("field_id: 21001\n")  # valid YAML, but a dict
        with pytest.raises(ValueError, match="expected list"):
            _load_golden(as_dict)

    def test_unknown_yaml_key_surfaces_issue(self, tmp_path):
        """A typo like 'field_idx' used to silently skip the entry.
        Now it must produce an issue."""
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import check_golden_fields
        typo_file = tmp_path / "typo.yaml"
        typo_file.write_text("- field_idx: 21001\n  title: Body mass index (BMI)\n")
        with sqlite3.connect(str(DB)) as conn:
            issues, detail = check_golden_fields(conn, typo_file)
        assert any("unknown key" in i for i in issues), (
            f"Typo 'field_idx' should surface as issue, got: {issues}"
        )

    def test_below_floor_surfaces_issue(self, tmp_path):
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "codebooks"))
        from verify_ukb_codebook import check_golden_fields
        skinny = tmp_path / "skinny.yaml"
        skinny.write_text("- field_id: 21001\n")
        with sqlite3.connect(str(DB)) as conn:
            issues, _ = check_golden_fields(conn, skinny)
        assert any("below floor" in i or "floor" in i for i in issues), (
            f"A 1-entry golden file should fail the _GOLDEN_MIN_ENTRIES "
            f"floor guard. Got: {issues}"
        )


@pytest.mark.skipif(
    not DB.exists() or os.environ.get("MLGG_UKB_LIVE_CHECK") != "1",
    reason="L4 live UKB check is opt-in; set MLGG_UKB_LIVE_CHECK=1 to run",
)
class TestUkbLiveCrossCheck:
    """L4 — external authority layer.

    Hits the live UKB Showcase to catch drift that L1-L3 cannot see:
      - upstream .txt files changed since our last fetch
      - a build-time transform silently lost/corrupted field metadata

    Network-bound and slow (~20s), so disabled by default. Enable with
    `MLGG_UKB_LIVE_CHECK=1 pytest tests/test_ukb_codebook_verify.py`
    before publication-grade runs.
    """

    def _run(self, *extra_args: str):
        # 360s: schema-drift check downloads 11 .txt files (up to
        # 18 MB each for esimpstring). UKB connection speed varies;
        # 180s was tight enough to trip on slow days even when the
        # content was fine. Separate network flakiness from correctness.
        return subprocess.run(
            [sys.executable, str(VERIFY_LIVE), *extra_args],
            capture_output=True, text=True, timeout=360,
        )

    def test_schema_files_identical_to_live(self):
        """11/11 .txt sha256 must match live UKB Showcase."""
        r = self._run("--schema-only")
        assert r.returncode == 0, (
            f"L4 schema-drift detected vs live UKB.\n{r.stdout}\n{r.stderr}"
        )

    def test_golden_seed_fields_match_live_pages(self):
        """Probe fields must have identical title + category on UKB."""
        r = self._run("--field-only", "--pause", "0.2")
        assert r.returncode == 0, (
            f"L4 field-page mismatch vs live UKB.\n{r.stdout}\n{r.stderr}"
        )
