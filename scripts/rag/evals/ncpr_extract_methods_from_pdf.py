"""NCPR v2 PDF Methods-section extractor (W23-A2).

Why this module exists
----------------------
The W22 V2 audit flagged that the peer-review KB has no ``methods_text``
field for most papers, so the v1 NCPR benchmark falls back to whatever
short snippet the matcher can scrape. A real recall/precision number
against reviewer concerns needs the paper's actual Methods section as
LLM input. The PDFs are the source of truth: per-paper PDFs (the
``*_peer_review.pdf`` files) live under
``references/case-studies/<journal_slug>/`` and the KB ``id`` (e.g.
``PR-104``) corresponds to the numeric prefix of the PDF basename
(``104_HFpEF_external_validation_peer_review.pdf``).

Strategy
--------
1. Locate the PDF for ``paper_id`` by scanning candidate journal dirs
   for a file whose basename starts with the paper's numeric suffix.
2. Shell out to ``pdftotext -layout`` (poppler). If pdftotext is not on
   PATH, raise ``MethodsExtractError`` with a clear install hint
   (we deliberately do not install poppler -- per CLAUDE.md NEVER rule
   #4 we never modify the user's package state).
3. Walk the text for the first ``Methods`` / ``Materials and Methods``
   / ``Methodology`` / ``Study design`` header (case-insensitive).
4. Capture from that header up to the next major section header
   (``Results``, ``Discussion``, ``References``, ``Acknowledgements``).
5. Truncate to ``_MAX_CHARS`` (8000) so downstream LLM consumers stay
   inside their token budget (~2k tokens at typical English density).

Design choices
--------------
- **subprocess vs library**: pdftotext via subprocess avoids forcing a
  pdfminer / pypdf dependency into the eval scripts. NCPR runs offline
  on the maintainer's box where poppler is standard; CI does not need
  this script (it operates on already-extracted ``methods_text``).
- **`-layout` flag**: preserves column ordering on two-column journal
  PDFs. Without it the Methods column gets interleaved with the
  Results column on the same page and the section regex fails.
- **First match wins**: papers sometimes have a "Methods summary" in
  the abstract and a full "Methods" section later. We take the
  *first* full section, which matches the conventional Nature-style
  layout (summary in abstract, full methods after Results -- in which
  case the first header we hit IS the full one). For older
  journals where Methods comes before Results, the first match is
  again the only sensible one.
- **No OCR fallback**: scanned PDFs are out of scope; the case-study
  PDFs are all born-digital. If extraction returns empty text we
  raise rather than silently degrade.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

__all__ = [
    "MethodsExtractError",
    "extract_methods_section",
    "extract_for_paper_ids",
]

logger = logging.getLogger(__name__)


# Token-budget cap. 8000 chars ≈ 2k English tokens, well inside the
# 8k context tail we reserve for retrieved KB concerns + system prompt.
_MAX_CHARS = 8000

# Subprocess timeout. Even a 60-page PDF parses in under 5 s with
# poppler on commodity hardware; 30 s is generous and bounds runaway.
_PDFTOTEXT_TIMEOUT_S = 30

# Section-header regexes. We require a newline boundary on both sides
# so we do not match inline phrases like "the methods we used".
_METHODS_HEADER_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\.?\s*)?"
    r"(materials?\s+and\s+methods?|methods?|methodology|study\s+design)"
    r"[ \t]*$"
)
_END_HEADER_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\.?\s*)?"
    r"(results?|discussion|references?|acknowledgements?|acknowledgments?|"
    r"conclusions?|supplementary\s+(?:information|materials?))"
    r"[ \t]*$"
)


class MethodsExtractError(Exception):
    """Raised when methods extraction cannot produce a usable string."""


# ────────────────────────────────────────────────────────────────────────
# pdftotext invocation
# ────────────────────────────────────────────────────────────────────────


def _run_pdftotext(pdf_path: Path) -> str:
    """Shell out to ``pdftotext -layout`` and return decoded stdout.

    Separated so tests can monkeypatch ``subprocess.run`` cleanly.
    """
    if shutil.which("pdftotext") is None:
        raise MethodsExtractError(
            "pdftotext binary not found on PATH. Install poppler:\n"
            "  macOS:  brew install poppler\n"
            "  Debian: sudo apt-get install poppler-utils\n"
            "(this script intentionally does not auto-install -- see "
            "CLAUDE.md NEVER rule #4)."
        )

    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            timeout=_PDFTOTEXT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MethodsExtractError(
            f"pdftotext timed out after {_PDFTOTEXT_TIMEOUT_S}s on {pdf_path}"
        ) from exc
    except FileNotFoundError as exc:
        # Race: shutil.which saw it but exec failed. Treat same as missing.
        raise MethodsExtractError(
            f"pdftotext disappeared between check and exec: {exc}"
        ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise MethodsExtractError(
            f"pdftotext exited with status {completed.returncode} "
            f"for {pdf_path}: {stderr or '(no stderr)'}"
        )

    return completed.stdout.decode("utf-8", errors="replace")


# ────────────────────────────────────────────────────────────────────────
# Section slicing
# ────────────────────────────────────────────────────────────────────────


def _slice_methods(text: str) -> str:
    """Return the methods section, or empty string if no header found."""
    start_match = _METHODS_HEADER_RE.search(text)
    if start_match is None:
        return ""

    # Start AFTER the header line so the section body comes first.
    start = start_match.end()

    # Find the first end-marker that occurs *after* the methods header.
    end_match = _END_HEADER_RE.search(text, pos=start)
    end = end_match.start() if end_match else len(text)

    section = text[start:end].strip()
    return section


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def extract_methods_section(pdf_path: Path) -> str:
    """Extract the Methods section from ``pdf_path``.

    Returns up to ``_MAX_CHARS`` characters of plain text.

    Raises
    ------
    MethodsExtractError
        If pdftotext is missing, the conversion fails, or no Methods
        section header is found in the PDF text.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise MethodsExtractError(f"PDF not found: {pdf_path}")

    raw = _run_pdftotext(pdf_path)
    section = _slice_methods(raw)
    if not section:
        raise MethodsExtractError(
            f"no Methods section header detected in {pdf_path.name} "
            "(tried: Methods / Materials and Methods / Methodology / "
            "Study design). Either the PDF lacks one or pdftotext "
            "produced unusable layout."
        )

    if len(section) > _MAX_CHARS:
        section = section[:_MAX_CHARS]
    return section


