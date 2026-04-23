# UKB Codebook — Known Coverage Gaps

This codebook mirrors the UKB Data Showcase schema download
(`https://biobank.ndph.ox.ac.uk/ukb/scdown.cgi`, schema IDs 1-13).
Everything the Showcase exposes is here. Everything below is **not**
in our local DB because UKB does not distribute it through the
Showcase — you need a UKB basket / return-data access to get it.

Listing these explicitly so "missing in our codebook" is never
confused with "missing in UKB".

## ❌ Olink NPX proteomics (2923 proteins)

- UKB Showcase carries only **5 metadata fields** under cat 1839:
  30900 (Number of proteins measured), 30901 (Plate used), 30902
  (Well used), 30903 (UKB-PPP flag), 30904 (blind-spike duplicates).
- The 2923 individual protein NPX values live in **return
  dataset T1072** ("Olink Explore 3072 NPX data"), downloaded as
  a basket-delivered flat file.
- If your analysis needs single-protein lookup (e.g., "IL6",
  "NT-proBNP"), you must fetch the T1072 schema separately and
  map Olink target names → column indices yourself.

Reference: field 30900 description says explicitly:
> "Number of protein measurements available in olink assay data.
> Add this field to a basket to gain access to ~T1072~."

## ❌ Whole-exome / whole-genome sequencing data

- UKB-PPP / WES / WGS release is distributed as bulk PLINK / VCF
  files via the Research Access Platform, not as Showcase fields.
- The Showcase exposes only metadata (cat 100314: Sequencing) —
  ~20 fields describing coverage, QC flags, assay version, etc.
- Variant-level data (hundreds of TB) is never in this codebook.

## ❌ Linked health records detail

- Primary-care records (GP), inpatient HES, Spine, ONS death
  registry are summarised as "first occurrence" fields (cat
  2401-2416) and registry fields (40000-40099), but the raw
  record rows live in dated return tables (e.g., HES APC
  episode table) that require basket subscription.
- Use our `encoding_values` table for ICD-10 / ICD-9 / OPCS-4
  lookup (19,190 / 13,709 / 11,288 entries respectively) — these
  are complete for code→meaning resolution.

## ⚠️ First-occurrence fields attached to wrong category

2,330 first-occurrence fields (e.g., `Date I10 first reported`) are
indexed under sub-categories **2401-2416** rather than their parent
category **1712** ("Health-related outcomes — first occurrences").
A query filtering on `main_category = 1712` misses them. L2 verifier
currently tolerates this as the DB reflects UKB's actual structure.
Code searching by category SHOULD traverse the `catbrowse` tree, not
filter on `main_category` only.

## ⚠️ Alias table thin (67 entries)

`aliases` table has 67 colloquial-term → field_id mappings. "bmi" /
"hba1c" / "systolic bp" work; less common terms ("甘油三酯" /
"triglycerides" / "fasting glucose") may not. L2 verifier emits a
warning if this count stays low — add entries over time.

## Reproducibility guarantee

Four verification layers. L1-L3 are offline/deterministic (run every
commit); L4 hits the live UKB website (run before publication-grade
claims or when drift is suspected).

| Layer | What it checks | Against | When |
|-------|---------------|---------|------|
| L1 | .txt file fidelity | committed sha256 in `source_manifest.json` | pre-commit, CI |
| L2 | structural invariants (counts, FK, flag logic) | SQL queries | pre-commit, CI |
| L3 | golden-seed fields survive | `ukb_golden_fields.yaml` | pre-commit, CI |
| L4 | local DB == live UKB website | `biobank.ndph.ox.ac.uk/ukb` | manual, pre-publication |

**L1-L3 alone are self-consistent but circular** — they verify the
local .txt files haven't been corrupted since ingest, but say nothing
about whether UKB has since updated its schema or whether our build
faithfully reflected the source at ingest time. L4 closes that loop.

```sh
# Offline layers (fast, deterministic)
python3 scripts/codebooks/verify_ukb_codebook.py

# Live external-authority layer (network-bound, ~20s)
python3 scripts/codebooks/verify_ukb_against_live.py           # default 38 probes
python3 scripts/codebooks/verify_ukb_against_live.py --probes 100   # 38 + 100 random
python3 scripts/codebooks/verify_ukb_against_live.py --schema-only  # just .txt sha
```

L4 re-downloads all 11 Showcase .txt files and diffs sha256 against
the manifest, then fetches `field.cgi?id=<fid>` HTML for each probe
field and compares Description + Category to our DB. Last run
(2026-04-23): **11/11 .txt identical, 19/19 probe fields exact match**.

Exit 0 = clean; Exit 2 = at least one drift or mismatch detected —
investigate before trusting the codebook.

The committed `source_manifest.json` pins every .txt file's sha256;
`fetch_ukb_showcase.py` refuses silent drift unless
`--update-manifest` is explicitly passed.
