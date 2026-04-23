#!/usr/bin/env python3
"""Verify UKB codebook completeness and integrity.

Runs 3 layers of checks (see references/codebooks/ukb/KNOWN_GAPS.md):

    L1 — source fidelity:   .txt file sha256 + byte + line count match
                            committed source_manifest.json
    L2 — structural invariants: count assertions + FK integrity +
                            ICD/OPCS dict sizes + no duplicate field_ids
    L3 — golden-seed ground truth: known-famous UKB fields exist with
                            the expected metadata (ukb_golden_fields.yaml)

Exits 0 on clean pass, 2 on any violation.

Usage:
    python3 scripts/codebooks/verify_ukb_codebook.py
    python3 scripts/codebooks/verify_ukb_codebook.py --skip-l1
    python3 scripts/codebooks/verify_ukb_codebook.py --report /tmp/ukb_verify.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UKB_DIR = REPO_ROOT / "references" / "codebooks" / "ukb"
DEFAULT_DB = UKB_DIR / "ukb_codebook.sqlite"
DEFAULT_MANIFEST = UKB_DIR / "source_manifest.json"
DEFAULT_GOLDEN = UKB_DIR / "ukb_golden_fields.yaml"


# ── L2: structural invariants — baseline counts & hard invariants ───
# Baselines captured 2026-04-23; tolerate ±0.5% drift for each count
# in case UKB adds/removes a handful of fields between refreshes.
_COUNTS = {
    # (label, sql, expected, tolerance_pct)
    "fields_total":        ("SELECT COUNT(*) FROM fields;",                                                11821, 0.5),
    "categories_total":    ("SELECT COUNT(*) FROM categories;",                                              410, 5.0),
    "encodings_total":     ("SELECT COUNT(*) FROM encodings;",                                               858, 5.0),
    # Round-9 strict-review: csv.QUOTE_NONE fix recovered 66,379
    # rows of CTV3 clinical codes (encoding 7128 in esimpstring.txt)
    # that were silently dropped by csv.DictReader's default quote
    # handling. Total 466,907 → 533,286.
    # Tolerance tightened 1% → 0.1% (±533 rows). Per-encoding pins
    # for enc3/5/6/1006 (HARD above) catch full category drops.
    "encoding_values":     ("SELECT COUNT(*) FROM encoding_values;",                                      533286, 0.1),
    "icd10_codes":         ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=19;",                  19190, 0.5),
    "icd9_codes":          ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=87;",                  13710, 0.5),
    "opcs4_codes":         ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=240;",                 11288, 0.5),
    "nmr_cat_220":         ("SELECT COUNT(*) FROM fields WHERE main_category=220;",                          251, 0.5),
}

# Hard invariants (must be exact, no tolerance).
_HARD = {
    "duplicate_field_ids": (
        "SELECT COUNT(*) FROM (SELECT field_id FROM fields GROUP BY field_id HAVING COUNT(*) > 1);",
        0,
        "Fields table has duplicate field_id values — primary-key violation.",
    ),
    "bmi_21001":   ("SELECT COUNT(*) FROM fields WHERE field_id=21001;", 1, "Field 21001 (BMI) missing."),
    "hba1c_30750": ("SELECT COUNT(*) FROM fields WHERE field_id=30750;", 1, "Field 30750 (HbA1c) missing."),
    # 2026-04-23 strict audit fixed a missing catbrowse.txt loader:
    # the category hierarchy was not imported and every category had
    # parent_id=NULL, breaking tree-traversal queries. Assert that
    # ≥300 of the 410 categories have a non-null parent so the
    # regression can't silently return.
    "categories_with_parent_gte_300": (
        "SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL AND parent_id != 0;",
        # Note: this is a >= check semantically. The comparison in
        # check_hard_invariants is equality, so we express the
        # boundary via a different query that returns 1 if healthy.
        # Keep this marker here and enforce via the alternative
        # query below to avoid changing the tuple shape elsewhere.
        361,
        "Fewer than 300 categories have a parent — catbrowse.txt may "
        "not be loading. Check build_ukb_codebook_db.py step 1.",
    ),
    # Instance metadata — 9 instances had empty title/description
    # before the 2026-04-23 fix; assert none remain empty.
    "instances_with_title": (
        "SELECT COUNT(*) FROM instances WHERE title IS NOT NULL AND trim(title) != '';",
        13,
        "Some instances missing title — insvalue.txt column mapping "
        "may have regressed (columns are instance_id / descript / num_members).",
    ),
    # UKB ships 319 private=1 fields. 2026-04-23 strict audit split
    # these into:
    #   - 193 real PHI identifiers → risk_category='identifier_direct'
    #   - 126 EMBARGOED future-release imaging → risk_category='embargoed'
    # Sum must still equal 319 (the private=1 total from UKB); any
    # drift means either UKB changed the count OR our classifier
    # stopped distinguishing the two categories.
    "phi_fields_correctly_flagged": (
        "SELECT COUNT(*) FROM fields WHERE private=1 AND risk_category='identifier_direct';",
        193,
        "Private=1 real-PHI fields must carry risk_category="
        "'identifier_direct'. If this drops, classify_field() may be "
        "misclassifying DOB / home-location etc. as embargoed.",
    ),
    "embargoed_count": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='embargoed';",
        126,
        "EMBARGOED future-release fields count changed. UKB may have "
        "unlocked some (good — migrate to real category) or removed "
        "the EMBARGOED prefix convention.",
    ),
    "private_total_still_319": (
        "SELECT COUNT(*) FROM fields WHERE private=1;",
        319,
        "UKB private=1 field total drifted. Either UKB revised "
        "privacy flags or fetch returned a different snapshot.",
    ),
    "no_private_labeled_baseline": (
        "SELECT COUNT(*) FROM fields WHERE private=1 AND risk_category='baseline';",
        0,
        "Private=1 fields must NEVER be labeled 'baseline' "
        "(leakage-guard would treat them as safe).",
    ),
    # Alias floor: we committed 106 entries as of 2026-04-23 (after
    # semantic audit fixed 5 incorrect first-occurrence mappings and
    # added 4 specific-disease aliases). Drift alerts on any change;
    # additions welcome — grow past this by bumping the number in
    # the same commit.
    "alias_floor": (
        "SELECT COUNT(*) FROM aliases;",
        106,
        "Alias table shrank — medical-term lookups degrade. Re-add "
        "removed mappings in COMMON_ALIASES (build_ukb_codebook_db.py).",
    ),
    # ICD-10 / ICD-9 / OPCS-4 parent chain — previously 100%
    # broken (parent_code stored UKB-internal numeric code_id instead
    # of the actual parent value string). After 2026-04-23 two-pass
    # fix, every parent_code resolves to a real code in the same
    # encoding, or is NULL for root nodes.
    "icd10_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=19 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=19);",
        0,
        "Some ICD-10 parent_code values don't exist in the table. "
        "build_ukb_codebook_db.py hierarchical loader likely regressed.",
    ),
    "icd9_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=87 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=87);",
        0, "ICD-9 parent chain broken.",
    ),
    "opcs4_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=240 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=240);",
        0, "OPCS-4 parent chain broken.",
    ),
    # Block-level aggregators (e.g., "Block A00-A09") must be marked
    # selectable=0 so lookups don't silently include them. Before the
    # 2026-04-23 fix selectable was mis-parsed as Y/N heuristic and
    # always returned 1.
    "icd10_block_level_nonselectable": (
        "SELECT COUNT(*) FROM encoding_values "
        "WHERE encoding_id=19 AND selectable=0 AND code LIKE 'Block %';",
        264,
        "ICD-10 block-level codes must carry selectable=0. "
        "selectable parser may have regressed to Y/N heuristic.",
    ),
    # ICD-9 and OPCS-4 use a stricter hierarchy convention than ICD-10:
    # selectable=0 iff the code has children. Round-3 audit (2026-04-23)
    # confirmed every selectable=0 row in encodings 87 (ICD-9) and 240
    # (OPCS-4) is a true aggregator — 0 leaf rows. Pinning this invariant
    # catches any future regression where a leaf code gets marked
    # non-selectable (lookup would silently skip it) or an aggregator
    # gets marked selectable (diagnoses would be coded at the wrong level).
    "icd9_selectable_zero_iff_has_children": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=87 AND ev.selectable=0 "
        "AND NOT EXISTS (SELECT 1 FROM encoding_values c "
        "                WHERE c.encoding_id=87 AND c.parent_code=ev.code);",
        0,
        "ICD-9 has selectable=0 rows without children — either a leaf "
        "got mis-parsed as non-selectable, or a broken hierarchy dropped "
        "the children. Round-3 invariant: every non-selectable ICD-9 "
        "code must be a true aggregator (has >=1 child).",
    ),
    "opcs4_selectable_zero_iff_has_children": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=240 AND ev.selectable=0 "
        "AND NOT EXISTS (SELECT 1 FROM encoding_values c "
        "                WHERE c.encoding_id=240 AND c.parent_code=ev.code);",
        0,
        "OPCS-4 has selectable=0 rows without children — same failure "
        "shape as ICD-9. Either selectable parser regressed or the "
        "hierarchical loader dropped children on a category.",
    ),
    # Companion count invariants for ICD-9 / OPCS-4 aggregator totals,
    # mirroring the ICD-10 block-level pin above. 2026-04-23 values:
    # ICD-9 = 153 aggregators, OPCS-4 = 1590 aggregators.
    "icd9_aggregator_count": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=87 AND selectable=0;",
        2073,
        "ICD-9 non-selectable (aggregator) count drifted from 2073. "
        "UKB may have refreshed the ICD-9 dictionary — investigate.",
    ),
    "opcs4_aggregator_count": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=240 AND selectable=0;",
        1590,
        "OPCS-4 non-selectable (aggregator) count drifted from 1590. "
        "UKB may have refreshed the OPCS-4 dictionary — investigate.",
    ),
    # Hierarchical heading preservation: 2026-04-23 strict audit found
    # 104 category-heading rows silently collapsed because the previous
    # PK (encoding_id, code) didn't tolerate repeated code='-1' rows
    # that UKB uses for non-leaf nodes in encodings 3/5/6/1003/1005/1006
    # (Cancer / Operation / Non-cancer Illness self-reported trees, used
    # by fields 20001/20002/20004). Fixed by widening PK with node_id
    # (UKB's internal code_id). Pin the exact source-row counts so the
    # bug can't silently return.
    "enc5_operation_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=5;",
        270,
        "Operation tree (encoding 5, field 20004) lost rows — check "
        "build PK / node_id handling in hierarchical loader.",
    ),
    "enc6_noncancer_illness_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=6;",
        474,
        "Non-cancer-illness tree (encoding 6, field 20002) lost rows.",
    ),
    "enc3_cancer_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=3;",
        89,
        "Cancer tree (encoding 3, field 20001) lost rows.",
    ),
    "enc1006_noncancer_retyped_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=1006;",
        479,
        "Non-cancer illness (re-typed) tree lost rows.",
    ),
    # Round-9: CTV3 clinical codes (used in UK primary care / GP
    # records). 66,379 of 332,115 rows were silently dropped by the
    # csv.DictReader default-quoting bug until the QUOTE_NONE fix.
    # Pin at exact source-file count so any regression trips here
    # before downstream GP-code lookups start returning NULL.
    "enc7128_ctv3_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=7128;",
        332115,
        "CTV3 clinical codes (encoding 7128) lost rows — check the "
        "csv.QUOTE_NONE setting in read_tab_file().",
    ),
    # Every hierarchical row with a parent_node_id must point to an
    # existing node in the same encoding — verifies the heading-to-
    # heading DAG is fully connected.
    "hierarchical_parent_node_orphans": (
        "SELECT COUNT(*) FROM encoding_values child "
        "WHERE child.parent_node_id IS NOT NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM encoding_values parent "
        "  WHERE parent.encoding_id=child.encoding_id "
        "  AND parent.node_id=child.parent_node_id"
        ");",
        0,
        "Some hierarchical rows reference a parent_node_id that doesn't "
        "exist — DAG broken. Heading preservation or code_id parsing may "
        "have regressed.",
    ),
    # parent_code must agree with parent_node_id when both are set —
    # the two-pass builder translates parent_id → parent's value via
    # the code_id_to_value map. Any mismatch means the translation
    # logic has drifted (e.g., the map was overwritten during a
    # heading collision before the PK fix). 0 means perfect
    # consistency.
    "parent_code_agrees_with_parent_node": (
        "SELECT COUNT(*) FROM encoding_values child "
        "WHERE child.parent_code IS NOT NULL "
        "AND child.parent_node_id IS NOT NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM encoding_values parent "
        "  WHERE parent.encoding_id=child.encoding_id "
        "  AND parent.node_id=child.parent_node_id "
        "  AND parent.code=child.parent_code"
        ");",
        0,
        "parent_code disagrees with parent_node_id — translation logic "
        "regressed. Check two-pass code_id_to_value build in the "
        "hierarchical loader.",
    ),
    # 2026-04-23 deep-check: ECG automated-diagnoses fields and the
    # COVID self-report cat (1511) were classified as baseline, which
    # would let a leakage-guard treat them as safe features. Both are
    # outcome labels. Pin field 12653 and cat-1511 fields as
    # outcome_derived so a classifier regression is caught.
    "ecg_diagnoses_are_outcome": (
        "SELECT COUNT(*) FROM fields WHERE field_id=12653 "
        "AND risk_category='outcome_derived';",
        1,
        "Field 12653 (ECG automated diagnoses) must be outcome_derived. "
        "If this fails the 'automated diagnos' rule in classify_field() "
        "regressed.",
    ),
    "covid_selfreport_outcome_count": (
        "SELECT COUNT(*) FROM fields WHERE main_category=1511 "
        "AND risk_category='outcome_derived';",
        8,
        "Cat 1511 (COVID self-report) fields must all be outcome_derived. "
        "If this drops, classify_field() lost the cat==1511 override and "
        "COVID diagnosis events are back to baseline.",
    ),
    # 2026-04-23 deep-check: 1625 fields under UKB's "Online follow-up"
    # tree (root cat 100089, ~79 descendant cats) were labeled baseline
    # because classifier domain rules (mental_health, cognitive,
    # lifestyle, medical) map them to baseline risk. These are
    # POST-BASELINE questionnaires — using them as baseline features
    # in a temporal-leakage-sensitive model is wrong. Build-time
    # override promotes baseline→online_followup for any descendant
    # of cat 100089. Pin: ZERO fields in this tree may be 'baseline'.
    "no_baseline_under_online_followup_tree": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND main_category IN (WITH RECURSIVE d(cid) AS ("
        "  SELECT category_id FROM categories WHERE title='Online follow-up' "
        "  UNION ALL SELECT c.category_id FROM categories c JOIN d ON c.parent_id=d.cid"
        ") SELECT cid FROM d);",
        0,
        "Fields under the Online follow-up tree must not be risk "
        "'baseline' — they're collected AFTER the baseline visit. "
        "Check the online-followup override in build_ukb_codebook_db.py.",
    ),
    # 2026-04-23 round-6: accelerometry (cats 1008-1013, 1020) are
    # POST-BASELINE by mail — UKB shipped accelerometers 2013-2015,
    # years after baseline (2006-2010). Previously labeled 'baseline'.
    # 211 fields must now carry online_followup risk.
    "accelerometry_is_online_followup": (
        "SELECT COUNT(*) FROM fields WHERE domain='accelerometry' "
        "AND risk_category='online_followup';",
        211,
        "Accelerometry fields must be online_followup, not baseline. "
        "UKB wore-by-mail device is post-baseline data.",
    ),
    "no_accelerometry_baseline": (
        "SELECT COUNT(*) FROM fields WHERE domain='accelerometry' "
        "AND risk_category='baseline';",
        0,
        "Accelerometry fields must not be risk_category='baseline' — "
        "leakage-guard would treat post-baseline sensor data as safe.",
    ),
    # Every field with encoding_id must reference a real encoding.
    # Previous L1 sha-pin catches source corruption; this catches
    # builder-side FK breakage.
    "fields_with_orphan_encoding": (
        "SELECT COUNT(*) FROM fields WHERE encoding_id IS NOT NULL "
        "AND encoding_id != 0 AND encoding_id NOT IN "
        "(SELECT encoding_id FROM encodings);",
        0,
        "Some fields reference an encoding_id that doesn't exist in "
        "the encodings table — FK broken.",
    ),
    # Category full_path hierarchy: 2026-04-23 deep-check found 362/410
    # paths were wrong (only single-title stubs) because the builder
    # computed paths BEFORE catbrowse.txt was merged, so parent lookups
    # returned None for every non-root. Fix: compute after catbrowse.
    # Pin exact counts so the step ordering can't silently regress.
    "categories_with_hierarchy_path": (
        "SELECT COUNT(*) FROM categories WHERE full_path LIKE '%>%';",
        361,
        "Hierarchical full_path count dropped — build_ukb_codebook_db.py "
        "may have reverted catbrowse-before-path ordering.",
    ),
    "categories_depth_ge_3": (
        "SELECT COUNT(*) FROM categories "
        "WHERE (length(full_path) - length(replace(full_path, '>', ''))) >= 2;",
        316,
        "Deep-hierarchy category count dropped — full_path walk may "
        "be terminating too early (visited-set bug or parent mismatch).",
    ),
    # FTS5 ↔ fields parity: every field must be searchable, no phantom
    # FTS rows. If rebuild() was skipped or the trigger to sync missed
    # an insert, lookups silently return nothing.
    "fts_matches_fields_count": (
        "SELECT (SELECT COUNT(*) FROM fields_fts) = (SELECT COUNT(*) FROM fields);",
        1, "FTS5 row count drifted from fields — index out of sync.",
    ),
    "fts_missing_no_fields": (
        "SELECT COUNT(*) FROM fields WHERE field_id NOT IN "
        "(SELECT rowid FROM fields_fts);",
        0, "Some fields have no FTS row — rebuild fields_fts.",
    ),
    "fts_no_phantom_rows": (
        "SELECT COUNT(*) FROM fields_fts WHERE rowid NOT IN "
        "(SELECT field_id FROM fields);",
        0, "FTS5 has rows without a backing field — stale index.",
    ),
    # Cat 2 follow-up audit (2026-04-23): fields 190/191 (lost-to-follow-up)
    # and 20143/20144/20145/110007 (post-baseline recontact/communication
    # log) were previously swept into 'demographics, baseline' by the
    # generic cat=2 rule. A leakage-guard would then treat cohort
    # attrition outcomes as safe predictors. The targeted
    # participant_admin rule in classify_field() must keep them flagged.
    "cat2_followup_fields_flagged": (
        "SELECT COUNT(*) FROM fields "
        "WHERE field_id IN (190, 191, 20143, 20144, 20145, 110007) "
        "AND risk_category='online_followup';",
        6,
        "Cat 2 lost-to-follow-up / contact-log fields must carry "
        "risk_category='online_followup'. If this drops, the "
        "participant_admin rule in classify_field() may have been "
        "broadened or removed and these fields fell back to 'baseline'.",
    ),
    "field_20005_stays_baseline": (
        # Email access is asked at the assessment visit itself — NOT a
        # post-baseline artifact — and shares cat 2 with the follow-up/
        # admin fields. A too-broad rule would sweep it up. The guard
        # asserts the title-scoped rule doesn't reach this field.
        "SELECT COUNT(*) FROM fields "
        "WHERE field_id=20005 AND risk_category='baseline';",
        1,
        "Email access (20005) must remain baseline. If this fails, the "
        "participant_admin rule was broadened to a raw cat==2 check.",
    ),
    # ── Leakage-keyword reverse scan ────────────────────────────────
    # Positive guardrail: no field in risk_category='baseline' may
    # carry a title that clearly describes a post-baseline/outcome/
    # death event. The 6-round deep-check audits kept finding misses
    # by manual inspection; this pins the pattern automatically.
    # Keyword list is deliberately conservative (all currently yield
    # zero hits on a clean DB) — so this will only fire on a real
    # regression, not on borderline cases. If a true positive ever
    # appears that should legitimately stay baseline, add an
    # explicit field_id carveout comment and a separate _HARD rule
    # rather than weakening this check.
    "baseline_titles_no_lost_to_followup": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND LOWER(title) LIKE '%lost to follow%';",
        0,
        "Baseline field has 'lost to follow-up' in its title — this is "
        "cohort attrition, an outcome. classify_field's "
        "participant_admin rule should catch it.",
    ),
    "baseline_titles_no_death_event": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND (LOWER(title) LIKE '%date of death%' "
        "     OR LOWER(title) LIKE '%cause of death%' "
        "     OR LOWER(title) LIKE '%deceased%');",
        0,
        "Baseline field has a death-event title — this is a registry "
        "outcome, not a baseline covariate. Move to death_registry.",
    ),
    "baseline_titles_no_first_occurrence": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND (LOWER(title) LIKE '%first reported%' "
        "     OR LOWER(title) LIKE '%first occurrence%');",
        0,
        "Baseline field has 'first reported' / 'first occurrence' in "
        "title — this is a first-occurrence ICD date, outcome_derived.",
    ),
    "baseline_titles_no_algorithmically_defined": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND LOWER(title) LIKE '%algorithmically defined%';",
        0,
        "Baseline field has 'algorithmically defined' in title — this "
        "is a derived outcome label, should be outcome_derived.",
    ),
    "baseline_titles_no_followup_years": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='baseline' "
        "AND LOWER(title) LIKE '%years%follow%up%';",
        0,
        "Baseline field has 'years follow-up' — this is a cohort "
        "follow-up duration, not a baseline covariate.",
    ),

    # ── Encoding FK completeness (C) ────────────────────────────────
    # fields_with_orphan_encoding (above) checks against the
    # `encodings` metadata table. But an encoding_id can exist in
    # `encodings` with ZERO rows in `encoding_values` — the encoding
    # is registered but empty. A field that lookups through it gets
    # an unresolvable label. Pin that this never happens for the
    # encoding types we actually load.
    #
    # Exclusion: coded_as='61' is UKB's time type. UKB does NOT ship
    # an esimptime.txt alongside esimpint/string/real/date, so every
    # coded_as=61 encoding ends up with zero rows on our side even
    # though `encodings` advertises them. Known values: encoding_ids
    # 439 ("Not performed") and 1439 ("Time conditions"), used by
    # time-valued fields like 3166 "Time blood sample collected" and
    # the AFib first-occurrence timestamps. These are an upstream
    # schema quirk, not a builder regression.
    "fields_pointing_to_empty_encoding": (
        "SELECT COUNT(DISTINCT f.encoding_id) FROM fields f "
        "WHERE f.encoding_id IS NOT NULL AND f.encoding_id != 0 "
        "AND NOT EXISTS (SELECT 1 FROM encoding_values ev "
        "                WHERE ev.encoding_id=f.encoding_id) "
        "AND (SELECT coded_as FROM encodings e "
        "     WHERE e.encoding_id=f.encoding_id) != '61';",
        0,
        "A non-time encoding is referenced by a field but has zero "
        "rows in encoding_values — lookup will silently return empty "
        "labels. Check the hierarchical/simple loaders populated "
        "every encoding that the `encodings` table advertises.",
    ),
    # Companion invariant: the known coded_as=61 orphan count is
    # expected to be exactly 2. If UKB adds a new time-encoded
    # lookup this will climb, and we'll want to notice.
    "time_encodings_known_orphans": (
        "SELECT COUNT(DISTINCT f.encoding_id) FROM fields f "
        "WHERE f.encoding_id IS NOT NULL AND f.encoding_id != 0 "
        "AND NOT EXISTS (SELECT 1 FROM encoding_values ev "
        "                WHERE ev.encoding_id=f.encoding_id) "
        "AND (SELECT coded_as FROM encodings e "
        "     WHERE e.encoding_id=f.encoding_id) = '61';",
        2,
        "Time-typed orphan encoding count drifted from 2 (439, 1439). "
        "Either UKB added a new time encoding (investigate — may need "
        "a new esimptime.txt loader) or one of the known two got "
        "populated unexpectedly.",
    ),

    # ── Round-2 structural audit (2026-04-23) ────────────────────────
    # The three pins below come from a systematic sweep after all the
    # classify_field deep-check rounds. Each catches a different class
    # of silent failure:

    # (1) First-occurrence fields escaping outcome_derived.
    # Any field whose title reads 'First Occurrence' / 'First Reported'
    # MUST carry risk_category='outcome_derived' OR 'identifier_direct'
    # (the latter because UKB's cardiac monitoring cat 348/349 fields
    # — 12 of them — are private=1, which takes priority in
    # classify_field). If UKB ever drops the private=1 flag on those
    # cats, they would fall through to 'baseline' silently and a
    # leakage gate would pass them as safe features. This invariant
    # catches that flip.
    "first_occurrence_titles_in_outcome_or_phi": (
        "SELECT COUNT(*) FROM fields "
        "WHERE (LOWER(title) LIKE '%first reported%' "
        "       OR LOWER(title) LIKE '%first occurrence%') "
        "AND risk_category NOT IN ('outcome_derived', 'identifier_direct');",
        0,
        "First-occurrence title fields must be 'outcome_derived' or "
        "'identifier_direct'. If they land anywhere else (esp. "
        "'baseline' or 'imaging'), classify_field() regressed — "
        "investigate cat 348/349 cardiac monitoring and cat 1712 "
        "first-occurrence rules.",
    ),

    # (2) COVID schema quirk: fields 41000 and 41001 declare
    # instanced=0 but instance_min=instance_max=3. UKB's upstream
    # schema is inconsistent on these two. Our field_to_rap_names()
    # returns 'p41000' (bare, honoring instanced=0), which may or may
    # not match what RAP actually serves — we can only know via a
    # real RAP smoke test. Pin the count at 2 so any NEW instance of
    # this quirk surfaces for investigation.
    "instanced_zero_with_instance_max_known": (
        "SELECT COUNT(*) FROM fields "
        "WHERE (instanced=0 OR instanced IS NULL) "
        "AND instance_max IS NOT NULL AND instance_max > 0;",
        2,
        "Fields with instanced=0 but instance_max>0 drifted from 2 "
        "(known: 41000/41001 COVID imaging repeat). RAP column name "
        "for any new such field is ambiguous — investigate whether "
        "field_to_rap_names() should emit p{fid} or p{fid}_i{inst_max}.",
    ),

    # (3) Hierarchical encoding_values parent_code self-loops.
    # 65 rows have parent_code == code — all are UKB's '-1' heading
    # sentinel in encodings 5/6/1005/1006 (Operation / Non-cancer
    # Illness trees). Tree-traversal code that walks parent_code
    # hits infinite recursion on these. Known structural quirk;
    # pinned to catch any new self-loop.
    "parent_code_self_loops_known": (
        "SELECT COUNT(*) FROM encoding_values "
        "WHERE parent_code IS NOT NULL AND parent_code=code;",
        65,
        "parent_code self-loop count drifted from 65 (known UKB "
        "heading sentinel convention in encodings 5/6/1005/1006). "
        "Any new self-loop breaks hierarchical traversal — either "
        "the build script regressed or UKB added a new hierarchy "
        "with the same convention.",
    ),
}

# Ceiling checks — values we tolerate today but flag as technical debt
# if they rise. Not errors; useful signal for the operator.
_CEILINGS = {
    "orphan_field_cats": (
        "SELECT COUNT(*) FROM fields f WHERE f.main_category NOT IN (SELECT category_id FROM categories);",
        126,
        "Fields pointing to a main_category that is not in categories table.",
    ),
    # 2026-04-23 deep-check: classifier misses reduced 498 → 15 by
    # adding eye/genomics/covid/dMRI/hearing/verbal-interview/online-
    # follow-up sub-categories. If this climbs, UKB has added new
    # categories that need mapping in classify_field().
    "unclassified_domain_other": (
        "SELECT COUNT(*) FROM fields WHERE domain='other';",
        5,
        "Unclassified fields (domain='other') rising — extend "
        "classify_field() with new UKB sub-category ids. 2026-04-23 "
        "round-7 drove this to 0 by mapping cats 147/100061/100073/"
        "100077/100095.",
    ),
    # Note: removed the "alias_thinness" ceiling — the check direction
    # was inverted (growth is GOOD, not a warning). Floor enforced in
    # _HARD below.
}


def _row(conn: sqlite3.Connection, sql: str) -> int:
    """Run a scalar SQL query and return the first int value."""
    cur = conn.execute(sql)
    result = cur.fetchone()
    return int(result[0]) if result else 0


# ── Content-facet hashes ─────────────────────────────────────────────
# L1 pins .txt sha256 (upstream source). L2 pins counts + specific
# facts. But neither catches silent content drift: e.g. classify_field
# quietly flips 1000 fields from baseline→online_followup — counts can
# move inside tolerance, L2 facts stay green, and no audit trail
# notices. These four facet hashes make every such change visible.
#
# Each facet drifts at a different rate, so they're reported
# separately:
#   - source_titles   : field_id → title. Changes only when UKB
#                       refreshes the Showcase (→ L1 sha256 drifts too).
#   - classification  : field_id → (domain, risk_category). Changes
#                       every classify_field() update — expect 5-10
#                       commits per round of deep-check.
#   - encoding_values : (encoding_id, code) → (meaning, selectable,
#                       parent_code). Changes only with UKB schema
#                       refresh.
#   - aliases         : alias → field_id. Changes with curation.
#
# By default these are only REPORTED (printed + in --report JSON).
# If source_manifest.json has a content_hashes block, drift against
# it is emitted as a warning. Use --strict-content-hashes to fail
# the verify on drift — useful for release-gate CI.


def compute_content_hashes(conn: sqlite3.Connection) -> Dict[str, str]:
    """Compute sha256 per content-facet. Deterministic across runs."""
    import hashlib

    def _h(rows, fmt: str) -> str:
        payload = "\n".join(fmt.format(*r) for r in rows).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    source_rows = conn.execute(
        "SELECT field_id, COALESCE(title,'') FROM fields ORDER BY field_id"
    ).fetchall()
    classification_rows = conn.execute(
        "SELECT field_id, COALESCE(domain,''), COALESCE(risk_category,'') "
        "FROM fields ORDER BY field_id"
    ).fetchall()
    encoding_rows = conn.execute(
        "SELECT encoding_id, code, COALESCE(meaning,''), "
        "COALESCE(selectable,-1), COALESCE(parent_code,'') "
        "FROM encoding_values ORDER BY encoding_id, code"
    ).fetchall()
    alias_rows = conn.execute(
        "SELECT alias, field_id FROM aliases ORDER BY alias, field_id"
    ).fetchall()

    return {
        "source_titles":   _h(source_rows, "{0}|{1}"),
        "classification":  _h(classification_rows, "{0}|{1}|{2}"),
        "encoding_values": _h(encoding_rows, "{0}|{1}|{2}|{3}|{4}"),
        "aliases":         _h(alias_rows, "{0}|{1}"),
    }


def check_content_hash_drift(
    computed: Dict[str, str],
    manifest_path: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """Compare computed hashes against the optional `content_hashes`
    block in source_manifest.json. Returns (drift_warnings, detail).
    """
    warnings: List[str] = []
    pinned: Dict[str, str] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pinned = manifest.get("content_hashes") or {}
        except (OSError, json.JSONDecodeError):
            pass
    for key, c_hash in computed.items():
        p_hash = pinned.get(key)
        if p_hash and p_hash != c_hash:
            warnings.append(
                f"{key}: pinned {p_hash[:12]}… drifted to {c_hash[:12]}… "
                f"— investigate build logs or regenerate with "
                f"--print-content-hashes if this change is intentional"
            )
    return warnings, {"pinned": pinned, "computed": computed}


# ── L1 ──────────────────────────────────────────────────────────────

def check_source_manifest(
    ukb_dir: Path, manifest_path: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """Compare live .txt files in ukb_dir against committed manifest.

    Returns (issues, summary_dict).
    """
    issues: List[str] = []
    summary: Dict[str, Any] = {"files_checked": 0, "drift": []}
    if not manifest_path.exists():
        issues.append(f"manifest missing: {manifest_path}")
        return issues, summary
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"manifest unreadable: {exc}")
        return issues, summary
    for fname, entry in manifest.get("files", {}).items():
        path = ukb_dir / fname
        if not path.exists():
            issues.append(f"{fname}: not found locally")
            summary["drift"].append(fname)
            continue
        data = path.read_bytes()
        live_sha = hashlib.sha256(data).hexdigest()
        live_bytes = len(data)
        live_lines = data.count(b"\n")
        if live_sha != entry.get("sha256"):
            issues.append(f"{fname}: sha256 drift "
                          f"(ref={entry.get('sha256', '?')[:16]}, got={live_sha[:16]})")
            summary["drift"].append(fname)
        if live_bytes != entry.get("bytes"):
            issues.append(f"{fname}: byte count drift "
                          f"(ref={entry.get('bytes')}, got={live_bytes})")
        if live_lines != entry.get("lines"):
            issues.append(f"{fname}: line count drift "
                          f"(ref={entry.get('lines')}, got={live_lines})")
        summary["files_checked"] += 1
    return issues, summary


# ── L2 ──────────────────────────────────────────────────────────────

def check_counts(conn: sqlite3.Connection) -> Tuple[List[str], Dict[str, Any]]:
    """Assert baseline counts within tolerance."""
    issues: List[str] = []
    detail: Dict[str, Any] = {}
    for label, (sql, expected, tol_pct) in _COUNTS.items():
        actual = _row(conn, sql)
        low = int(expected * (1 - tol_pct / 100))
        high = int(expected * (1 + tol_pct / 100))
        detail[label] = {"actual": actual, "expected": expected,
                         "tolerance_pct": tol_pct}
        if not (low <= actual <= high):
            issues.append(
                f"{label}: {actual} not in [{low}, {high}] "
                f"(expected ~{expected}, ±{tol_pct}%)"
            )
    return issues, detail


def check_hard_invariants(conn: sqlite3.Connection) -> List[str]:
    """Assert hard invariants (exact-match)."""
    issues: List[str] = []
    for label, (sql, expected, message) in _HARD.items():
        actual = _row(conn, sql)
        if actual != expected:
            issues.append(f"{label}: got {actual}, expected {expected} — {message}")
    return issues


def check_ceilings(conn: sqlite3.Connection) -> List[str]:
    """Report ceilings as warnings only (debt signal, not error)."""
    warnings: List[str] = []
    for label, (sql, ceiling, message) in _CEILINGS.items():
        actual = _row(conn, sql)
        if actual > ceiling:
            warnings.append(
                f"{label}: {actual} exceeds known ceiling {ceiling} — {message}"
            )
    return warnings


def check_source_encoding(ukb_dir: Path) -> Tuple[List[str], Dict[str, int]]:
    """Count non-UTF-8 bytes per source file.

    UKB .txt files are mostly UTF-8 but round-9 strict-review found
    category.txt has 2 stray 0x97 bytes (cp1252 em-dash). The builder
    now recovers these via a cp1252 fallback handler, but we still
    track the total so a sudden surge (UKB switching encoding) fires
    a loud warning. Zero would be ideal; >5 triggers investigation.
    """
    issues: List[str] = []
    detail: Dict[str, int] = {}
    for txt in sorted(ukb_dir.glob("*.txt")):
        raw = txt.read_bytes()
        bad = 0
        pos = 0
        while pos < len(raw):
            try:
                raw[pos:].decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                bad += 1
                pos += exc.start + 1
        detail[txt.name] = bad
        if bad > 5:
            issues.append(
                f"{txt.name}: {bad} non-UTF-8 bytes (threshold 5). UKB "
                "may have switched encoding; investigate before trusting "
                "text-heavy fields (notes, descriptions)."
            )
    return issues, detail


def check_source_vs_db_row_counts(
    ukb_dir: Path, conn: sqlite3.Connection,
) -> List[str]:
    """Compare raw-source row count to DB row count per table.

    Round-9 strict-review found 66,379 silent row drops from the CSV
    quote-merge bug — undetectable by existing checks because the
    source manifest only pins file sha256 (correct) and the L2
    encoding_values count was ±1% tolerance (too loose). This check
    counts source lines directly and compares to the DB row count,
    catching any future silent-drop regressions regardless of cause.

    Returns issues. Expected: zero diff for fields / encodings /
    categories / encoding_values. instances is +1 because the
    builder seeds well-known instances 0-3; that +1 is tolerated.
    """
    issues: List[str] = []
    tables = {
        "fields": "field.txt",
        "encodings": "encoding.txt",
        "categories": "category.txt",
    }
    for tbl, fname in tables.items():
        path = ukb_dir / fname
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = sum(1 for _ in f) - 1  # minus header
        dbc = _row(conn, f"SELECT COUNT(*) FROM {tbl}")
        if src != dbc:
            issues.append(
                f"{tbl}: source={src} vs db={dbc} (diff={src - dbc}). "
                "A silent-drop bug in the builder. Start with "
                "read_tab_file and any per-row `if` filters."
            )
    # encoding_values: sum of all 4 simp + 2 hier files.
    ev_src = 0
    for fname in ("esimpint.txt", "esimpstring.txt", "esimpreal.txt",
                  "esimpdate.txt", "ehierint.txt", "ehierstring.txt"):
        path = ukb_dir / fname
        if path.exists():
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                ev_src += sum(1 for _ in f) - 1
    ev_db = _row(conn, "SELECT COUNT(*) FROM encoding_values")
    if ev_src != ev_db:
        issues.append(
            f"encoding_values: source={ev_src} vs db={ev_db} "
            f"(diff={ev_src - ev_db}). Silent-drop bug — see round-9 "
            "CSV QUOTE_NONE fix for precedent."
        )
    return issues


# ── L3 ──────────────────────────────────────────────────────────────

def _load_golden(path: Path) -> List[Dict[str, Any]]:
    """Load golden-seed YAML (YAML is optional; fall back to JSON).

    Returns [] only when the file is truly missing. A file that exists
    but parses to a non-list / all-comments structure raises — deep-
    check round-8 strict-review found: with the prior silent `or []`
    fallback, emptying or corrupting the file made L3 pass with 0
    checks and report ✅.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(text)
    except ImportError:
        parsed = json.loads(text)
    if parsed is None:
        raise ValueError(
            f"golden-seed file {path} is empty or all-comments — "
            "L3 would silently pass with 0 checks."
        )
    if not isinstance(parsed, list):
        raise ValueError(
            f"golden-seed file {path} parsed to {type(parsed).__name__}, "
            "expected list."
        )
    return parsed


