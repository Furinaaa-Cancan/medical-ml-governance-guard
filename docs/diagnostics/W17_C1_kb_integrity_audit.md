# W17-C1: peer-review-kb Integrity Audit

**Scope:** `references/case-studies/peer-review-kb.json` (contract `peer_review_kb.v1.4`).
**Audited:** 335 paper entries, **817 reviewer-concerns**.
**Fields validated:** `concern_id`, `concern_text`, `severity`, `mlgg_gates` (list ≥1, each name resolvable to `scripts/gates/*.py` and `scripts/core/_gate_registry.py::GATE_REGISTRY`), `paper_id` stem consistency.

## Verdict: **YELLOW**

No RED conditions (zero dangling gate refs, zero duplicate concern IDs, zero invalid severity, zero missing mandatory fields). Yellow is driven by stale metadata and partial coverage.

## Findings

| Check | Result |
| --- | --- |
| Unique concern_ids | 817 / 817 |
| Duplicate paper_ids | 0 |
| Missing `concern_text` / `severity` / `mlgg_gates` | 0 / 0 / 0 |
| Invalid severity | 0 |
| `concern_id` stem ≠ parent paper id | 0 |
| Empty `mlgg_gates` list | 0 |
| Dangling gate names | **0** |
| paper_id formats accepted | `PR-001`, `PR-EXP-0084`, `PR-RO-07` |

## Stale / inconsistent metadata (YELLOW drivers)

1. **Header counter stale.** KB header `total_concerns: 449`, actual **817** (+82 % drift). W9 claim re-verified true; header never bumped.
2. **181 papers carry 0 concerns** (54 %) — pending-extraction stubs. concerns/paper: min 0, max 15, mean 2.44, median 0.
3. **217 papers empty `domain`** (`PR-EXP-NNNN` batch); only 118 carry a real domain.
4. **Quarantine retained** (`PR-040`, fabricated DOI, removed 2026-05-10) — correctly excluded.

## Orphaned gates (registered, never referenced)

`manifest_lock`, `request_contract_gate`, `security_audit_gate`, `self_critique_gate` — 4/33 (12 %). All infrastructure/meta gates no peer-review concern would naturally cite. Acceptable.

## Top 10 most-broken concerns

**None.** All 817 concerns pass every check.

## Wave-N+ fix candidates

- **W17-fix:** rewrite `total_concerns` header to 817 (or compute on read).
- **W18:** backfill `domain` for the 217 `PR-EXP-NNNN` stubs, or split KB into `curated` vs `pending` arrays so headline metrics aren't diluted.
- **W18:** triage 181 zero-concern papers + 24 `resolved:false` + 89 `resolved:null`.

**Artefacts:** `/tmp/W17_C1_audit.py`, `/tmp/W17_C1_audit.json`, `/tmp/W17_C1_audit.log`.
