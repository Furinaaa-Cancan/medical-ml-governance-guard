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
        return subprocess.run(
            [sys.executable, str(VERIFY_LIVE), *extra_args],
            capture_output=True, text=True, timeout=180,
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
