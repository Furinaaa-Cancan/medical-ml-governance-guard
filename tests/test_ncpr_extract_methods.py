"""Unit tests for the NCPR v2 PDF methods extractor (W23-A2).

All tests are offline and deterministic. ``subprocess.run`` and
``shutil.which`` are monkeypatched so we never invoke a real pdftotext
binary or read a real PDF — this keeps the test green on CI hosts that
do not have poppler installed (and matches the rest of the NCPR test
suite, see ``test_ncpr_paper_runner.py``).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from rag.evals.ncpr_extract_methods_from_pdf import (
    MethodsExtractError,
    extract_for_paper_ids,
    extract_methods_section,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


def _fake_completed(stdout: str, returncode: int = 0, stderr: str = "") -> object:
    """Build a ``subprocess.CompletedProcess`` lookalike with bytes attrs."""
    return mock.Mock(
        stdout=stdout.encode("utf-8"),
        stderr=stderr.encode("utf-8"),
        returncode=returncode,
    )


@pytest.fixture()
def dummy_pdf(tmp_path: Path) -> Path:
    """A zero-byte placeholder file that just needs to exist on disk.

    ``extract_methods_section`` checks ``is_file()`` before exec; what
    pdftotext returns is fully controlled by the mock so the bytes do
    not matter.
    """
    p = tmp_path / "paper.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


# Plausible Methods-bearing pdftotext output. The blank lines around
# the headers matter -- our regex anchors on line boundaries.
_METHODS_BODY = (
    "We retrospectively assembled an EHR cohort of 12,345 adult patients\n"
    "from a single tertiary hospital between 2015 and 2022. Patients were\n"
    "split 70/15/15 by patient ID into train/validation/test partitions.\n"
    "XGBoost (n_estimators=500) was tuned on the validation fold via\n"
    "5-fold cross-validation; final hyperparameters were locked before\n"
    "test-set evaluation. Calibration was assessed using the integrated\n"
    "calibration index. Missing data were handled with multiple\n"
    "imputation (m=5).\n"
)

_FAKE_PDF_TEXT = (
    "Title of the Paper\n"
    "\n"
    "Abstract\n"
    "We propose XYZ. Brief background, brief results.\n"
    "\n"
    "Introduction\n"
    "Background motivation here.\n"
    "\n"
    "Methods\n"
    f"{_METHODS_BODY}"
    "\n"
    "Results\n"
    "The model achieved AUROC 0.91 on test.\n"
    "\n"
    "Discussion\n"
    "We discuss limitations.\n"
    "\n"
    "References\n"
    "[1] Smith et al. 2020.\n"
)


# ────────────────────────────────────────────────────────────────────────
# extract_methods_section — happy path + failure modes
# ────────────────────────────────────────────────────────────────────────


def test_extract_methods_happy_path(dummy_pdf, monkeypatch):
    """Mocked pdftotext returns a paper with a Methods section -> we get it."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(_FAKE_PDF_TEXT),
    )

    out = extract_methods_section(dummy_pdf)

    # Body text is present; downstream Results/Discussion is NOT.
    assert "EHR cohort of 12,345" in out
    assert "5-fold cross-validation" in out
    assert "AUROC 0.91" not in out, "Results section must be excluded"
    assert "We discuss limitations" not in out, "Discussion must be excluded"
    assert "Smith et al" not in out, "References must be excluded"


def test_extract_methods_pdftotext_missing(dummy_pdf, monkeypatch):
    """No pdftotext on PATH -> MethodsExtractError with install hint."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(MethodsExtractError) as exc:
        extract_methods_section(dummy_pdf)
    msg = str(exc.value)
    assert "pdftotext" in msg
    assert "poppler" in msg.lower(), "error must hint how to install"


def test_extract_methods_no_methods_section(dummy_pdf, monkeypatch):
    """PDF text with no Methods header anywhere -> MethodsExtractError."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    no_methods_text = (
        "Title\n\nAbstract\nSome abstract text.\n\n"
        "Results\nWe found X.\n\nDiscussion\nWe argue Y.\n"
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(no_methods_text),
    )

    with pytest.raises(MethodsExtractError) as exc:
        extract_methods_section(dummy_pdf)
    assert "no Methods section" in str(exc.value)


