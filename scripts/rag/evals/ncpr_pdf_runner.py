"""NCPR v2 PDF-backed paper runner (W23-C2).

Why this module exists
----------------------
The W22 V2 audit flagged that the peer-review KB rarely ships a
``methods_text`` field, so v1's ``ncpr_paper_runner`` fell back to using
the reviewer concerns *themselves* as the RAG query — a clear
ground-truth leak that inflated recall.

W23-A2 (``ncpr_extract_methods_from_pdf``) gives us the paper's real
Methods section straight out of the PDF. This module is the glue:

    PDF  ──extract──▶  methods text  ──slice──▶  ~5 chunks
                                                   │
                                                   ▼
                                       scripts.rag.query.rag_query
                                                   │
                                                   ▼
                                       per-chunk flag lists
                                                   │
                                                   ▼
                                           dedupe + aggregate

So NCPR v2 numbers reflect what MLGG-flavoured RAG would surface from a
*blind* reading of the paper's methods, not from peeking at reviewer
comments.

Design choices
--------------
- **Stub fallback for W23-A2.**  W23-A2 is on a parallel branch and may
  not be merged at runtime. We try to import ``extract_methods_section``
  and fall back to a tiny deterministic sample so this runner stays
  testable / runnable in isolation. The stub is loud: callers see it in
  ``errors`` so they can tell apart "real extraction succeeded" from
  "stubbed sample text used".

- **~5 query chunks, sentence-grouped.**  Two reasons:

    1. ``rag_query`` retrieves a small ``top_k`` per call (default 20);
       firing one query against an 8000-char methods blob risks the BGE
       embedder pooling so many tokens that fine-grained concerns (e.g.
       "no calibration plot") get washed out by the dominant theme.
    2. Five is the sweet spot the W22 ablation found between recall
       (more chunks ≈ more retrieval surface) and runtime budget
       (each chunk = one in-process embed + ANN search).

  We group by sentence boundaries instead of fixed char windows so a
  chunk does not split mid-statement (which the embedder handles, but
  badly).

- **Flag dedupe key = ``code`` only.**  Two chunks frequently retrieve
  the same KB concern (e.g. the leakage concern matches both the
  "splitting" and "feature engineering" chunks). Keeping both inflates
  recall in the matcher. ``code`` is the canonical concern id from the
  KB; ``evidence_text`` varies per-chunk so we keep the first occurrence
  for transparency.

- **Per-paper timeout.**  Default 60 s wall-clock around the whole
  pipeline (extraction + chunking + N RAG calls). Enforced with a
  worker-thread + ``Event`` rather than ``signal.SIGALRM`` so the
  runner works in non-main threads (e.g. pytest's collection thread)
  and on Windows. Timeout produces a structured error rather than an
  uncaught exception so ``batch_run_pdfs`` can continue.

- **Batch helper logs and continues.**  One missing PDF or extraction
  crash must not abort a 50-paper benchmark; each per-paper failure
  surfaces in that paper's ``errors`` list and the batch keeps going.

What this module deliberately does NOT do
-----------------------------------------
- No subprocess invocation of ``mlgg lint`` / ``mlgg audit``. That is
  ``ncpr_paper_runner.run_mlgg_pipeline``'s job and requires a code
  repo, which is orthogonal to the PDF-vs-KB-query question this
  runner answers. A v3 may compose the two; v2 stays narrow.
- No semantic matching against reviewer concerns. That is W22-X1's
  ``ncpr_matcher`` — this runner only *produces* the flag list it
  consumes.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import TypedDict

__all__ = [
    "PdfRunResult",
    "run_on_pdf",
    "batch_run_pdfs",
    "DEFAULT_CHUNK_COUNT",
    "DEFAULT_TIMEOUT_S",
]

logger = logging.getLogger(__name__)


# Number of methods-section chunks to fire as independent RAG queries.
# See module docstring for the empirical justification.
DEFAULT_CHUNK_COUNT: int = 5

# Per-paper wall-clock budget. Generous enough for slow disks / first
# embed warm-up; small enough that a 50-paper batch finishes inside an
# hour even when several papers stall.
DEFAULT_TIMEOUT_S: int = 60

# Sentence splitter. We do not need true linguistic accuracy — only a
# stable, dependency-free way to break methods text into roughly even
# pieces. Splits on ".", "?", "!" followed by whitespace and an
# uppercase / digit. Conservative on abbreviations ("Fig.", "e.g.")
# because falsely keeping them joined is harmless; falsely splitting
# them is also harmless for retrieval.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

# Stub methods text used when W23-A2 is not importable. Picked to be
# obviously synthetic so anyone reading the flag stream can tell the
# difference. Intentionally short and concern-relevant so RAG still
# returns *something* downstream tests can assert on.
_STUB_METHODS_TEXT = (
    "We trained a logistic regression model to predict 30-day mortality "
    "using a single-center retrospective cohort. Patients were randomly "
    "split 80/20 into training and test sets. Missing values were "
    "imputed using the median computed across the full dataset. "
    "Hyperparameters were selected on the test set to maximize AUROC. "
    "Calibration was not assessed. No external validation cohort was "
    "available. We report only point-estimate AUROC without confidence "
    "intervals."
)


class PdfRunResult(TypedDict):
    paper_id: str
    flags: list
    wall_time_s: float
    errors: list


# ────────────────────────────────────────────────────────────────────────
# W23-A2 extractor: try-import with stub fallback
# ────────────────────────────────────────────────────────────────────────


def _load_extractor():
    """Return ``(extract_fn, stub_used: bool)``.

    ``extract_fn`` always has signature ``(pdf_path: Path) -> str``.
    When W23-A2 is unavailable we return a closure that ignores the path
    and returns the stub sample text, plus ``stub_used=True`` so callers
    can surface the substitution in ``errors``.
    """
    try:
        from scripts.rag.evals.ncpr_extract_methods_from_pdf import (
            extract_methods_section,
        )

        def _real(pdf_path: Path) -> str:
            return extract_methods_section(pdf_path)

        return _real, False
    except ImportError:
        def _stub(pdf_path: Path) -> str:  # noqa: ARG001
            logger.warning(
                "ncpr_pdf_runner: W23-A2 extractor not importable; "
                "using stub methods text for %s", pdf_path,
            )
            return _STUB_METHODS_TEXT

        return _stub, True


# ────────────────────────────────────────────────────────────────────────
# Chunking
# ────────────────────────────────────────────────────────────────────────


def _chunk_methods_text(text: str, n_chunks: int) -> list[str]:
    """Split ``text`` into ~``n_chunks`` sentence-grouped pieces.

    Guarantees:
    - Empty / whitespace input → ``[]``.
    - ``n_chunks <= 0`` is clamped to 1.
    - Returned list has length ``min(n_chunks, sentence_count)`` so we
      never emit empty chunks padded out to ``n_chunks``.
    - Sentence order is preserved across the concatenation; each chunk
      is a substring of the normalised input modulo whitespace.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    if n_chunks < 1:
        n_chunks = 1

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip())]
    sentences = [s for s in sentences if s]
    if not sentences:
        return []

    n_chunks = min(n_chunks, len(sentences))
    # Even-ish bucketing: chunks 0..(remainder-1) get one extra sentence.
    base, rem = divmod(len(sentences), n_chunks)
    chunks: list[str] = []
    i = 0
    for c in range(n_chunks):
        size = base + (1 if c < rem else 0)
        chunks.append(" ".join(sentences[i:i + size]))
        i += size
    return chunks


