"""Unit tests for the NCPR v2 PDF-backed paper runner (W23-C2).

Fully offline / deterministic. We mock both the W23-A2 extractor and
the v1 ``synthesize_flags_from_rag`` bridge so no PDF binary, poppler
install, or live KB is required.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest import mock

import pytest

from rag.evals import ncpr_pdf_runner
from rag.evals.ncpr_pdf_runner import (
    DEFAULT_CHUNK_COUNT,
    batch_run_pdfs,
    run_on_pdf,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────────────


_SAMPLE_METHODS = (
    "We used a single-center retrospective cohort of adult patients. "
    "Patients were split 80/20 into train and test sets at random. "
    "Missing values were imputed using the global median. "
    "Hyperparameters were tuned on the test set. "
    "Calibration was not assessed. "
    "No external validation was performed. "
    "Confidence intervals were not reported for any metric. "
    "We used AUROC as the sole evaluation criterion."
)


def _flag(code: str, evidence: str = "x",
          severity: str = "HIGH", category: str = "design") -> dict:
    return {
        "code": code,
        "severity": severity,
        "category": category,
        "evidence_text": evidence,
    }


@pytest.fixture()
def fake_pdf(tmp_path: Path) -> Path:
    """Create a placeholder file the runner will see as a 'real' PDF.

    Content does not matter — the extractor is mocked in every test that
    cares about it.
    """
    p = tmp_path / "paper_42.pdf"
    p.write_bytes(b"%PDF-1.4\n% fake\n")
    return p


# ────────────────────────────────────────────────────────────────────────
# 1. Happy path: single PDF, mocked extractor, mocked RAG
# ────────────────────────────────────────────────────────────────────────


def test_run_on_pdf_happy_path_returns_deduped_flag_list(fake_pdf):
    """Extractor returns real-shaped text → chunks → RAG → deduped flags."""
    # Mock the extractor at the loader so we exercise the import path.
    fake_extract = mock.Mock(return_value=_SAMPLE_METHODS)
    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(fake_extract, False),
    ), mock.patch.object(
        ncpr_pdf_runner, "_flags_for_chunk",
        # Each chunk yields one unique flag + one duplicate "LEAK-01"
        # so the dedupe path is also exercised.
        side_effect=lambda chunk, top_k, **_kwargs: [
            _flag("LEAK-01", evidence=chunk[:20]),
            _flag(f"UNIQ-{hash(chunk) % 1000}"),
        ],
    ):
        result = run_on_pdf("PR-042", fake_pdf, top_k=10)

    assert result["paper_id"] == "PR-042"
    assert result["errors"] == []
    assert isinstance(result["wall_time_s"], float) and result["wall_time_s"] >= 0
    fake_extract.assert_called_once_with(fake_pdf)

    codes = [f["code"] for f in result["flags"]]
    # Exactly one LEAK-01 (duplicate squashed) + one unique per chunk.
    assert codes.count("LEAK-01") == 1
    # We split the sample into ~DEFAULT_CHUNK_COUNT chunks so we expect
    # that many unique non-LEAK codes plus the single LEAK-01.
    expected = 1 + DEFAULT_CHUNK_COUNT
    assert len(codes) == expected


def test_run_on_pdf_excludes_current_paper_on_every_rag_chunk(fake_pdf):
    """PDF-backed NCPR must not retrieve the paper's own KB rows."""
    fake_extract = mock.Mock(return_value=_SAMPLE_METHODS)
    calls: list[dict] = []

    def fake_flags(chunk, top_k, **kwargs):
        calls.append({"chunk": chunk, "top_k": top_k, **kwargs})
        return [_flag("OK")]

    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(fake_extract, False),
    ), mock.patch.object(
        ncpr_pdf_runner,
        "_flags_for_chunk",
        side_effect=fake_flags,
    ):
        result = run_on_pdf("PR-042", fake_pdf, top_k=10)

    assert result["errors"] == []
    assert calls
    assert {tuple(c.get("excluded_paper_ids", [])) for c in calls} == {("PR-042",)}


