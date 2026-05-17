# W22-U3 — Journal Distribution Audit for NCPR Stratification

**Wave:** NCPR Benchmark v1 — W22 unit U3
**Scope:** `references/case-studies/peer-review-kb.json` (`contract_version: peer_review_kb.v1.4`)
**Date:** 2026-05-17
**Mode:** READ-ONLY (no edits to `references/`, `scripts/`, `.github/`)
**Question:** Is the curated 154-paper KB balanced enough to support a stratified holdout that respects journal proportions?

---

## TL;DR

**Verdict: RED — cannot stratify cleanly by journal.**

The KB header advertises 335 papers across 2 journals (Nature Communications + Communications Medicine), but the **curated** subset (papers with ≥1 reviewer concern — the only papers usable as benchmark items) is **154**, of which **150 are NC and only 4 are CM**. Any "stratified by journal" claim collapses to "97.4% NC, 2.6% CM" — i.e., journal stratification is mathematically meaningless on this KB. The folder structure under `references/case-studies/<journal>/` (bmj, jama, lancet_digital_health, nature_medicine, npj_digital_medicine, specialist_journals) contains **only domain templates, not actual paper entries** — none of those 6 nominal journals contribute curated rows to the KB.

W22-T3's stratified-holdout criterion (proportional per-journal allocation) is therefore unenforceable as written. Either (a) collapse "journal" stratum and stratify on a different axis (severity / category / domain), or (b) gate the benchmark until CM ingestion reaches a useful floor (≥30 curated CM papers).

---

## 1. Folder vs KB reality

```
references/case-studies/<journal>/ count of subentries
  bmj                       : 9   (all are disease subfolders, 0 papers)
  jama                      : 9   (disease subfolders, 0 papers)
  lancet_digital_health     : 9   (disease subfolders, 0 papers)
  nature_medicine           : 9   (disease subfolders, 0 papers)
  npj_digital_medicine      : 9   (disease subfolders, 0 papers)
  specialist_journals       : 10  (disease subfolders, 0 papers)
  communications_medicine   : 82  (per-paper directories)
  nature_communications     : 290 (per-paper directories)
```

Only NC and CM have populated per-paper directories. The other six journal folders are scaffolding from `papers/manifests/batch_manifest_*.json` (target_journals list) that have not yet been ingested into `peer-review-kb.json`.

---

## 2. Per-journal table (curated = papers with ≥1 reviewer concern)

| Journal | Total papers | Curated (≥1 concern) | Methods-text grounded | Total concerns | Mean concerns / curated paper | Avg review rounds |
|---|---:|---:|---:|---:|---:|---:|
| Nature Communications | 248 | **150** | 150 | 795 | 5.30 | 2.03 |
| Communications Medicine | 87 | **4** | 4 | 22 | 5.50 | 2.00 |
| **Total** | **335** | **154** | **154** | **817** | 5.31 | — |

- "Methods-text grounded" = paper has at least one concern with non-empty `concern_text` (proxy for reviewable methods evidence). `pdf_verification.status` is `NONE` for all 335 entries, so PDF grounding cannot be confirmed from the KB metadata alone.
- 181 entries (98 NC + 83 CM) have **zero** reviewer concerns; in CM these are mostly `PR-EXP-*` stub IDs from 2025–2026 expansion ingest, not usable for benchmark scoring.

### Severity distribution (% of journal's curated concerns)

| Severity | NC | CM |
|---|---:|---:|
| CRITICAL | 40 (5%) | 1 (5%) |
| HIGH | 300 (38%) | 4 (18%) |
| MEDIUM | 402 (51%) | 10 (45%) |
| LOW | 53 (7%) | 7 (32%) |

CM's small N inflates LOW share (32% vs NC 7%) — likely sampling noise, not a real journal effect.

### Top-5 category mix

| Category | NC | CM |
|---|---:|---:|
| evaluation_metrics | 190 | 6 |
| study_design | 167 | 5 |
| reporting | 93 | 2 |
| external_validation | 67 | 1 |
| model_selection | 54 | 4 |