# ────────────────────────────────────────────────────────────────────────
# RAG bridge + flag dedupe
# ────────────────────────────────────────────────────────────────────────


def _flags_for_chunk(
    chunk: str,
    top_k: int,
    excluded_paper_ids: list[str] | None = None,
) -> list:
    """Run RAG retrieval on ``chunk`` and convert hits to MlggFlag dicts.

    Reuses ``synthesize_flags_from_rag`` from the v1 runner so the KB-row
    → flag mapping stays in one place and any future schema change lands
    in both runners simultaneously.
    """
    # Deferred import: keeps this module importable in environments
    # where the RAG stack is not installed (e.g. doc-build CI).
    from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag

    return synthesize_flags_from_rag(
        chunk,
        top_k=top_k,
        excluded_paper_ids=excluded_paper_ids,
    )


def _paper_exclusion_ids(
    paper_id: str,
    paper_identifiers: object = None,
) -> list[str]:
    """Collect the primary id plus optional DOI/aliases for LOPO exclusion."""
    if paper_identifiers is None:
        extras = []
    elif isinstance(paper_identifiers, str):
        extras = [paper_identifiers]
    else:
        try:
            extras = list(paper_identifiers)  # type: ignore[arg-type]
        except TypeError:
            extras = [paper_identifiers]

    ids: list[str] = []
    seen: set[str] = set()
    for value in [paper_id, *extras]:
        text = str(value).strip() if value is not None else ""
        if not text or text == "<unknown>" or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _dedupe_flags(flags: list) -> list:
    """Dedupe by ``code``, preserving first occurrence."""
    seen: set[str] = set()
    out: list = []
    for f in flags:
        if not isinstance(f, dict):
            continue
        code = str(f.get("code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(f)
    return out


# ────────────────────────────────────────────────────────────────────────
# Core single-paper pipeline (sans timeout wrapper)
# ────────────────────────────────────────────────────────────────────────


def _run_on_pdf_inner(
    paper_id: str,
    pdf_path: Path,
    top_k: int,
    errors: list,
    excluded_paper_ids: list[str],
) -> list:
    """Do the work; append any non-fatal issues to ``errors``.

    Split from ``run_on_pdf`` so the timeout wrapper can call this in a
    worker thread without re-implementing the happy path.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        errors.append(f"pdf-not-found: {pdf_path}")
        return []

    extract_fn, stub_used = _load_extractor()
    if stub_used:
        errors.append(
            "extractor-stub-used: W23-A2 not importable; "
            "results derived from sample methods text"
        )

    try:
        methods_text = extract_fn(pdf_path)
    except Exception as exc:  # noqa: BLE001 — extractor can raise anything
        errors.append(f"extraction-failed: {type(exc).__name__}: {exc}")
        return []

    if not methods_text or not methods_text.strip():
        errors.append("extraction-empty: no methods text returned")
        return []

    chunks = _chunk_methods_text(methods_text, DEFAULT_CHUNK_COUNT)
    if not chunks:
        errors.append("chunking-empty: no sentences after split")
        return []

    all_flags: list = []
    for idx, chunk in enumerate(chunks):
        try:
            all_flags.extend(
                _flags_for_chunk(
                    chunk,
                    top_k=top_k,
                    excluded_paper_ids=excluded_paper_ids,
                )
            )
        except Exception as exc:  # noqa: BLE001 — RAG can fail many ways
            errors.append(f"rag-chunk-{idx}: {type(exc).__name__}: {exc}")

    return _dedupe_flags(all_flags)


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def run_on_pdf(
    paper_id: str,
    pdf_path: Path,
    top_k: int = 20,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    paper_identifiers: object = None,
) -> PdfRunResult:
    """Run the PDF-backed flag pipeline on a single paper.

    Pipeline (see module docstring for the why):

    1. Extract Methods section via W23-A2 (or stub fallback).
    2. Slice into ~5 sentence-grouped chunks.
    3. For each chunk, call ``scripts.rag.query.rag_query`` and convert
       hits to ``MlggFlag`` dicts.
    4. Dedupe by ``code``.

    Args:
        paper_id: Caller's identifier for this paper. Echoed back in the
            result and always included in RAG self-exclusion.
        pdf_path: Path to the per-paper PDF.
        top_k: ``rag_query`` retrieval depth per chunk. Clamped to ≥ 1
            inside ``synthesize_flags_from_rag``.
        timeout_s: Wall-clock budget for the whole call. On expiry the
            returned result has ``flags=[]`` and an error string; the
            in-flight worker thread is left to finish in the background.
        paper_identifiers: Optional DOI / alternate ids for the same paper.
            These are threaded into ``excluded_paper_ids`` for every RAG chunk
            alongside ``paper_id`` so DOI-keyed KB rows cannot leak back into
            a PDF-backed leave-one-paper-out run.

    Returns:
        ``PdfRunResult`` — always returns, never raises. Per-step
        failures live in ``errors``.
    """
    t0 = time.perf_counter()
    pid = str(paper_id)
    excluded_paper_ids = _paper_exclusion_ids(pid, paper_identifiers)
    errors: list = []
    flags_holder: dict = {"flags": []}
    done = threading.Event()

    def _worker() -> None:
        try:
            flags_holder["flags"] = _run_on_pdf_inner(
                pid, Path(pdf_path), top_k, errors, excluded_paper_ids,
            )
        except Exception as exc:  # noqa: BLE001 — last-ditch safety net
            errors.append(f"unhandled: {type(exc).__name__}: {exc}")
        finally:
            done.set()

    # daemon=True so a stuck extraction does not block interpreter shutdown.
    worker = threading.Thread(target=_worker, name=f"ncpr-pdf-{pid}", daemon=True)
    worker.start()
    finished = done.wait(timeout=max(1, int(timeout_s)))

    if not finished:
        errors.append(f"timeout: exceeded {timeout_s}s wall-clock budget")
        flags: list = []
    else:
        flags = flags_holder["flags"]

    wall_time_s = round(time.perf_counter() - t0, 4)
    return PdfRunResult(
        paper_id=pid,
        flags=flags,
        wall_time_s=wall_time_s,
        errors=errors,
    )


def batch_run_pdfs(
    paper_ids_to_paths: dict,
    top_k: int = 20,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    paper_identifiers_by_id: dict | None = None,
) -> dict:
    """Iterate ``run_on_pdf`` over ``{paper_id: pdf_path}``.

    One failed paper never aborts the batch — failures land in that
    paper's ``errors`` list and the next paper proceeds. The catch-all
    ``except`` here is the last line of defence; ``run_on_pdf`` already
    swallows known failure modes, so reaching this handler indicates a
    bug worth surfacing in the per-paper error list rather than
    silently dropping the paper.

    Args:
        paper_ids_to_paths: Mapping of paper id → PDF path.
        top_k: Forwarded to ``run_on_pdf``.
        timeout_s: Forwarded to ``run_on_pdf``.
        paper_identifiers_by_id: Optional mapping of paper id → DOI/aliases
            forwarded to ``run_on_pdf`` for leave-one-paper-out exclusion.

    Returns:
        ``{paper_id: PdfRunResult}`` with one entry per input paper.
    """
    if not isinstance(paper_ids_to_paths, dict):
        raise TypeError(
            "batch_run_pdfs expects a dict {paper_id: pdf_path}, "
            f"got {type(paper_ids_to_paths).__name__}"
        )

    results: dict[str, PdfRunResult] = {}
    for pid, path in paper_ids_to_paths.items():
        extra_ids = None
        if paper_identifiers_by_id:
            extra_ids = paper_identifiers_by_id.get(pid)
            if extra_ids is None:
                extra_ids = paper_identifiers_by_id.get(str(pid))
        try:
            results[str(pid)] = run_on_pdf(
                str(pid),
                Path(path),
                top_k=top_k,
                timeout_s=timeout_s,
                paper_identifiers=extra_ids,
            )
        except Exception as exc:  # noqa: BLE001 — defensive: log + continue
            logger.exception("batch_run_pdfs: unexpected crash on %s", pid)
            results[str(pid)] = PdfRunResult(
                paper_id=str(pid),
                flags=[],
                wall_time_s=0.0,
                errors=[f"batch-unhandled: {type(exc).__name__}: {exc}"],
            )
    return results
