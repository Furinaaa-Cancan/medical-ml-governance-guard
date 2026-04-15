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

```
fields          — 11,821 fields (field_id PK, title, value_type, units, domain, encoding_id, ...)
categories      — 410 categories (category_id PK, parent_id, title, full_path)
encodings       — 858 encodings (encoding_id PK, title, coded_as)
encoding_values — 466,803 code→meaning mappings (encoding_id + code PK)
instances       — 13 instances (instance_id PK, title, temporal_order)
aliases         — 67 common name aliases (alias → field_id)
fields_fts      — FTS5 full-text search index
```

## Usage

```bash
# Rebuild from scratch
python3 scripts/codebooks/fetch_ukb_showcase.py     # download schema files
python3 scripts/codebooks/build_ukb_codebook_db.py  # build SQLite

# Lookup
python3 scripts/codebooks/ukb_codebook_lookup.py --field bmi
python3 scripts/codebooks/ukb_codebook_lookup.py --search "blood pressure"
python3 scripts/codebooks/ukb_codebook_lookup.py --data my_extract.csv --target 130708-0.0

# Python API
from scripts.tools.ukb_codebook_lookup import UKBCodebook
cb = UKBCodebook()
info = cb.lookup("hba1c")           # alias → field 30750
results = cb.search("cholesterol")   # FTS5 search
report = cb.validate_columns(["21001-0.0", "30750-0.0"], target_col="130708-0.0")
```

## Key Differences from NHANES Codebook

| Dimension | NHANES | UKB |
|-----------|--------|-----|
| Temporal structure | Cycles (2017-2018) | Instances (0-3 assessment visits) |
| Missing mechanism | Skip patterns (gating chains) | No skip; missing = not assessed at that visit |
| Encoding | Per-variable codebook | Shared encoding dictionaries |
| Scale | ~58K variables | ~12K fields × multiple instances |
| Leakage risk | Skip-pattern MNAR, definition variables | Temporal (cross-instance), derived outcome fields |