def test_extract_methods_multiple_headers_first_wins(dummy_pdf, monkeypatch):
    """Two methods-like headers -> only text following the first is returned."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    text = (
        "Abstract\nAbstract content.\n\n"
        "Methods\n"
        "FIRST methods body talking about cohort assembly.\n\n"
        "Results\n"
        "We report AUROC 0.87.\n\n"
        "Materials and Methods\n"
        "SECOND duplicate methods body (supplementary appendix style).\n\n"
        "Discussion\n"
        "Limitations.\n"
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(text),
    )

    out = extract_methods_section(dummy_pdf)
    assert "FIRST methods body" in out
    assert "SECOND duplicate methods body" not in out, \
        "must stop at the first end-section header (Results)"
    assert "AUROC 0.87" not in out


def test_extract_methods_truncated_at_8000_chars(dummy_pdf, monkeypatch):
    """A Methods section longer than the cap is truncated cleanly."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    long_body = "A" * 12000
    text = f"Abstract\n\nMethods\n{long_body}\n\nResults\nfoo\n"
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(text),
    )

    out = extract_methods_section(dummy_pdf)
    assert len(out) == 8000
    assert set(out) == {"A"}, "truncated slice must come from the body, not headers"


def test_extract_methods_pdftotext_nonzero_exit(dummy_pdf, monkeypatch):
    """pdftotext returncode != 0 -> MethodsExtractError surfacing stderr."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(
            "", returncode=1, stderr="Syntax Error: PDF file is damaged"
        ),
    )
    with pytest.raises(MethodsExtractError) as exc:
        extract_methods_section(dummy_pdf)
    assert "status 1" in str(exc.value)
    assert "damaged" in str(exc.value)


def test_extract_methods_pdftotext_timeout(dummy_pdf, monkeypatch):
    """Subprocess timeout -> MethodsExtractError mentioning the timeout."""
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )

    def _boom(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=30)

    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run", _boom
    )
    with pytest.raises(MethodsExtractError) as exc:
        extract_methods_section(dummy_pdf)
    assert "timed out" in str(exc.value)


def test_extract_methods_missing_pdf_file(tmp_path):
    """Nonexistent PDF path -> MethodsExtractError before subprocess runs."""
    with pytest.raises(MethodsExtractError) as exc:
        extract_methods_section(tmp_path / "does_not_exist.pdf")
    assert "PDF not found" in str(exc.value)


# ────────────────────────────────────────────────────────────────────────
# extract_for_paper_ids — batch behaviour
# ────────────────────────────────────────────────────────────────────────


def test_extract_for_paper_ids_batch(tmp_path, monkeypatch, caplog):
    """Batch: one resolvable PDF + one missing paper -> mixed dict, no raise."""
    # Layout: <root>/journal_X/104_widget_peer_review.pdf
    journal_dir = tmp_path / "journal_x"
    journal_dir.mkdir()
    pdf = journal_dir / "104_widget_peer_review.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    kb_path = tmp_path / "peer-review-kb.json"
    kb_path.write_text('{"entries": []}', encoding="utf-8")

    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(_FAKE_PDF_TEXT),
    )

    with caplog.at_level("WARNING"):
        out = extract_for_paper_ids(
            paper_ids=["PR-104", "PR-999"],
            kb_path=kb_path,
            case_studies_root=tmp_path,
        )

    assert set(out.keys()) == {"PR-104", "PR-999"}
    assert out["PR-104"] is not None and "EHR cohort" in out["PR-104"]
    assert out["PR-999"] is None
    assert any("PR-999" in rec.message for rec in caplog.records), \
        "missing-paper failure must be logged at WARNING"


def test_extract_for_paper_ids_pdf_prefix_not_substring_match(tmp_path, monkeypatch):
    """``PR-10`` must NOT match ``104_*.pdf`` -- the prefix is anchored on `_`."""
    journal_dir = tmp_path / "j"
    journal_dir.mkdir()
    (journal_dir / "104_paper_peer_review.pdf").write_bytes(b"%PDF")
    (journal_dir / "1040_paper_peer_review.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.shutil.which",
        lambda _name: "/usr/bin/pdftotext",
    )
    monkeypatch.setattr(
        "rag.evals.ncpr_extract_methods_from_pdf.subprocess.run",
        lambda *a, **kw: _fake_completed(_FAKE_PDF_TEXT),
    )

    out = extract_for_paper_ids(
        paper_ids=["PR-10"],
        kb_path=tmp_path / "kb.json",
        case_studies_root=tmp_path,
    )
    # No 10_* file exists, so the only correct answer is None.
    assert out == {"PR-10": None}