def test_run_on_pdf_excludes_all_supplied_paper_identifiers(fake_pdf):
    """DOI/alias identifiers must ride along with the primary paper id."""
    fake_extract = mock.Mock(return_value=_SAMPLE_METHODS)
    calls: list[dict] = []

    def fake_flags(chunk, top_k, **kwargs):
        calls.append({"chunk": chunk, "top_k": top_k, **kwargs})
        return [_flag("OK")]

    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(fake_extract, False),
    ), mock.patch.object(
        ncpr_pdf_runner,
        "_flags_for_chunk",
        side_effect=fake_flags,
    ):
        result = run_on_pdf(
            "PR-042",
            fake_pdf,
            top_k=10,
            paper_identifiers=[" 10.1/pdf-doi ", "PR-042", None, ""],
        )

    assert result["errors"] == []
    assert calls
    assert {tuple(c.get("excluded_paper_ids", [])) for c in calls} == {
        ("PR-042", "10.1/pdf-doi"),
    }


# ────────────────────────────────────────────────────────────────────────
# 2. PDF not found → graceful error, no crash
# ────────────────────────────────────────────────────────────────────────


def test_run_on_pdf_missing_file_returns_error_not_exception(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    # Even if the extractor would be called, it must not be — we short-
    # circuit on the file-existence check first.
    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(mock.Mock(side_effect=AssertionError("should not run")), False),
    ):
        result = run_on_pdf("PR-999", missing)

    assert result["paper_id"] == "PR-999"
    assert result["flags"] == []
    assert any("pdf-not-found" in e for e in result["errors"])


# ────────────────────────────────────────────────────────────────────────
# 3. Extraction returns empty → empty flag list, no crash
# ────────────────────────────────────────────────────────────────────────


def test_run_on_pdf_empty_extraction_yields_empty_flags(fake_pdf):
    """Extractor returns ""/whitespace → no chunks, no flags, structured error."""
    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(mock.Mock(return_value="   \n  "), False),
    ), mock.patch.object(
        ncpr_pdf_runner, "_flags_for_chunk",
        side_effect=AssertionError("must not be called when no chunks"),
    ):
        result = run_on_pdf("PR-empty", fake_pdf)

    assert result["flags"] == []
    assert any("extraction-empty" in e for e in result["errors"])


# ────────────────────────────────────────────────────────────────────────
# 4. Batch: one PDF fails, others succeed → batch continues
# ────────────────────────────────────────────────────────────────────────


def test_batch_run_pdfs_continues_past_per_paper_failure(tmp_path):
    good = tmp_path / "good.pdf"
    good.write_bytes(b"%PDF-1.4\n")
    bad = tmp_path / "missing.pdf"  # never created — file-not-found path
    good2 = tmp_path / "good2.pdf"
    good2.write_bytes(b"%PDF-1.4\n")

    fake_extract = mock.Mock(return_value=_SAMPLE_METHODS)
    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(fake_extract, False),
    ), mock.patch.object(
        ncpr_pdf_runner, "_flags_for_chunk",
        side_effect=lambda chunk, top_k, **_kwargs: [_flag("OK-1")],
    ):
        results = batch_run_pdfs(
            {"P1": good, "P2": bad, "P3": good2},
            top_k=5,
        )

    assert set(results.keys()) == {"P1", "P2", "P3"}
    # Successful papers got at least one flag.
    assert results["P1"]["flags"], "P1 should have flags"
    assert results["P3"]["flags"], "P3 should have flags"
    # Failed paper has structured error and zero flags but did NOT crash.
    assert results["P2"]["flags"] == []
    assert any("pdf-not-found" in e for e in results["P2"]["errors"])
    # Successful papers carry no errors.
    assert results["P1"]["errors"] == []
    assert results["P3"]["errors"] == []


def test_batch_run_pdfs_threads_paper_identifiers_to_rag_chunks(tmp_path):
    """Batch PDF runs must preserve DOI/alias self-exclusion for each paper."""
    pdf1 = tmp_path / "p1.pdf"
    pdf1.write_bytes(b"%PDF-1.4\n")
    pdf2 = tmp_path / "p2.pdf"
    pdf2.write_bytes(b"%PDF-1.4\n")
    calls: list[dict] = []

    def fake_flags(chunk, top_k, **kwargs):
        calls.append({"chunk": chunk, "top_k": top_k, **kwargs})
        return [_flag("OK")]

    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(mock.Mock(return_value=_SAMPLE_METHODS), False),
    ), mock.patch.object(
        ncpr_pdf_runner,
        "_flags_for_chunk",
        side_effect=fake_flags,
    ):
        results = batch_run_pdfs(
            {"P1": pdf1, "P2": pdf2},
            top_k=5,
            paper_identifiers_by_id={
                "P1": ["10.1/p1", "P1"],
                "P2": "10.1/p2",
            },
        )

    assert set(results.keys()) == {"P1", "P2"}
    assert results["P1"]["errors"] == []
    assert results["P2"]["errors"] == []
    assert {
        tuple(c.get("excluded_paper_ids", [])) for c in calls
    } == {
        ("P1", "10.1/p1"),
        ("P2", "10.1/p2"),
    }


