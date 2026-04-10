# NHANES Codebook Data (Harvard CCB-HMS)

Authoritative NHANES variable metadata from Harvard Center for Computational Biomedicine.

## Source

Repository: [ccb-hms/NHANES-metadata](https://github.com/ccb-hms/NHANES-metadata)

## Files

| File | Rows | Description |
|------|------|-------------|
| `nhanes_variables.tsv` | 58,794 | All NHANES variables: name, SAS label, English question text, target population |
| `nhanes_variables_codebooks.tsv` | 202,019 | Value codes, descriptions, frequencies, skip patterns (SkipToItem) |

## Download

```bash
curl -sL -o references/nhanes_codebook/nhanes_variables.tsv \
  "https://raw.githubusercontent.com/ccb-hms/NHANES-metadata/master/metadata/nhanes_variables.tsv"

curl -sL -o references/nhanes_codebook/nhanes_variables_codebooks.tsv \
  "https://raw.githubusercontent.com/ccb-hms/NHANES-metadata/master/metadata/nhanes_variables_codebooks.tsv"
```

## Usage

These files are used to cross-validate `references/dataset-codebook-registry.json`.
The registry contains a curated subset of variables relevant to MLGG datasets,
with additional annotations (skip patterns, gated missingness, encoding rules)
not present in the raw Harvard data.

## Cross-validation (2026-04-10)

- 21/21 variables matched against Harvard 2017-2018 cycle data
- 0 semantic conflicts
- Skip patterns confirmed for: BPQ020, DIQ010, DIQ172, SMQ020
- Gated missingness confirmed for: BPQ050A (68%), DIQ172 (34%)