# ────────────────────────────────────────────────────────────────────────
# Batch helper (paper_id -> PDF discovery + extraction)
# ────────────────────────────────────────────────────────────────────────


def _paper_numeric_suffix(paper_id: str) -> Optional[str]:
    """``"PR-104"`` -> ``"104"``. Returns None if no numeric suffix."""
    m = re.search(r"(\d+)$", paper_id)
    return m.group(1) if m else None


def _find_pdf_for_paper(
    paper_id: str,
    case_studies_root: Path,
) -> Optional[Path]:
    """Locate the per-paper PDF under ``case_studies_root``.

    PDFs are stored as ``<journal_slug>/<NN>_<slug>_peer_review.pdf``
    where ``NN`` matches the numeric suffix of ``paper_id``
    (``PR-104`` -> ``104_...peer_review.pdf``).

    Returns the first matching path or None. Scans every journal dir
    so we do not have to thread the KB's ``journal`` field in here --
    callers that need journal-aware lookup can layer it on top.
    """
    suffix = _paper_numeric_suffix(paper_id)
    if suffix is None:
        return None

    # Match e.g. "104_" but NOT "1040_" or "1_" against suffix "104".
    prefix_re = re.compile(rf"^0*{suffix}_.*\.pdf$", re.IGNORECASE)

    if not case_studies_root.is_dir():
        return None

    for journal_dir in sorted(case_studies_root.iterdir()):
        if not journal_dir.is_dir():
            continue
        for pdf in sorted(journal_dir.glob("*.pdf")):
            if prefix_re.match(pdf.name):
                return pdf
    return None


def extract_for_paper_ids(
    paper_ids: list[str],
    kb_path: Path,
    case_studies_root: Path,
) -> dict:
    """Batch-extract methods text for ``paper_ids``.

    Returns ``{paper_id: methods_text_or_None}``. Per-paper failures are
    logged at WARNING level and surface as ``None`` rather than
    aborting the batch (NCPR runs need partial numbers when a few PDFs
    are missing or malformed).

    ``kb_path`` is accepted for parity with the v1 extractor signature
    but is not currently consulted -- PDF discovery is purely
    filesystem-driven. We keep the parameter so a future enhancement
    can use the KB's ``journal`` field to restrict the search and
    callers do not have to change their call site.
    """
    case_studies_root = Path(case_studies_root)
    results: dict[str, Optional[str]] = {}

    for pid in paper_ids:
        pdf = _find_pdf_for_paper(pid, case_studies_root)
        if pdf is None:
            logger.warning(
                "extract_for_paper_ids: %s skipped, no PDF found under %s",
                pid, case_studies_root,
            )
            results[pid] = None
            continue
        try:
            results[pid] = extract_methods_section(pdf)
            logger.info("extract_for_paper_ids: %s OK (%d chars)",
                        pid, len(results[pid] or ""))
        except MethodsExtractError as exc:
            logger.warning("extract_for_paper_ids: %s failed: %s", pid, exc)
            results[pid] = None

    return results
