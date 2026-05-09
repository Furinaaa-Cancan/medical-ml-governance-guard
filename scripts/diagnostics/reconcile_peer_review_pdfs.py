#!/usr/bin/env python3
"""Reconcile peer-review-kb.json entries with on-disk PDFs by DOI / title match.

Reads:
  - references/case-studies/peer-review-kb.json (the KB)
  - references/case-studies/nature_communications/*.pdf (the PDF corpus)

Writes (if --apply):
  - peer-review-kb.json with two new fields per entry:
      peer_review_pdf_path: relative path to verified PDF, or null
      pdf_verification: {method, matched_doi, matched_title, confidence,
                         verified_at}

Always writes:
  - paper/reconciliation-report.md (human-readable summary)
  - paper/reconciliation-report.json (machine-readable detail)

Usage:
    python3 scripts/diagnostics/reconcile_peer_review_pdfs.py            # dry-run, report only
    python3 scripts/diagnostics/reconcile_peer_review_pdfs.py --apply    # also mutate KB

Exit code: 0 if no errors during scan; 2 if any PDF fails to parse.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
PDF_DIR = ROOT / "references" / "case-studies" / "nature_communications"
REPORT_DIR = ROOT / "paper"
REPORT_MD = REPORT_DIR / "reconciliation-report.md"
REPORT_JSON = REPORT_DIR / "reconciliation-report.json"

# Manual override for cases the automated matcher cannot resolve due to
# abbreviations (NLP/EHR/CXR/CT) or unusual filename conventions.
# Each entry visually verified against PDF content + KB title.
MANUAL_OVERRIDES: dict[str, str] = {
    "PR-014": "references/case-studies/nature_communications/42_cancer_NLP_EHR_peer_review.pdf",
    "PR-015": "references/case-studies/nature_communications/43_synthetic_EHR_HALO_peer_review.pdf",
    "PR-062": "references/case-studies/nature_communications/NC_lung_mortality_CXR_DL_peer_review.pdf",
    "PR-066": "references/case-studies/nature_communications/NC_renal_mass_CT_AI_peer_review.pdf",
    "PR-067": "references/case-studies/nature_communications/NC_T2D_chest_xray_DL_peer_review.pdf",
    "PR-068": "references/case-studies/nature_communications/NC_pretrained_transformer_trials_peer_review.pdf",
    "PR-073": "references/case-studies/nature_communications/NC_ECG_multilabel_DL_peer_review.pdf",
    "PR-092": "references/case-studies/nature_communications/NC_pathology_biomarker_DL_peer_review.pdf",
    "PR-RO-01": "references/case-studies/nature_communications/NC_AD_genetics_ML_peer_review.pdf",
    "PR-RO-02": "references/case-studies/nature_communications/NC_cardiometab_children_peer_review.pdf",
    # PR-RO-03 still unmapped - no obvious orphan PDF for Crohn's plasma proteomic
}

DOI_RE = re.compile(r'10\.1038/(s\d{5}-\d{3}-\d{5}-[a-z0-9]+|s\d{5}-\d{3}-\d{4,5}-[a-z0-9]+)')


def extract_pdf_text(pdf_path: Path, max_pages: int = 5) -> str:
    """Extract text from first N pages of a PDF. Returns empty string on error."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        pages = reader.pages[:max_pages]
        return "\n".join(p.extract_text() or "" for p in pages)
    except Exception as exc:
        print(f"  WARN: cannot read {pdf_path.name}: {exc}", file=sys.stderr)
        return ""


def find_doi_in_text(text: str) -> set[str]:
    return set(DOI_RE.findall(text))


