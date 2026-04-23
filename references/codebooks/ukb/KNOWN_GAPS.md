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

## ⚠️ Alias table thin

`aliases` maps colloquial medical terms to field_id. L2 floor invariant
pins the current count (106 as of 2026-04-23). "bmi" / "hba1c" /
"systolic bp" work; less common terms ("甘油三酯" / "fasting glucose")
may not yet — add entries in `COMMON_ALIASES`
(`scripts/codebooks/build_ukb_codebook_db.py`). Additions are welcome;
bump the floor in the same commit.

## Reproducibility guarantee

Seven verification layers. L1-L3b + content-hashes are offline and
deterministic (run every commit); L4 hits the live UKB website (run
before publication-grade claims or when drift is suspected).

| Layer | What it checks | Against | When |
|-------|---------------|---------|------|
| **L1** | `.txt` source fidelity | committed sha256 in `source_manifest.json` | pre-commit, CI |
| **L2** | structural invariants — counts within tolerance, 30+ `_HARD` facts (FK integrity, ICD/OPCS parent chain, PHI totals, risk-category pins, encoding FK completeness, leakage-keyword reverse-scan on baseline titles) | SQL queries | pre-commit, CI |
| **L3** | golden-seed fields + ICD codes survive with expected metadata | `ukb_golden_fields.yaml` | pre-commit, CI |
| **L3b** | `disease-definition-knowledge-base.json`'s `ukb_definition_fields` all exist in DB and land in a risk_category allowed for outcome definition (baseline / outcome_derived / hospital_derived / death_registry / online_followup) | `references/methodology/disease-definition-knowledge-base.json` | pre-commit, CI |
| **content-hashes** | sha256 per content facet — `source_titles`, `classification`, `encoding_values`, `aliases` — catches silent drift (e.g. 1000 fields quietly flipped baseline → online_followup) that counts + golden seeds both miss | optional `content_hashes` block in `source_manifest.json` | reported every run; enforced with `--strict-content-hashes` |
| **L4 (schema)** | all 11 live `.txt` files still match committed sha256 | `biobank.ndph.ox.ac.uk/ukb` | manual, pre-publication |
| **L4 (fields)** | title + category of 38 probe fields match live UKB field pages | `biobank.ndph.ox.ac.uk/ukb` | manual, pre-publication |

**L1-L3 alone are self-consistent but circular** — they verify the
local .txt files haven't been corrupted since ingest, but say nothing
about whether UKB has since updated its schema or whether our build
faithfully reflected the source at ingest time. L4 closes that loop.

**Content-hashes sit between L2 and L4** — they're offline so cheap
to run every commit, but unlike L2's specific-fact pins they catch
*any* semantic change across the four facets. Ideal for CI log audit
trails: a `classification` hash change visible in diff means
`classify_field()` got updated; if that wasn't expected, investigate.

```sh
# Offline layers (fast, deterministic)
python3 scripts/codebooks/verify_ukb_codebook.py

# Skip individual layers
python3 scripts/codebooks/verify_ukb_codebook.py --skip-l1
python3 scripts/codebooks/verify_ukb_codebook.py --skip-l3
python3 scripts/codebooks/verify_ukb_codebook.py --skip-disease-kb

# Content hash pinning workflow
python3 scripts/codebooks/verify_ukb_codebook.py --print-content-hashes
# → emits JSON; paste under 'content_hashes' in source_manifest.json
python3 scripts/codebooks/verify_ukb_codebook.py --strict-content-hashes
# → any drift vs pinned = exit 2 (release-gate mode)

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

### What each layer is *not* good at

- **L1** cannot see a bug in our build-time transform — the .txt is
  perfect but we misread a column. → L2 + L4-fields.
- **L2** specific-fact pins (30+) cover the facts we thought to pin.
  Anything else, including *"1799 fields flipped risk_category since
  last build"*, slides through the ±0.5% count tolerance. → content-hashes.
- **L3** golden-seeds cover ~200 field_ids and ~20 ICD codes by
  name — high-confidence but shallow. → L3b + content-hashes.
- **L3b** disease-KB join only touches ~50 definition field_ids
  across ~10 diseases. Everything outside that is unchecked. → L4.
- **content-hashes** show that *something* moved but not *what*. Pair
  with `git diff` of the commit that moved them to identify the
  rule change. → (manual) reverse-scan per-risk-category breakdown.
- **L4** is the only layer proving our DB reflects reality, but it's
  network-bound and probabilistic (38 probes out of 11,821 fields).
  → run larger probe sample (`--probes 200`) before any publication-
  grade claim.
