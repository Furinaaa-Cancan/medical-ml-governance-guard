# UK Biobank Codebook

Machine-readable codebook for UK Biobank field definitions, encoding dictionaries,
and category hierarchy. Built from the **public** UKB Data Showcase schema files
(no data access approval required).

## Data Source

- **UK Biobank Data Showcase**: https://biobank.ndph.ox.ac.uk/ukb/
- **Schema endpoint**: `scdown.cgi?fmt=txt&id={schema_id}`
- **Download date**: 2026-04-12
- **License**: UKB Data Showcase metadata is publicly accessible

## Contents

| File | Schema | Records | Description |
|------|--------|---------|-------------|
| `field.txt` | 1 | ~11,800 | Field definitions (ID, title, value type, units, encoding) |
| `encoding.txt` | 2 | ~860 | Encoding dictionary metadata |
| `category.txt` | 3 | ~410 | Category definitions |
| `esimpint.txt` | 5 | varies | Integer encoding values (code → label) |
| `esimpstring.txt` | 6 | varies | String encoding values |
| `esimpreal.txt` | 7 | varies | Real encoding values |
| `esimpdate.txt` | 8 | varies | Date encoding values |
| `ehierint.txt` | 11 | varies | Hierarchical int values (ICD-10, OPCS-4) |
| `ehierstring.txt` | 12 | varies | Hierarchical string values |
| `insvalue.txt` | 9 | ~13 | Instance definitions |
| `catbrowse.txt` | 13 | varies | Category browse tree |
| **`ukb_codebook.sqlite`** | — | — | Compiled SQLite database (all above) |

## SQLite Schema

Current counts (see `verify_ukb_codebook.py` for the authoritative pinned values):

```
fields          — 11,821 fields (field_id PK, title, value_type, units, domain,
                  risk_category, encoding_id, num_participants, instance_min/max,
                  array_min/max, private, availability, ...)
categories      — 410 categories (category_id PK, parent_id, title, full_path)
encodings       — 858 encodings (encoding_id PK, title, coded_as)
encoding_values — 533,286 code→meaning mappings (encoding_id + code PK +
                  node_id for hierarchy, selectable flag, parent_code)
instances       — 13 instances (instance_id PK, title, temporal_order)
aliases         — 106 common name aliases (alias → field_id)
fields_fts      — FTS5 full-text search index
```

Each field carries a `risk_category` chosen by `classify_field()`:
`baseline`, `outcome_derived`, `hospital_derived`, `death_registry`,
`online_followup`, `imaging`, `genomics`, `identifier_direct`,
`embargoed`.

## Usage

### Rebuild from scratch

```bash
python3 scripts/codebooks/fetch_ukb_showcase.py     # download schema files
python3 scripts/codebooks/build_ukb_codebook_db.py  # build SQLite
```

### Single-field lookup / search

```bash
python3 scripts/codebooks/ukb_codebook_lookup.py --field bmi
python3 scripts/codebooks/ukb_codebook_lookup.py --search "blood pressure"
python3 scripts/codebooks/ukb_codebook_lookup.py --stats
```

`search()` promotes canonical aliases (e.g. `hba1c → 30750`) to top-1 over
BM25 noise so peripheral fields don't crowd out the true measurement.

### RAP field-list generation (disease-aware)

```bash
# Generic baseline covariate list
python3 scripts/codebooks/ukb_codebook_lookup.py --generate baseline -o fields.txt

# Disease-specific: union ukb_definition_fields from disease-definition-
# knowledge-base.json into the output (adds first-occurrence / self-
# report / lab codes used to define the outcome label)
python3 scripts/codebooks/ukb_codebook_lookup.py --generate type_2_diabetes -o t2d.txt

# Clean-feature extraction: drop fields whose risk_category is a post-
# baseline outcome family, so the resulting .txt is safe to model on.
python3 scripts/codebooks/ukb_codebook_lookup.py \
  --generate type_2_diabetes -o t2d_features.txt \
  --exclude-risk outcome_derived,death_registry,hospital_derived
```

Every `--generate` run writes a `<output>.txt.provenance.json` sidecar
recording which section contributed each RAP column, disease KB match
result, codebook `schema_version`, and applied exclusions. Disable
with `--no-provenance`.

### Python API

```python
from scripts.codebooks.ukb_codebook_lookup import UKBCodebook

with UKBCodebook() as cb:
    info = cb.lookup("hba1c")                     # alias → field 30750
    results = cb.search("cholesterol")            # FTS5 + alias promotion
    fids = cb.field_ids_by_risk(["outcome_derived"])  # batch risk lookup
    label = cb.decode_value(31, 0)                # "Female"
    report = cb.validate_columns(
        ["p21001_i0_a0", "p30750_i0", "p130708"],
        target_col="p2443_i0",
    )
    fields = cb.generate_field_list(
        "type_2_diabetes",
        output_path="t2d.txt",
        exclude_risk=["outcome_derived", "death_registry"],
    )
```

### Verification layers

See `KNOWN_GAPS.md` for the full reproducibility contract. Summary:

| Layer | What it checks | When |
|-------|----------------|------|
| **L1** | `.txt` sha256 vs `source_manifest.json` | every run |
| **L2** | 50+ structural `_HARD` invariants (FK, ICD/OPCS parent chain, PHI totals, risk-category pins, encoding FK completeness, leakage-keyword reverse scan, ICD-9/OPCS-4 selectable/has-children invariant) | every run |
| **L2c** | Full source-row → DB cell-by-cell faithfulness | every run |
| **L3** | golden-seed fields (`ukb_golden_fields.yaml`) | every run |
| **L3b** | `ukb_definition_fields` from disease-definition-knowledge-base.json — every referenced field exists + lands in allowed risk category | every run |
| **content-hashes** | 4 facet sha256 (source_titles / classification / encoding_values / aliases) pinned in `source_manifest.json`; `--strict-content-hashes` makes drift a hard fail | every run |
| **L4** | local DB ↔ live UKB website (schema sha + 38 probe-field titles + encoding row counts + units) | manual, pre-publication |

```bash
# Offline — all layers except L4
python3 scripts/codebooks/verify_ukb_codebook.py
python3 scripts/codebooks/verify_ukb_codebook.py --strict-content-hashes  # release gate

# After changing classify_field: regenerate + re-pin content hashes
python3 scripts/codebooks/verify_ukb_codebook.py --print-content-hashes
# paste output into source_manifest.json → commit together

# Live cross-check before publication-grade claims
python3 scripts/codebooks/verify_ukb_against_live.py --probes 100
```

## Key Differences from NHANES Codebook

| Dimension | NHANES | UKB |
|-----------|--------|-----|
| Temporal structure | Cycles (2017-2018) | Instances (0-3 assessment visits) |
| Missing mechanism | Skip patterns (gating chains) | No skip; missing = not assessed at that visit |
| Encoding | Per-variable codebook | Shared encoding dictionaries |
| Scale | ~58K variables | ~12K fields × multiple instances |
| Leakage risk | Skip-pattern MNAR, definition variables | Temporal (cross-instance), derived outcome fields |