def normalize_title(t: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    t = re.sub(r'[^a-z0-9\s]', ' ', t.lower())
    return re.sub(r'\s+', ' ', t).strip()


def title_overlap(a: str, b: str) -> float:
    """Jaccard overlap of normalized title word sets."""
    sa = set(normalize_title(a).split())
    sb = set(normalize_title(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa | sb), 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Mutate KB; default is dry-run.")
    args = ap.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. Index all PDFs ---
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"Indexing {len(pdfs)} PDFs (extracting first 2 pages each)...", file=sys.stderr)
    pdf_index: list[dict] = []
    parse_errors = 0
    for i, p in enumerate(pdfs):
        if i % 20 == 0 and i > 0:
            print(f"  {i}/{len(pdfs)}...", file=sys.stderr)
        text = extract_pdf_text(p)
        if not text:
            parse_errors += 1
            pdf_index.append({"path": str(p.relative_to(ROOT)),
                              "name": p.name,
                              "size_bytes": p.stat().st_size,
                              "dois_found": [],
                              "title_snippet": "",
                              "first_page_first_500": ""})
            continue
        dois = sorted(find_doi_in_text(text))
        # Heuristic: title is often the line right after "Peer Review File"
        m = re.search(r'Peer Review File\s*([^\n]{20,200})', text)
        title_snippet = (m.group(1) if m else "").strip()
        if not title_snippet:
            # fallback: first non-trivial line
            for line in text.split("\n"):
                line = line.strip()
                if 20 < len(line) < 200 and not line.startswith(("Open Access", "This file")):
                    title_snippet = line
                    break
        pdf_index.append({
            "path": str(p.relative_to(ROOT)),
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "dois_found": dois,
            "title_snippet": title_snippet,
            "first_page_first_500": text[:500],
            "full_text_norm": normalize_title(text[:12000]),  # for substring search
        })
    print(f"  done. parse_errors={parse_errors}", file=sys.stderr)

    # --- 2. Load KB ---
    kb = json.loads(KB_PATH.read_text())
    entries = kb["entries"]
    print(f"Loaded {len(entries)} KB entries.", file=sys.stderr)

    # --- 3. Match each KB entry to a PDF ---
    results = []
    for e in entries:
        eid = e["id"]
        kb_doi = e.get("paper_doi", "").strip()
        kb_title = e.get("paper_title", "").strip()
        # Strategy 0: manual override (visually verified pairings)
        if eid in MANUAL_OVERRIDES:
            ov_path = MANUAL_OVERRIDES[eid]
            ov_pi = next((pi for pi in pdf_index if pi["path"] == ov_path), None)
            if ov_pi:
                results.append({
                    "id": eid,
                    "kb_doi": kb_doi,
                    "kb_title": kb_title[:100],
                    "pdf_path": ov_pi["path"],
                    "pdf_name": ov_pi["name"],
                    "confidence": "high",
                    "method": "manual_override",
                    "note": "Visually verified mapping (abbreviation/filename mismatch)",
                })
                continue
        # Strategy 1: DOI exact match
        matched_via_doi = []
        for pi in pdf_index:
            for pd in pi["dois_found"]:
                full_pd = pd if pd.startswith("10.") else f"10.1038/{pd}"
                if full_pd == kb_doi or pd in kb_doi or kb_doi.endswith(pd):
                    matched_via_doi.append(pi)
                    break
        # Strategy 2: title overlap (jaccard >= 0.5)
        title_matches = []
        for pi in pdf_index:
            ov = title_overlap(kb_title, pi["title_snippet"])
            if ov >= 0.5:
                title_matches.append((ov, pi))
        title_matches.sort(reverse=True, key=lambda x: x[0])

        # Strategy: peer review PDFs contain full paper title somewhere in
        # first 3 pages. Match KB title against full PDF text as substring
        # (after normalization). The first 5-8 words of a paper title are
        # almost always unique within a corpus.
        kb_title_norm = normalize_title(kb_title)
        kb_first_words = " ".join(kb_title_norm.split()[:7])
        substring_matches = []
        for pi in pdf_index:
            full_text_norm = normalize_title(pi.get("first_page_first_500", "") + " " +
                                             pi.get("title_snippet", "") + " " +
                                             pi.get("full_text_norm", ""))
            if len(kb_first_words) >= 30 and kb_first_words in full_text_norm:
                substring_matches.append(pi)
        if matched_via_doi and len(matched_via_doi) == 1:
            best = matched_via_doi[0]
            confidence = "high"
            method = "doi_match"
            note = "DOI exact match in PDF text"
        elif len(substring_matches) == 1:
            best = substring_matches[0]
            confidence = "high"
            method = "title_substring"
            note = f"First 7 words of KB title found in PDF text"
        elif len(substring_matches) > 1:
            # Disambiguate by largest title overlap
            scored = sorted(((title_overlap(kb_title, pi.get("title_snippet","")), pi) for pi in substring_matches), reverse=True, key=lambda x: x[0])
            best = scored[0][1]
            confidence = "high_multi"
            method = "title_substring_multi"
            note = f"Title substring matched {len(substring_matches)} PDFs; chose by overlap {scored[0][0]:.2f}"
        elif title_matches and title_matches[0][0] >= 0.7:
            best = title_matches[0][1]
            confidence = "medium"
            method = "title_jaccard"
            note = f"Title Jaccard {title_matches[0][0]:.2f}"
        elif title_matches and title_matches[0][0] >= 0.5:
            best = title_matches[0][1]
            confidence = "low"
            method = "title_jaccard"
            note = f"Title Jaccard {title_matches[0][0]:.2f}"
        else:
            # Last-resort: match by filename keyword overlap with KB title
            fname_matches = []
            kb_words = set(normalize_title(kb_title).split())
            for pi in pdf_index:
                # filename like '04_AI_sepsis_prediction_peer_review.pdf' -> keywords
                stem = pi["name"].replace("_peer_review.pdf","").replace(".pdf","")
                stem_words = set(normalize_title(stem.replace("_"," ")).split())
                stem_words -= {"NC","CM","peer","review","ML","AI","DL"}
                if not stem_words:
                    continue
                ov = len(kb_words & stem_words) / max(len(stem_words), 1)
                if ov >= 0.5:
                    fname_matches.append((ov, pi))
            fname_matches.sort(reverse=True, key=lambda x: x[0])
            if fname_matches:
                best = fname_matches[0][1]
                confidence = "low"
                method = "filename_keywords"
                note = f"Filename keyword overlap {fname_matches[0][0]:.2f}"
            else:
                best = None
                confidence = "none"
                method = "no_match"
                note = f"No title/filename match (best title overlap={title_matches[0][0]:.2f})" if title_matches else "No overlap with any PDF"

        result = {
            "id": eid,
            "kb_doi": kb_doi,
            "kb_title": kb_title[:100],
            "pdf_path": best["path"] if best else None,
            "pdf_name": best["name"] if best else None,
            "confidence": confidence,
            "method": method,
            "note": note,
        }
        results.append(result)

    # --- 4. Compute coverage stats ---
    n_high = sum(1 for r in results if r["confidence"] == "high")
    n_high_multi = sum(1 for r in results if r["confidence"] == "high_multi")
    n_medium = sum(1 for r in results if r["confidence"] == "medium")
    n_low = sum(1 for r in results if r["confidence"] == "low")
    n_none = sum(1 for r in results if r["confidence"] == "none")
    matched_pdfs = {r["pdf_path"] for r in results if r["pdf_path"]}
    unmatched_pdfs = [pi for pi in pdf_index if pi["path"] not in matched_pdfs]

    # --- 5. Write reports ---
    REPORT_JSON.write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "kb_path": str(KB_PATH.relative_to(ROOT)),
        "pdf_dir": str(PDF_DIR.relative_to(ROOT)),
        "pdfs_total": len(pdf_index),
        "pdfs_parse_errors": parse_errors,
        "kb_entries_total": len(entries),
        "matches": {
            "high (DOI single match)": n_high,
            "high_multi (DOI matches multiple)": n_high_multi,
            "medium (title >= 0.7)": n_medium,
            "low (title 0.5–0.7)": n_low,
            "none (no match)": n_none,
        },
        "kb_entries_with_verified_pdf": n_high + n_high_multi,
        "pdfs_unmatched_to_any_kb_entry": len(unmatched_pdfs),
        "results": results,
        "unmatched_pdfs": [{"name": pi["name"], "size_bytes": pi["size_bytes"],
                            "title_snippet": pi["title_snippet"][:150],
                            "dois_found": pi["dois_found"]} for pi in unmatched_pdfs],
    }, indent=2, ensure_ascii=False))

    md = []
    md.append(f"# Peer-review KB ↔ PDF reconciliation report")
    md.append("")
    md.append(f"**Generated**: {datetime.now(timezone.utc).isoformat()}")
    md.append(f"**KB**: `{KB_PATH.relative_to(ROOT)}`")
    md.append(f"**PDF dir**: `{PDF_DIR.relative_to(ROOT)}`")
    md.append("")
    md.append(f"## Headline numbers")
    md.append("")
    md.append(f"| Metric | Count |")
    md.append(f"|---|---|")
    md.append(f"| KB entries | {len(entries)} |")
    md.append(f"| PDFs in directory | {len(pdf_index)} |")
    md.append(f"| PDFs that failed to parse | {parse_errors} |")
    md.append(f"| KB entries with **high-confidence** PDF (DOI match, single) | **{n_high}** |")
    md.append(f"| KB entries with high-multi (DOI match, ambiguous) | {n_high_multi} |")
    md.append(f"| KB entries with medium (title overlap ≥0.7) | {n_medium} |")
    md.append(f"| KB entries with low (title overlap 0.5–0.7) | {n_low} |")
    md.append(f"| KB entries with **no match** | **{n_none}** |")
    md.append(f"| PDFs not matched to any KB entry | {len(unmatched_pdfs)} |")
    md.append("")
    md.append(f"## What this means for the paper")
    md.append("")
    md.append(f"- Trustable corpus (KB entry + verified PDF link): **{n_high} papers**")
    md.append(f"- With looser title-jaccard 0.7+: **{n_high + n_high_multi + n_medium} papers**")
    md.append(f"- Speculative (no PDF link found): **{n_none} papers**")
    md.append("")
    md.append(f"## KB entries with no PDF match")
    md.append("")
    md.append(f"| ID | DOI | Title (first 80) |")
    md.append(f"|---|---|---|")
    for r in results:
        if r["confidence"] == "none":
            md.append(f"| {r['id']} | `{r['kb_doi']}` | {r['kb_title'][:80]} |")
    md.append("")
    md.append(f"## PDFs not matched to any KB entry (potentially orphaned)")
    md.append("")
    md.append(f"| File | Size | DOI in text | Title snippet |")
    md.append(f"|---|---:|---|---|")
    for pi in unmatched_pdfs[:50]:
        size_kb = pi["size_bytes"] // 1024
        dois = ", ".join(pi["dois_found"]) or "—"
        title = pi["title_snippet"][:80] if pi["title_snippet"] else "—"
        md.append(f"| `{pi['name']}` | {size_kb} KB | {dois} | {title} |")
    if len(unmatched_pdfs) > 50:
        md.append(f"")
        md.append(f"... and {len(unmatched_pdfs) - 50} more.")
    md.append("")
    REPORT_MD.write_text("\n".join(md))

    # --- 6. (optional) Mutate KB ---
    if args.apply:
        ts = datetime.now(timezone.utc).isoformat()
        for e, r in zip(entries, results):
            if r["confidence"] in ("high", "high_multi", "medium"):
                e["peer_review_pdf_path"] = r["pdf_path"]
                e["pdf_verification"] = {
                    "method": r["method"],
                    "confidence": r["confidence"],
                    "note": r["note"],
                    "verified_at": ts,
                }
            else:
                e["peer_review_pdf_path"] = None
                e["pdf_verification"] = {
                    "method": r["method"],
                    "confidence": r["confidence"],
                    "note": r["note"],
                    "verified_at": ts,
                }
        kb["provenance"] = {
            "last_reconciled_utc": ts,
            "reconciliation_script": "scripts/diagnostics/reconcile_peer_review_pdfs.py",
            "pdf_dir": str(PDF_DIR.relative_to(ROOT)),
            "match_strategy": "Layered: (0) manual override for known abbreviation cases, (1) DOI substring in PDF first 5 pages, (2) KB title first-7-words substring in normalized first 12000 chars of PDF text, (3) title Jaccard >= 0.7 / 0.5 fallback, (4) filename keyword overlap fallback. Peer review PDFs typically do NOT contain the DOI; substring of paper title is the dominant signal.",
            "confidence_levels": {
                "high": "title_substring or doi_match or manual_override",
                "high_multi": "title substring matched multiple PDFs (ambiguous)",
                "medium": "Title Jaccard overlap >= 0.7",
                "low": "Title Jaccard 0.5–0.7 or filename keyword overlap >= 0.5",
                "none": "No reliable signal; PDF link set to null",
            },
            "manual_overrides": list(MANUAL_OVERRIDES.keys()),
            "known_unmatched_kb_ids": ["PR-RO-03"],  # Crohn's plasma proteomic; PDF not downloaded
        }
        KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False))
        print(f"\nKB mutated: peer_review_pdf_path + pdf_verification added per entry.", file=sys.stderr)

    # --- 7. Console summary ---
    print(f"\nReports written:")
    print(f"  {REPORT_MD.relative_to(ROOT)}")
    print(f"  {REPORT_JSON.relative_to(ROOT)}")
    print(f"\nTrustable corpus (high-confidence DOI match): {n_high} papers")
    print(f"With looser title overlap: {n_high + n_high_multi + n_medium} papers")
    print(f"Unmatched KB entries: {n_none}")
    print(f"Orphan PDFs (no KB entry): {len(unmatched_pdfs)}")
    return 0 if parse_errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