Rank order roughly preserved; CM concern counts are too small for a meaningful chi-square comparison.

### Are NC papers systematically "harder" than CM?

Mean concerns/curated-paper is essentially identical (NC 5.30 vs CM 5.50). Mean review rounds identical (2.03 vs 2.00). **No evidence of journal-level difficulty skew**, but CM N=4 makes the comparison unreliable.

---

## 3. N=30 holdout allocation under W22-T3 proportional rule

| Scenario | NC alloc | CM alloc | Notes |
|---|---:|---:|---|
| A — proportional on **all 335** entries | 22 | 8 | Would require holding out 8 CM papers, but only 4 are curated — **infeasible**. |
| B — proportional on **154 curated** | 29 | 1 | Mathematically feasible; CM stratum collapses to a single paper, providing no within-stratum variance estimate. |
| C — strict floor on curated | 29 | 1 | Same as B. |

Even Scenario B yields a degenerate CM stratum (N=1), which cannot support per-stratum metric reporting, confidence intervals, or per-journal subgroup analysis. The "stratified by journal" claim is cosmetic.

---

## 4. Imbalance warnings

1. **CM curation backlog is the binding constraint.** 83 of 87 CM entries are concern-less placeholders; the effective CM corpus is ~5% the size of NC. No statistical adjustment recovers from a 150:4 imbalance.
2. **Five nominally-targeted journals have zero curated entries** (BMJ, JAMA, Lancet DH, Nature Medicine, npj DM). The `batch_manifest_all.json` enumerates 4 sample projects (O'Connor, Hippisley-Cox, Esteva, Attia) but these are not present as KB entries. Any "multi-journal benchmark" claim is unsupported.
3. **PDF verification absent.** All 335 entries report `pdf_verification.status = NONE`. Methods-text grounding can be inferred only from concern text length, not from a verified source PDF.
4. **Domain mix is uneven within NC** (48/150 curated papers have `domain = None`, oncology is the only well-represented domain at 28). If T3 ultimately stratifies on domain instead of journal, expect similar degeneracies.

---

## 5. Verdict and recommendation

**RED — cannot stratify cleanly by journal.**

Options for W22-T3 follow-up:

| Option | Description | Cost |
|---|---|---|
| **R1** | Drop journal as a stratification axis. Stratify on severity-mix or top-category instead (both have usable variance within the 150 NC papers). | Low — relabel the holdout-construction step in T3. |
| **R2** | Block the v1 benchmark release on CM ingestion to ≥30 curated papers (and ideally ≥30 each for ≥1 of {BMJ, JAMA, Lancet DH, Nature Medicine, npj DM}). | High — manual curation throughput is the bottleneck. |
| **R3** | Ship v1 as "Nature Communications methodology critique benchmark," explicitly scoped, and defer multi-journal coverage to v2. | Low — but must edit benchmark scope docs and README claims. |

Recommended path: **R1 + R3** in parallel. R2 alone is unrealistic within the W22 wave.

---

## Appendix — Artifacts

- `/tmp/W22_U3_per_journal_table.txt` — full per-journal breakdown (severity %, category top-5, all three allocation scenarios)
- `/tmp/W22_U3_journal_breakdown.json` — machine-readable per-journal stats with N=30 allocations under both scenarios

## Reproduce

```bash
ls references/case-studies/ | grep -v '\.' | sort
for d in references/case-studies/*/; do echo "$d: $(ls $d 2>&1 | wc -l) entries"; done
python3 -c "
import json
from collections import Counter, defaultdict
kb = json.load(open('references/case-studies/peer-review-kb.json'))
j = defaultdict(lambda: {'papers':0,'curated':0,'concerns':0})
for e in kb['entries']:
    d=j[e['journal']]; d['papers']+=1
    cs=e.get('reviewer_concerns') or []
    if cs: d['curated']+=1
    d['concerns']+=len(cs)
print(dict(j))
"
```
