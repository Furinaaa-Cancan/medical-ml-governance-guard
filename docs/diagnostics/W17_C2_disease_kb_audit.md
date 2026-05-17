# W17-C2 — Disease KB Fail-Closed Gate Audit

**Wave**: 17 (strict review) · **Slot**: C2 · **Date**: 2026-05-17
**Scope**: Verify W11-F2 + W13-C1 hardened `publication_gate` disease-KB
fail-closed check actually fires against the bundled KB and against three
spoof patterns.
**Mode**: READ-ONLY for `references/`, `scripts/`, `.github/`.
Fixtures + raw report under `/tmp/W17_C2_*`.
**Driver**: `/tmp/W17_C2_driver.py` (calls
`publication_gate.enforce_disease_kb_clinically_reviewed()` directly so
each KB is exercised in isolation, without fabricating 30 stub reports
for the surrounding pipeline).
**Raw JSON**: `/tmp/W17_C2_pubgate.json`.

---

## 1. Bundled KB inventory

File: `references/methodology/disease-definition-knowledge-base.json`
(1194 lines, version per top-level `version`).

- **Total disease entries**: 11 (dict keyed by disease slug).
- **`provenance` block present**: 11 / 11.
- **`clinician_review_status` field**: 0 / 11 (field absent from every
  entry; classifier falls through to the default `pending` bucket).
- **`reviewer` field**: 11 / 11 present but **value is `null`** for every
  entry.
- **`last_reviewed` field**: 11 / 11 present but **value is `null`** for
  every entry.
- **`source` field**: 11 / 11 = `"llm_compiled"`.

### Status-bucket histogram (classifier output)

| Bucket   | Count | Notes                                                    |
| -------- | ----- | -------------------------------------------------------- |
| approved | 0     | Required triple (status ∈ APPROVED + reviewer + date) absent. |
| pending  | 11    | Default branch — no `clinician_review_status` set.       |
| missing  | 0     | No entry advertised approved-source without the triple.  |

Confirms the memory entry `project_disease_kb_provenance.md`: **0/11 of
the bundled KB entries are clinician-approved.**

### `definition_variables_to_exclude` coverage

| Metric                              | Value      |
| ----------------------------------- | ---------- |
| Entries with non-empty list         | **11 / 11 (100%)** |
| Sum across all entries              | 97 vars    |
| Per-entry range (min / median / max) | 3 / 9 / 20 |
| Entries that would silent-pass leakage_gate from empty spec | **0** |

The bundled KB itself does **not** carry the "empty-spec silent exit 0"
risk W16-B3 raised — that risk lives in *user-supplied* target specs
fed into `leakage_gate`/`definition_variable_guard`, where the
`defining_variables` field on a target block can be empty. The bundled
KB only ships 11 of Torralbo 2025's 313-disease catalog; the remaining
302 are out of scope for this audit (not present in the repo).

---

## 2. Publication gate verdicts

Driver calls the hardened `enforce_disease_kb_clinically_reviewed`
helper (W11-F2 + W13-C1 code path). `exit_code_simulated` mirrors what
`finish()` would emit for this isolated check.

| Case                          | Exit | failures | Expected | Verdict |
| ----------------------------- | ---- | -------- | -------- | ------- |
| BUNDLED_KB                    | **2** | 1 (`disease_kb_unreviewed`) | 2 | PASS |
| SPOOF-A: status=approved only | **2** | 1 (`disease_kb_unreviewed`) | 2 | PASS |
| SPOOF-B: + reviewer="Anonymous", no date | **2** | 1 (`disease_kb_unreviewed`) | 2 | PASS |
| SPOOF-C: status+reviewer + `last_reviewed=2099-01-01` | **0** | 0 | 2 | **FAIL** |

Spoof fixtures: `/tmp/W17_C2_spoofs/SPOOF_{A,B,C}_*.json`.

- **SPOOF-A** (source-only / status-only spoof) is caught — bucketed as
  `missing` with reason `"incomplete provenance — missing: reviewer,
  last_reviewed"`. W11-F2 closure holds.
- **SPOOF-B** (named-but-anonymous reviewer, no date) is caught —
  bucketed as `missing`, missing `last_reviewed`. W11-F2 closure holds.
- **SPOOF-C** (named reviewer + future-date sign-off, `2099-01-01`)
  **passes silently as `approved`**. `classify_disease` in
  `scripts/diagnostics/disease_kb_review_check.py:160-170` only checks
  that `last_reviewed` is a non-empty string; there is no
  `datetime.fromisoformat` parse, no `<= today` sanity check, no format
  validation. Any string is accepted.

---

## 3. Per-spoof detail

| Spoof | Status field | Reviewer | last_reviewed | Bucket | F2 catches? |
| ----- | ------------ | -------- | ------------- | ------ | ----------- |
| A     | `approved`   | (absent) | (absent)      | missing | YES |
| B     | `approved`   | `"Anonymous"` | (absent) | missing | YES |
| C     | `approved`   | `"Dr. Smith"` | `"2099-01-01"` | approved | **NO** |

---

## 4. Verdict: **YELLOW**

- The W11-F2 + W13-C1 hardening **does** fire fail-closed on the bundled
  KB (all 11 entries → FAIL, exit 2). The user cannot ship publication-
  grade outputs with the bundled KB unless they explicitly invoke
  `--allow-unreviewed-disease-kb` / `MLGG_ALLOW_UNREVIEWED_DISEASE_KB=1`.
- The W11-F2 closure for source-only and missing-reviewer spoofs is
  intact.
- **One residual fail-open hole**: SPOOF-C (`last_reviewed=2099-01-01`)
  bypasses the gate. A malicious or sloppy reviewer can backdate /
  futuredate their sign-off with no format or temporal sanity check. The
  field's audit-trail value is materially degraded by this.

This is YELLOW (not RED) because exploiting it requires an adversarial
or careless human edit to provenance — it is not a default state and
cannot be reached by accident. But for an audit trail meant to bind
Nature Medicine / Lancet Digital Health-class claims to a named
clinician, "any string is accepted in the date field" is below the bar.

---

## 5. Wave-N+ fix candidates

1. **Wave-18 [HIGH]** — Extend `classify_disease` in
   `scripts/diagnostics/disease_kb_review_check.py` to parse
   `last_reviewed` as `datetime.date.fromisoformat` and require
   `1990-01-01 <= last_reviewed <= today`. Reject future-dated and
   malformed dates with a new bucket code
   `clinician_review_invalid_date`. Add a positive-control unit test in
   `tests/diagnostics/test_disease_kb_review_check.py` using the SPOOF-C
   fixture pattern.
2. **Wave-18 [HIGH]** — Add a reviewer-identity allow-list or at least
   a min-length / regex check (e.g., reject `"Anonymous"`, `"TBD"`,
   `"-"`, single-char names). Currently any non-empty string passes.
3. **Wave-19 [MED]** — Require a `reviewer_orcid` or
   `reviewer_institutional_email` field next to `reviewer` so the audit
   trail binds to a real-world identity rather than a free-text name.
4. **Wave-19 [MED]** — Document the SPOOF-C result in
   `references/methodology/DISEASE_KB_REVIEW.md` so reviewers know the
   gate currently trusts the date string verbatim.

---

## 6. Artifacts

- `/tmp/W17_C2_pubgate.json` — raw driver output (all 4 cases).
- `/tmp/W17_C2_driver.py` — verification driver source.
- `/tmp/W17_C2_kb_review.json` — standalone
  `disease_kb_review_check.py` report on the bundled KB.
- `/tmp/W17_C2_spoofs/SPOOF_{A,B,C}_*.json` — three spoof fixtures.