# ────────────────────────────────────────────────────────────────────────
# 5. Per-paper timeout protection
# ────────────────────────────────────────────────────────────────────────


def test_run_on_pdf_timeout_protection_returns_structured_error(fake_pdf):
    """Extractor that sleeps past the timeout returns a timeout error,
    not an uncaught exception, and the rest of the result is well-formed.
    """
    def slow_extract(_path):
        time.sleep(3.0)
        return _SAMPLE_METHODS  # pragma: no cover — timeout fires first

    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(mock.Mock(side_effect=slow_extract), False),
    ):
        # Timeout is clamped to >=1s inside run_on_pdf; pass 1 to keep
        # the test fast while still proving the timeout fires.
        result = run_on_pdf("PR-slow", fake_pdf, top_k=5, timeout_s=1)

    assert result["paper_id"] == "PR-slow"
    assert result["flags"] == []
    assert any("timeout" in e.lower() for e in result["errors"])
    # Wall-clock should be near the timeout, not the 3s sleep.
    assert result["wall_time_s"] < 2.5


# ────────────────────────────────────────────────────────────────────────
# 6. Stub fallback when W23-A2 is unavailable
# ────────────────────────────────────────────────────────────────────────


def test_run_on_pdf_stub_fallback_surfaces_in_errors(fake_pdf):
    """When W23-A2 is not importable, the stub runs and errors flag it."""
    stub_fn = mock.Mock(return_value=ncpr_pdf_runner._STUB_METHODS_TEXT)
    with mock.patch.object(
        ncpr_pdf_runner, "_load_extractor",
        return_value=(stub_fn, True),
    ), mock.patch.object(
        ncpr_pdf_runner, "_flags_for_chunk",
        side_effect=lambda chunk, top_k, **_kwargs: [_flag("STUB-OK")],
    ):
        result = run_on_pdf("PR-stub", fake_pdf, top_k=5)

    stub_fn.assert_called_once_with(fake_pdf)
    # Stub notice is surfaced — callers must be able to distinguish
    # real-extractor results from stubbed ones.
    assert any("extractor-stub-used" in e for e in result["errors"])
    # Despite the stub notice, real flags came through.
    assert any(f["code"] == "STUB-OK" for f in result["flags"])


# ────────────────────────────────────────────────────────────────────────
# 7. Chunking helper invariants (direct probe)
# ────────────────────────────────────────────────────────────────────────


def test_chunk_methods_text_invariants():
    # Empty / whitespace → []
    assert ncpr_pdf_runner._chunk_methods_text("", 5) == []
    assert ncpr_pdf_runner._chunk_methods_text("   \n  ", 5) == []

    # Fewer sentences than requested chunks → no empty chunks padded out.
    one_sentence = "Only one sentence here."
    out = ncpr_pdf_runner._chunk_methods_text(one_sentence, 5)
    assert out == [one_sentence]

    # Normal case: every chunk non-empty and order preserved.
    chunks = ncpr_pdf_runner._chunk_methods_text(_SAMPLE_METHODS, 5)
    assert len(chunks) == 5
    assert all(c.strip() for c in chunks)
    # Concatenating all chunks should contain every original sentence.
    joined = " ".join(chunks)
    for token in ["80/20", "median", "Calibration", "external validation"]:
        assert token in joined


# ────────────────────────────────────────────────────────────────────────
# 8. batch_run_pdfs: bad arg type is loud
# ────────────────────────────────────────────────────────────────────────


def test_batch_run_pdfs_rejects_non_dict():
    with pytest.raises(TypeError):
        batch_run_pdfs(["not", "a", "dict"])  # type: ignore[arg-type]