# Minimum golden-seed entries expected (after round-8 expansion). If
# the list shrinks below this, someone deleted entries — fail loudly.
_GOLDEN_MIN_ENTRIES = 200

# Acceptable top-level keys per entry shape. Anything else is a typo
# (e.g., "field_idx" instead of "field_id") that previously made the
# entry silently skipped — now surfaces as a hard issue.
_GOLDEN_FIELD_KEYS = {"field_id", "title", "title_contains", "main_category"}
_GOLDEN_ICD10_KEYS = {"icd10", "title_contains"}


def check_golden_fields(
    conn: sqlite3.Connection, golden_path: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """For each golden entry, assert the field exists and its metadata
    matches expected properties."""
    issues: List[str] = []
    golden = _load_golden(golden_path)
    if golden_path.exists() and len(golden) < _GOLDEN_MIN_ENTRIES:
        issues.append(
            f"golden-seed count {len(golden)} below floor "
            f"{_GOLDEN_MIN_ENTRIES} — entries deleted. Re-add or "
            "bump _GOLDEN_MIN_ENTRIES intentionally."
        )
    checked = 0
    missing = 0
    mismatches = 0
    for entry in golden:
        # Reject entries with unrecognized keys — catches YAML typos
        # that would otherwise make the entry silently skipped.
        if not isinstance(entry, dict):
            issues.append(f"golden entry {entry!r} not a dict — check YAML syntax")
            mismatches += 1
            continue
        keys = set(entry.keys())
        if not (keys <= _GOLDEN_FIELD_KEYS or keys <= _GOLDEN_ICD10_KEYS):
            unknown = keys - (_GOLDEN_FIELD_KEYS | _GOLDEN_ICD10_KEYS)
            issues.append(
                f"golden entry has unknown key(s) {sorted(unknown)}: "
                f"{entry!r}. Valid keys: field_id/title/title_contains/"
                "main_category or icd10/title_contains."
            )
            mismatches += 1
            continue
        if "field_id" in entry:
            checked += 1
            field_id = int(entry["field_id"])
            cur = conn.execute(
                "SELECT title, main_category FROM fields WHERE field_id=?",
                (field_id,),
            )
            row = cur.fetchone()
            if row is None:
                issues.append(f"golden field {field_id} not found")
                missing += 1
                continue
            title, main_cat = row
            # Optional checks — only enforce fields the YAML declares.
            if "title_contains" in entry:
                needle = entry["title_contains"].lower()
                if needle not in (title or "").lower():
                    issues.append(
                        f"golden field {field_id}: title '{title}' does not contain "
                        f"'{entry['title_contains']}'"
                    )
                    mismatches += 1
            if "title" in entry and entry["title"] != title:
                issues.append(
                    f"golden field {field_id}: title mismatch "
                    f"(expected {entry['title']!r}, got {title!r})"
                )
                mismatches += 1
            if "main_category" in entry and int(entry["main_category"]) != main_cat:
                issues.append(
                    f"golden field {field_id}: main_category "
                    f"{main_cat} != expected {entry['main_category']}"
                )
                mismatches += 1
        elif "icd10" in entry:
            checked += 1
            code = entry["icd10"].replace(".", "")
            # encoding_values(encoding_id, code, meaning, ...). ICD-10
            # codes in UKB often carry a trailing hyphen / block code
            # (e.g., "E11", "E11-Block", "E11.2"); LIKE match captures
            # any entry whose stripped-dot code starts with ours.
            cur = conn.execute(
                "SELECT code, meaning FROM encoding_values "
                "WHERE encoding_id=19 AND REPLACE(code,'.','') LIKE ? "
                "ORDER BY length(code) LIMIT 1",
                (code + "%",),
            )
            row = cur.fetchone()
            if row is None:
                issues.append(f"golden ICD10 {entry['icd10']} not found")
                missing += 1
                continue
            if "title_contains" in entry:
                needle = entry["title_contains"].lower()
                if needle not in (row[1] or "").lower():
                    issues.append(
                        f"golden ICD10 {entry['icd10']}: meaning '{row[1]}' "
                        f"does not contain '{entry['title_contains']}'"
                    )
                    mismatches += 1
    return issues, {
        "total": len(golden), "checked": checked,
        "missing": missing, "mismatches": mismatches,
    }


# ── L3b: Disease-KB × codebook consistency ──────────────────────────
# A silent failure we had no protection against: disease-definition-
# knowledge-base.json lists `ukb_definition_fields` per disease. If
# UKB deprecates one of those field_ids, the KB keeps pointing at it,
# generate_field_list keeps emitting `p{fid}_i0` into the RAP .txt,
# RAP returns "column not found", the user's outcome label is built
# from partial data, and the model ships with silently-missing cases.
#
# Scan the KB once per build and fail fast if any claimed field_id
# doesn't exist in the codebook, or lives in an unexpected risk
# category. Scope: defensive, not prescriptive — warns on unusual
# placements (e.g. 'imaging' risk on a diabetes definition field)
# but errors only when the field is entirely missing.

_DISEASE_DEFINITION_ALLOWED_RISKS = {
    "baseline",          # labs, biometrics, visit self-report
    "outcome_derived",   # first-occurrence ICD, algo-defined outcomes
    "hospital_derived",  # inpatient ICD, OPCS, GP records
    "death_registry",    # date/cause of death (e.g. fatal MI)
    "online_followup",   # post-baseline self-report used as definition
    # Round-9 strict-review addition: for heart failure and some
    # stroke subtypes, imaging-derived metrics ARE the canonical
    # definition (HFrEF diagnosed at LVEF<40% via cardiac MRI /
    # echocardiography; territorial infarction via MRI). An imaging
    # field listed under ukb_definition_fields for these diseases
    # should not trigger an "unusual risk" warning — it's standard.
    "imaging",
}


def check_disease_kb_consistency(
    conn: sqlite3.Connection,
    kb_path: Path,
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Cross-check disease-definition-knowledge-base.json against DB.

    Returns (errors, warnings, summary). Errors = missing field_id in
    DB (hard fail). Warnings = field lives in a risk_category outside
    the allowed-for-definition set (soft — may be intentional).
    """
    errors: List[str] = []
    warnings: List[str] = []
    summary: Dict[str, Any] = {
        "diseases_checked": 0, "fields_checked": 0,
        "missing_fields": [], "unusual_risk_placements": [],
    }

    if not kb_path.exists():
        warnings.append(f"disease-KB not found at {kb_path} — skipped")
        return errors, warnings, summary

    try:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"disease-KB unreadable: {exc}")
        return errors, warnings, summary

    diseases = kb.get("diseases", kb)
    for disease_key, entry in diseases.items():
        if not isinstance(entry, dict):
            continue
        summary["diseases_checked"] += 1
        for raw_fid in (entry.get("ukb_definition_fields") or []):
            try:
                fid = int(raw_fid)
            except (TypeError, ValueError):
                errors.append(
                    f"disease '{disease_key}' ukb_definition_fields "
                    f"entry {raw_fid!r} is not an integer"
                )
                continue
            summary["fields_checked"] += 1
            row = conn.execute(
                "SELECT title, risk_category, private "
                "FROM fields WHERE field_id=?", (fid,),
            ).fetchone()
            if row is None:
                errors.append(
                    f"disease '{disease_key}': ukb_definition_fields "
                    f"entry {fid} not in codebook — UKB may have "
                    f"deprecated it. Remove from KB or migrate to its "
                    f"replacement."
                )
                summary["missing_fields"].append(
                    {"disease": disease_key, "field_id": fid}
                )
                continue
            title, risk, private = row[0], row[1], row[2]
            # (Note: UKB's `availability` column is NOT a deprecation
            # flag — 98% of fields including BMI and HbA1c carry
            # availability=0. Do not use it as a liveness signal.)
            if risk not in _DISEASE_DEFINITION_ALLOWED_RISKS:
                warnings.append(
                    f"disease '{disease_key}' field {fid} ({title!r}) "
                    f"has unusual risk_category={risk!r}"
                    + (f" (private=1 — UKB restricts access)" if private == 1 else "")
                    + f". Allowed for definition fields: "
                    f"{sorted(_DISEASE_DEFINITION_ALLOWED_RISKS)}."
                )
                summary["unusual_risk_placements"].append(
                    {"disease": disease_key, "field_id": fid,
                     "risk_category": risk, "private": bool(private)}
                )

    return errors, warnings, summary


# ── Orchestration ──────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--skip-l1", action="store_true",
                        help="Skip source-file manifest check")
    parser.add_argument("--skip-l3", action="store_true",
                        help="Skip golden-field assertions")
    parser.add_argument("--skip-disease-kb", action="store_true",
                        help="Skip disease-KB consistency check (L3b)")
    parser.add_argument("--disease-kb", type=Path,
                        default=REPO_ROOT / "references" / "methodology"
                                / "disease-definition-knowledge-base.json",
                        help="Path to disease-definition-knowledge-base.json")
    parser.add_argument("--report", type=Path, help="Write JSON report")
    parser.add_argument("--print-content-hashes", action="store_true",
                        help="Print the four content-facet hashes as a JSON "
                             "snippet you can paste into source_manifest.json "
                             "under 'content_hashes'. No other checks run.")
    parser.add_argument("--strict-content-hashes", action="store_true",
                        help="Treat content-hash drift as error (exit 2) "
                             "rather than warning. Only enforced when the "
                             "manifest already has a content_hashes block.")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: UKB SQLite not found at {args.db}", file=sys.stderr)
        return 2

    # Fast-path for --print-content-hashes: just emit the JSON snippet.
    if args.print_content_hashes:
        with sqlite3.connect(str(args.db)) as conn:
            hashes = compute_content_hashes(conn)
        print(json.dumps({"content_hashes": hashes}, indent=2))
        return 0

    all_issues: List[str] = []
    all_warnings: List[str] = []
    summary: Dict[str, Any] = {"layers": {}}

    # L1
    if not args.skip_l1:
        issues, l1_detail = check_source_manifest(UKB_DIR, args.manifest)
        summary["layers"]["l1_source_fidelity"] = {
            "issues": len(issues), "detail": l1_detail,
        }
        all_issues.extend(f"[L1] {i}" for i in issues)

    # L2
    with sqlite3.connect(str(args.db)) as conn:
        count_issues, count_detail = check_counts(conn)
        hard_issues = check_hard_invariants(conn)
        source_vs_db_issues = check_source_vs_db_row_counts(UKB_DIR, conn)
        enc_issues, enc_detail = check_source_encoding(UKB_DIR)
        ceiling_warnings = check_ceilings(conn)
        summary["layers"]["l2_structural"] = {
            "count_issues": len(count_issues),
            "hard_invariant_issues": len(hard_issues),
            "source_vs_db_issues": len(source_vs_db_issues),
            "source_encoding_issues": len(enc_issues),
            "source_encoding_detail": enc_detail,
            "ceiling_warnings": len(ceiling_warnings),
            "counts": count_detail,
        }
        all_issues.extend(f"[L2] {i}" for i in count_issues)
        all_issues.extend(f"[L2] {i}" for i in hard_issues)
        all_issues.extend(f"[L2-src-vs-db] {i}" for i in source_vs_db_issues)
        all_issues.extend(f"[L2-src-encoding] {i}" for i in enc_issues)
        all_warnings.extend(f"[L2] {w}" for w in ceiling_warnings)

        # L3
        if not args.skip_l3:
            golden_issues, golden_detail = check_golden_fields(conn, args.golden)
            summary["layers"]["l3_golden"] = {
                "issues": len(golden_issues), "detail": golden_detail,
            }
            all_issues.extend(f"[L3] {i}" for i in golden_issues)

        # L3b — disease-KB × codebook consistency
        if not args.skip_disease_kb:
            kb_errors, kb_warnings, kb_detail = check_disease_kb_consistency(
                conn, args.disease_kb,
            )
            summary["layers"]["l3b_disease_kb"] = {
                "errors": len(kb_errors),
                "warnings": len(kb_warnings),
                "detail": kb_detail,
            }
            all_issues.extend(f"[L3b] {e}" for e in kb_errors)
            all_warnings.extend(f"[L3b] {w}" for w in kb_warnings)

        # Content-facet hashes — informational + optional drift check
        content_hashes = compute_content_hashes(conn)
        drift_warnings, drift_detail = check_content_hash_drift(
            content_hashes, args.manifest,
        )
        summary["layers"]["content_hashes"] = {
            "computed": content_hashes,
            "pinned": drift_detail["pinned"],
            "drift": drift_warnings,
        }
        if drift_warnings:
            if args.strict_content_hashes:
                all_issues.extend(f"[content-hash] {w}" for w in drift_warnings)
            else:
                all_warnings.extend(f"[content-hash] {w}" for w in drift_warnings)

    # Report
    print("=" * 60)
    print("UKB codebook verification")
    print("=" * 60)
    if all_warnings:
        print(f"\n{len(all_warnings)} warning(s):")
        for w in all_warnings:
            print(f"  ⚠️  {w}")
    if all_issues:
        print(f"\n{len(all_issues)} issue(s):")
        for i in all_issues:
            print(f"  ❌ {i}")
    else:
        print("\n✅ All checks passed.")

    # Always surface the content-facet hashes so CI logs have a stable
    # audit trail even on green runs. Cheap to print (~60 chars).
    ch = summary.get("layers", {}).get("content_hashes", {}).get("computed", {})
    if ch:
        print("\nContent hashes (12-char prefix — see --print-content-hashes "
              "for full):")
        for key in ("source_titles", "classification", "encoding_values", "aliases"):
            if key in ch:
                print(f"  {key:<18} {ch[key][:12]}…")
    print("=" * 60)

    if args.report:
        out = {
            "status": "fail" if all_issues else "pass",
            "issues": all_issues,
            "warnings": all_warnings,
            "summary": summary,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(out, indent=2) + "\n")

    return 2 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
