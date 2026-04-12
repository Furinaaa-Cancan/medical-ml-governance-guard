#!/usr/bin/env python3
"""
NHANES Codebook RAG — Retrieval-Augmented variable validation.

Loads Harvard CCB-HMS NHANES metadata (58K+ variables, 200K+ codebook entries)
and provides lookup/validation for any NHANES variable by code or friendly name.

Usage as library:
    from nhanes_codebook_lookup import NHANESCodebook
    cb = NHANESCodebook("references/nhanes_codebook")
    info = cb.lookup("DIQ172", cycle="2017-2018")
    issues = cb.validate_columns(df, target_col="y")

Usage as CLI:
    python3 scripts/tools/nhanes_codebook_lookup.py \
        --data examples/nhanes_diabetes.csv \
        --codebook-dir references/nhanes_codebook \
        --cycle 2017-2018 \
        --report /tmp/nhanes_rag_report.json
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Cycle → table suffix mapping ─────────────────────────
_CYCLE_SUFFIX = {
    "2017-2018": "_J",
    "2019-2020": "P_",  # P_ prefix, not suffix
    "2015-2016": "_I",
    "2013-2014": "_H",
    "2011-2012": "_G",
}


class NHANESCodebook:
    """In-memory index of NHANES variable metadata from Harvard CCB-HMS TSVs."""

    def __init__(self, codebook_dir: str, cycle: str = "2017-2018") -> None:
        self.codebook_dir = Path(codebook_dir)
        self.cycle = cycle
        self._variables: Dict[str, Dict[str, Any]] = {}
        self._codebooks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        vars_path = self.codebook_dir / "nhanes_variables.tsv"
        cb_path = self.codebook_dir / "nhanes_variables_codebooks.tsv"
        if not vars_path.exists() or not cb_path.exists():
            import warnings
            missing = [str(p) for p in [vars_path, cb_path] if not p.exists()]
            warnings.warn(
                f"NHANES codebook TSV files not found: {missing}. "
                f"RAG validation will be skipped. Download: "
                f"curl -sL -o {vars_path} "
                f'"https://raw.githubusercontent.com/ccb-hms/NHANES-metadata/master/metadata/nhanes_variables.tsv"',
                UserWarning,
                stacklevel=2,
            )
            return
        self._load_variables(vars_path)
        self._load_codebooks(cb_path)
        self._loaded = True

    def _match_cycle(self, table: str) -> bool:
        """Check if a table name belongs to the configured cycle."""
        suffix = _CYCLE_SUFFIX.get(self.cycle, "_J")
        if self.cycle == "2019-2020":
            return table.startswith("P_")
        return table.endswith(suffix)

    def _load_variables(self, path: Path) -> None:
        # Track variable order within each table (row order = questionnaire item order)
        self._table_var_order: Dict[str, List[str]] = defaultdict(list)
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                table = row.get("Table", "")
                if not self._match_cycle(table):
                    continue
                var = row["Variable"]
                if var not in self._variables:
                    self._variables[var] = {
                        "variable": var,
                        "table": table,
                        "sas_label": row.get("SASLabel", ""),
                        "english_text": row.get("EnglishText", ""),
                        "english_instructions": row.get("EnglishInstructions", ""),
                        "target_population": row.get("Target", ""),
                    }
                    self._table_var_order[table].append(var)

    def _load_codebooks(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                table = (row.get("Table") or "").strip('"')
                if not self._match_cycle(table):
                    continue
                var = (row.get("Variable") or "").strip('"')
                self._codebooks[var].append({
                    "value": (row.get("CodeOrValue") or "").strip('"'),
                    "description": (row.get("ValueDescription") or "").strip('"'),
                    "count": int((row.get("Count") or "0").strip('"') or 0),
                    "cumulative": int((row.get("Cumulative") or "0").strip('"') or 0),
                    "skip_to": (row.get("SkipToItem") or "").strip('"'),
                })

    @property
    def variable_count(self) -> int:
        self._ensure_loaded()
        return len(self._variables)

    def lookup(self, var_code: str) -> Optional[Dict[str, Any]]:
        """Look up a single variable by its NHANES code. Returns enriched info."""
        self._ensure_loaded()
        base = self._variables.get(var_code)
        if base is None:
            return None
        result = dict(base)
        cb_entries = self._codebooks.get(var_code, [])
        result["codebook"] = cb_entries

        # Derive skip patterns
        skip_map = {}
        for entry in cb_entries:
            if entry["skip_to"]:
                skip_map[entry["value"]] = entry["skip_to"]
        result["skip_pattern"] = skip_map if skip_map else None
        result["has_skip_pattern"] = bool(skip_map)

        # Derive missing rate
        total = 0
        missing = 0
        for entry in cb_entries:
            if entry["description"] == "Missing":
                missing = entry["count"]
            total = max(total, entry["cumulative"])
        result["missing_count"] = missing
        result["total_count"] = total
        result["missing_rate"] = round(missing / total, 3) if total > 0 else 0.0

        # Infer variable type from codebook values
        result["inferred_type"] = self._infer_type(cb_entries)

        return result

    def _infer_type(self, cb_entries: List[Dict[str, Any]]) -> str:
        """Infer variable type from codebook value descriptions."""
        descriptions = [e["description"] for e in cb_entries if e["description"] != "Missing"]
        values = [e["value"] for e in cb_entries if e["description"] != "Missing"]

        if any("Range of Values" in d for d in descriptions):
            return "continuous"
        if set(descriptions) - {"Missing"} <= {"Yes", "No", "Refused", "Don't know"}:
            return "binary"
        if len(descriptions) <= 2:
            return "binary"
        # Check if values are pure numeric codes
        non_special = [v for v in values if v not in (".", "7", "9", "77", "99", "777", "999")]
        if len(non_special) <= 10:
            return "categorical"
        return "continuous"

    def validate_columns(
        self,
        column_names: List[str],
        target_col: str = "y",
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate a list of column names against the NHANES codebook.

        Returns a list of issue dicts compatible with gate framework.
        """
        self._ensure_loaded()
        issues: List[Dict[str, Any]] = []

        for col in column_names:
            if col == target_col:
                continue

            # Try exact match first
            info = self.lookup(col)

            # Skip if already in manual registry (manual has priority)
            if manual_registry and col in manual_registry:
                continue

            if info is None:
                # Try reverse lookup from friendly name
                info = self._reverse_lookup(col)

            if info is None:
                continue

            var_code = info["variable"]

            # Check 1: Gated missingness
            # Source A: variable's own skip pattern + high missing
            # Source B: upstream gating chain (variable is skipped by another question)
            self._ensure_index()
            gating = self.resolve_gating_chain(var_code)
            is_upstream_gated = gating["is_gated"]

            if (info["has_skip_pattern"] or is_upstream_gated) and info["missing_rate"] > 0.10:
                issues.append({
                    "code": "CODEBOOK_GATED_MISSINGNESS",
                    "message": (
                        f"Column '{col}' maps to NHANES variable '{var_code}' "
                        f"({info['sas_label']}). "
                        f"{'Has own skip pattern: ' + str(info['skip_pattern']) + '. ' if info['has_skip_pattern'] else ''}"
                        f"{'Gated by upstream: ' + ', '.join(g['upstream_variable'] for g in gating['gated_by']) + '. ' if is_upstream_gated else ''}"
                        f"Missing rate: {info['missing_rate']:.0%}. "
                        f"NaN likely means 'question not asked' (gated), "
                        f"not 'value unknown'."
                    ),
                    "details": {
                        "column": col,
                        "var_code": var_code,
                        "sas_label": info["sas_label"],
                        "skip_pattern": info["skip_pattern"],
                        "upstream_gating": gating["gated_by"] if is_upstream_gated else None,
                        "missing_rate": info["missing_rate"],
                        "source": "nhanes_rag_auto",
                    },
                })

            # Check 2: Categorical variable type
            if info["inferred_type"] == "categorical":
                issues.append({
                    "code": "CODEBOOK_ENCODING_CHECK",
                    "message": (
                        f"Column '{col}' maps to NHANES '{var_code}' "
                        f"({info['sas_label']}), inferred as categorical. "
                        f"Verify encoding: if nominal, use one-hot; "
                        f"if ordinal, document the ordering rationale."
                    ),
                    "details": {
                        "column": col,
                        "var_code": var_code,
                        "inferred_type": "categorical",
                        "codebook_values": [
                            {"value": e["value"], "description": e["description"]}
                            for e in info["codebook"]
                            if e["description"] not in ("Missing", "Range of Values")
                        ][:10],
                        "source": "nhanes_rag_auto",
                    },
                })

        return issues

    def validate_columns_for_gate(
        self,
        column_names: List[str],
        target_col: str = "y",
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Alias for validate_columns — unified interface across all codebook types."""
        return self.validate_columns(column_names, target_col, manual_registry)

    # ── Task-aware validation (disease-KB × codebook) ────────

    def task_aware_validate(
        self,
        column_names: List[str],
        target_col: str,
        target_disease: str,
        disease_kb_path: str,
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate columns with disease-specific awareness.

        Loads disease-definition-knowledge-base.json, extracts:
        - definition_variables_to_exclude (abstract names)
        - lab_criteria (test names)
        - self_report_fields
        Then maps them to actual NHANES codes via hybrid search,
        and flags any that appear in the user's feature columns.
        """
        self._ensure_index()

        # Load disease KB
        kb_path = Path(disease_kb_path)
        if not kb_path.exists():
            return []
        try:
            with kb_path.open("r", encoding="utf-8") as fh:
                kb = json.load(fh)
        except Exception:
            return []

        diseases = kb.get("diseases", {})
        # Fuzzy match disease name
        disease_block = None
        target_lower = target_disease.lower().replace("_", " ").replace("-", " ")
        for dk, dv in diseases.items():
            dk_lower = dk.lower().replace("_", " ")
            name_lower = dv.get("name", "").lower()
            if target_lower in dk_lower or target_lower in name_lower or dk_lower in target_lower:
                disease_block = dv
                break
        if disease_block is None:
            return []

        # Collect all exclusion terms from the disease block
        exclude_terms: List[str] = list(disease_block.get("definition_variables_to_exclude", []))
        for lab in disease_block.get("lab_criteria", []):
            exclude_terms.append(lab.get("test", ""))
        exclude_terms.extend(disease_block.get("self_report_fields", []))
        exclude_terms = [t for t in exclude_terms if t]

        # Map abstract terms to NHANES codes via hybrid search
        flagged_codes: Dict[str, str] = {}  # nhanes_code → matched_term
        for term in exclude_terms:
            results = self.search(term, top_k=2, min_score=3.0)
            for r in results:
                if r["score"] >= 5.0:
                    flagged_codes[r["variable"]] = term

        # Also try alias-based reverse lookup
        for term in exclude_terms:
            info = self._reverse_lookup(term)
            if info:
                flagged_codes[info["variable"]] = term

        # Check which flagged codes appear in the user's columns
        issues: List[Dict[str, Any]] = []
        for col in column_names:
            if col == target_col:
                continue
            if manual_registry and col in manual_registry:
                continue

            # Resolve column → NHANES code
            matched_code = None
            if col in flagged_codes:
                matched_code = col
            else:
                info = self.lookup(col)
                if info and info["variable"] in flagged_codes:
                    matched_code = info["variable"]
                else:
                    rev = self._reverse_lookup(col)
                    if rev and rev["variable"] in flagged_codes:
                        matched_code = rev["variable"]

            if matched_code:
                var_info = self.lookup(matched_code)
                label = var_info["sas_label"] if var_info else matched_code
                term = flagged_codes[matched_code]
                issues.append({
                    "code": "CODEBOOK_DEFINITION_VARIABLE",
                    "message": (
                        f"Column '{col}' maps to NHANES '{matched_code}' ({label}), "
                        f"which is a definition/exclusion variable for "
                        f"'{target_disease}' (matched term: '{term}'). "
                        f"Using it as a predictor constitutes target leakage (MLGG-F01)."
                    ),
                    "details": {
                        "column": col,
                        "var_code": matched_code,
                        "sas_label": label,
                        "matched_term": term,
                        "target_disease": target_disease,
                        "source": "disease_kb_x_codebook_rag",
                    },
                })

        return issues

    # ── Hybrid retrieval ──────────────────────────────────────

    def _ensure_index(self) -> None:
        """Build BM25 and n-gram indexes for hybrid retrieval."""
        if hasattr(self, "_bm25_ready"):
            return
        self._ensure_loaded()

        # BM25 index: doc_id → token bag, plus IDF table
        self._doc_tokens: Dict[str, List[str]] = {}
        df_counter: Counter = Counter()  # document frequency
        for var_code, info in self._variables.items():
            tokens = self._tokenize(
                f"{info['sas_label']} {info.get('english_text', '')}"
            )
            self._doc_tokens[var_code] = tokens
            for t in set(tokens):
                df_counter[t] += 1

        n_docs = max(len(self._doc_tokens), 1)
        self._idf: Dict[str, float] = {
            t: math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            for t, df in df_counter.items()
        }

        # N-gram index: trigram → set of var_codes
        self._trigram_index: Dict[str, Set[str]] = defaultdict(set)
        for var_code, info in self._variables.items():
            label = info["sas_label"].lower()
            for tri in self._trigrams(label):
                self._trigram_index[tri].add(var_code)

        # Skip-chain graph: var → set of vars it gates (downstream)
        self._skip_graph: Dict[str, Set[str]] = defaultdict(set)
        self._gated_by: Dict[str, Set[str]] = defaultdict(set)
        for var_code in self._variables:
            cb_entries = self._codebooks.get(var_code, [])
            for entry in cb_entries:
                skip_to = entry.get("skip_to", "")
                if skip_to:
                    # var_code skips over variables between itself and skip_to
                    self._skip_graph[var_code].add(skip_to)

        # Build reverse: which variables are gated by which upstream questions.
        # A variable V is gated by U if U's skip pattern jumps PAST V.
        # Uses TSV row order (= questionnaire item order), NOT alphabetical.
        # This correctly handles DIQ010 skip→DIQ159 gating DIQ160-DIQ172.
        for upstream, skip_targets in self._skip_graph.items():
            up_info = self._variables.get(upstream)
            if not up_info:
                continue
            table = up_info["table"]
            vars_in_table = self._table_var_order.get(table, [])
            if upstream not in vars_in_table:
                continue
            up_idx = vars_in_table.index(upstream)
            for skip_target in skip_targets:
                # Find skip_target position — may be in the list or may be
                # a label that maps to a var further down
                if skip_target in vars_in_table:
                    skip_idx = vars_in_table.index(skip_target)
                else:
                    # skip_target not found in table — skip
                    continue
                # All variables between upstream and skip_target are gated
                for i in range(up_idx + 1, skip_idx):
                    gated_var = vars_in_table[i]
                    self._gated_by[gated_var].add(upstream)

        self._bm25_ready = True

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenize text for BM25. Lowercase, split on non-alpha, remove stopwords."""
        _STOP = {"the", "a", "an", "in", "of", "to", "for", "and", "or", "is",
                 "at", "by", "on", "as", "has", "had", "was", "been", "are",
                 "you", "your", "sp", "s", "he", "she", "his", "her", "have",
                 "do", "does", "did", "ever", "been", "told", "other"}
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [t for t in tokens if t not in _STOP and len(t) > 1]

    @staticmethod
    def _trigrams(text: str) -> List[str]:
        """Generate character trigrams from text."""
        s = f"__{text.lower()}__"
        return [s[i:i+3] for i in range(len(s) - 2)]

    def _bm25_score(self, query_tokens: List[str], doc_tokens: List[str],
                    k1: float = 1.5, b: float = 0.75) -> float:
        """BM25 score for a single document."""
        if not doc_tokens:
            return 0.0
        avg_dl = sum(len(t) for t in self._doc_tokens.values()) / max(len(self._doc_tokens), 1)
        dl = len(doc_tokens)
        tf_map = Counter(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            tf = tf_map.get(qt, 0)
            idf = self._idf.get(qt, 0.0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / avg_dl)
            score += idf * numerator / denominator
        return score

    def _trigram_similarity(self, query: str, candidate_label: str) -> float:
        """Jaccard similarity on character trigrams."""
        q_tri = set(self._trigrams(query))
        c_tri = set(self._trigrams(candidate_label))
        if not q_tri or not c_tri:
            return 0.0
        return len(q_tri & c_tri) / len(q_tri | c_tri)

    def search(self, query: str, top_k: int = 5,
               min_score: float = 2.0) -> List[Dict[str, Any]]:
        """Hybrid search: BM25 + trigram similarity.

        Returns top-k matches with combined scores.
        """
        self._ensure_index()
        query_tokens = self._tokenize(query)
        query_lower = query.lower().replace("_", " ")

        candidates: Dict[str, float] = {}

        # BM25 scoring
        for var_code, doc_tokens in self._doc_tokens.items():
            score = self._bm25_score(query_tokens, doc_tokens)
            if score > 0:
                candidates[var_code] = score

        # Trigram boost (for misspellings, partial matches)
        query_trigrams = set(self._trigrams(query_lower))
        trigram_candidates: Counter = Counter()
        for tri in query_trigrams:
            for var_code in self._trigram_index.get(tri, set()):
                trigram_candidates[var_code] += 1

        for var_code, tri_hits in trigram_candidates.items():
            label = self._variables[var_code]["sas_label"].lower()
            sim = self._trigram_similarity(query_lower, label)
            # Combine: BM25 base + trigram boost (weighted 0.5)
            candidates[var_code] = candidates.get(var_code, 0) + sim * 3.0

        # Sort by score, return top-k
        ranked = sorted(candidates.items(), key=lambda x: -x[1])
        results = []
        for var_code, score in ranked[:top_k]:
            if score < min_score:
                break
            info = self._variables[var_code]
            results.append({
                "variable": var_code,
                "sas_label": info["sas_label"],
                "score": round(score, 2),
                "table": info["table"],
            })
        return results

    def resolve_gating_chain(self, var_code: str) -> Dict[str, Any]:
        """Resolve the upstream gating chain for a variable.

        Returns: which upstream questions gate this variable via skip patterns.
        """
        self._ensure_index()
        upstream = self._gated_by.get(var_code, set())
        if not upstream:
            return {"variable": var_code, "gated_by": [], "is_gated": False}
        chain = []
        for up_var in sorted(upstream):
            up_info = self._variables.get(up_var, {})
            skip_targets = self._skip_graph.get(up_var, set())
            chain.append({
                "upstream_variable": up_var,
                "upstream_label": up_info.get("sas_label", ""),
                "skip_targets": sorted(skip_targets),
            })
        return {"variable": var_code, "gated_by": chain, "is_gated": True}

    def _reverse_lookup(self, friendly_name: str) -> Optional[Dict[str, Any]]:
        """Hybrid reverse lookup: alias table → exact label → BM25+trigram.

        Returns the best matching variable if confidence is high enough.
        """
        self._ensure_index()
        fn_lower = friendly_name.lower().replace("_", " ")

        # Tier 0: Known alias table (common friendly names from download scripts)
        _ALIAS_TABLE = {
            "age": "RIDAGEYR", "gender": "RIAGENDR", "sex": "RIAGENDR",
            "bmi": "BMXBMI", "body mass index": "BMXBMI",
            "waist circumference": "BMXWAIST",
            "hba1c": "LBXGH", "glycohemoglobin": "LBXGH", "a1c": "LBXGH",
            "fasting glucose": "LBXGLU", "glucose": "LBXGLU",
            "total cholesterol": "LBXTC", "cholesterol": "LBXTC",
            "hdl": "LBDHDD", "hdl cholesterol": "LBDHDD",
            "triglycerides": "LBXTR",
            "creatinine": "LBXSCR",
            "race ethnicity": "RIDRETH3", "race": "RIDRETH3",
            "ever smoked": "SMQ020", "smoking": "SMQ020",
            "bp medication": "BPQ050A",
            "hypertension diagnosed": "BPQ020", "high blood pressure": "BPQ020",
            "coronary heart disease": "MCQ160C", "chd": "MCQ160C",
            "stroke": "MCQ160F",
            "family history diabetes": "MCQ300C",
            "doctor told diabetes": "DIQ010", "diabetes diagnosis": "DIQ010",
            "prediabetes": "DIQ160",
            "depression": "DPQ010",
            "alcohol": "ALQ130",
            "income": "INDFMIN2", "education": "DMDEDUC2",
            "marital status": "DMDMARTL",
            "sbp mean": "BPXOSY2", "dbp mean": "BPXODI2",
            "systolic": "BPXOSY2", "diastolic": "BPXODI2",
        }
        alias_code = _ALIAS_TABLE.get(fn_lower)
        if alias_code and alias_code in self._variables:
            return self.lookup(alias_code)

        # Tier 1: Exact SAS label match
        for var_code, info in self._variables.items():
            if fn_lower == info["sas_label"].lower():
                return self.lookup(var_code)

        # Tier 2: Hybrid search (BM25 + trigram)
        results = self.search(friendly_name, top_k=3, min_score=5.0)
        if not results:
            return None

        best = results[0]
        # Require strong confidence AND clear separation from runner-up
        if best["score"] < 8.0:
            return None
        if len(results) >= 2 and results[1]["score"] > best["score"] * 0.7:
            return None

        return self.lookup(best["variable"])

    def summarize(self) -> Dict[str, Any]:
        """Return summary statistics about the loaded codebook."""
        self._ensure_loaded()
        skip_count = sum(1 for v in self._variables if self._codebooks.get(v) and
                         any(e.get("skip_to") for e in self._codebooks[v]))
        return {
            "cycle": self.cycle,
            "total_variables": len(self._variables),
            "with_codebook_entries": len(self._codebooks),
            "with_skip_patterns": skip_count,
            "loaded": self._loaded,
        }


# ═══════════════════════════════════════════════════════════════
# RegistryCodebook — lightweight validation from JSON registry only
# Works for ANY dataset (BRFSS, MIMIC, etc.) without TSV files.
# ═══════════════════════════════════════════════════════════════


class RegistryCodebook:
    """Validate columns against dataset-codebook-registry.json entries.

    Unlike NHANESCodebook (which loads 58K Harvard TSV variables with BM25
    and skip-chain), this class works purely from the curated registry JSON.
    Suitable for datasets without a Harvard-style metadata source.

    Usage:
        cb = RegistryCodebook("references/dataset-codebook-registry.json", "brfss_2022")
        issues = cb.validate_columns(["age", "bmi", "stroke", "y"], target_col="y")
    """

    def __init__(self, registry_path: str, dataset_key: str) -> None:
        self.registry_path = Path(registry_path)
        self.dataset_key = dataset_key
        self._variables: Dict[str, Dict[str, Any]] = {}
        self._friendly_map: Dict[str, str] = {}  # friendly_name → var_code
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            return
        try:
            with self.registry_path.open("r", encoding="utf-8") as fh:
                reg = json.load(fh)
        except Exception:
            return
        ds = reg.get("datasets", {}).get(self.dataset_key, {})
        self._variables = ds.get("variables", {})
        # Build reverse friendly-name map
        for var_code, info in self._variables.items():
            for friendly in info.get("friendly_names", []):
                self._friendly_map[friendly.lower()] = var_code
        self._loaded = True

    @property
    def variable_count(self) -> int:
        self._ensure_loaded()
        return len(self._variables)

    def lookup(self, var_code: str) -> Optional[Dict[str, Any]]:
        """Look up a variable by its raw code."""
        self._ensure_loaded()
        info = self._variables.get(var_code)
        if info is None:
            # Try friendly name reverse lookup
            mapped = self._friendly_map.get(var_code.lower())
            if mapped:
                info = self._variables.get(mapped)
                if info:
                    info = dict(info)
                    info["variable"] = mapped
                    return info
            return None
        result = dict(info)
        result["variable"] = var_code
        return result

    def validate_columns(
        self,
        column_names: List[str],
        target_col: str = "y",
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate columns against registry entries."""
        self._ensure_loaded()
        issues: List[Dict[str, Any]] = []

        for col in column_names:
            if col == target_col:
                continue
            if manual_registry and col in manual_registry:
                continue

            info = self.lookup(col)
            if info is None:
                continue

            var_code = info.get("variable", col)

            # Check 1: encoding rule
            if info.get("encoding_rule") == "must_onehot" or info.get("type") == "nominal_categorical":
                issues.append({
                    "code": "CODEBOOK_ENCODING_CHECK",
                    "message": (
                        f"Column '{col}' maps to '{var_code}' ({info.get('label', '')}), "
                        f"type={info.get('type')}. Verify OneHot encoding for nominal variables."
                    ),
                    "details": {"column": col, "var_code": var_code,
                                "type": info.get("type"), "source": "registry"},
                })

            # Check 2: must_exclude_if_target
            if info.get("must_exclude_if_target"):
                targets = info.get("definition_variable_for", []) + info.get("target_adjacent_for", [])
                issues.append({
                    "code": "CODEBOOK_VARIABLE_MISLABEL",
                    "message": (
                        f"Column '{col}' ({info.get('label', '')}) is a definition/target-adjacent "
                        f"variable for {targets}. Must be excluded from features."
                    ),
                    "details": {"column": col, "var_code": var_code,
                                "targets": targets, "source": "registry"},
                })

            # Check 3: reverse causation
            if info.get("reverse_causation_risk"):
                issues.append({
                    "code": "CODEBOOK_REVERSE_CAUSATION",
                    "message": (
                        f"Column '{col}' ({info.get('label', '')}) has reverse causation risk "
                        f"for {info['reverse_causation_risk']}."
                    ),
                    "details": {"column": col, "var_code": var_code,
                                "targets": info["reverse_causation_risk"], "source": "registry"},
                })

            # Check 4: top-coding
            top_val = info.get("top_coded")
            if top_val is not None:
                issues.append({
                    "code": "CODEBOOK_TOP_CODED",
                    "message": (
                        f"Column '{col}' is top-coded at {top_val}."
                    ),
                    "details": {"column": col, "ceiling": top_val, "source": "registry"},
                })

        return issues

    def validate_columns_for_gate(
        self,
        column_names: List[str],
        target_col: str = "y",
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Alias for validate_columns — unified interface across all codebook types."""
        return self.validate_columns(column_names, target_col, manual_registry)

    def task_aware_validate(
        self,
        column_names: List[str],
        target_col: str,
        target_disease: str,
        disease_kb_path: str,
        manual_registry: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Cross-reference disease-KB with registry variables."""
        # Load disease KB
        kb_path = Path(disease_kb_path)
        if not kb_path.exists():
            return []
        try:
            with kb_path.open("r", encoding="utf-8") as fh:
                kb = json.load(fh)
        except Exception:
            return []

        diseases = kb.get("diseases", {})
        disease_block = None
        target_lower = target_disease.lower().replace("_", " ")
        for dk, dv in diseases.items():
            if target_lower in dk.lower().replace("_", " ") or target_lower in dv.get("name", "").lower():
                disease_block = dv
                break
        if disease_block is None:
            return []

        # Collect exclusion terms
        exclude_terms = list(disease_block.get("definition_variables_to_exclude", []))
        for lab in disease_block.get("lab_criteria", []):
            exclude_terms.append(lab.get("test", ""))
        exclude_terms.extend(disease_block.get("self_report_fields", []))

        # Map to registry variables
        self._ensure_loaded()
        flagged: Dict[str, str] = {}
        for term in exclude_terms:
            if not term:
                continue
            info = self.lookup(term)
            if info:
                flagged[info.get("variable", term)] = term
            # Also check friendly names
            term_lower = term.lower().replace("_", " ")
            for var_code, var_info in self._variables.items():
                label_lower = var_info.get("label", "").lower()
                if term_lower in label_lower or label_lower in term_lower:
                    flagged[var_code] = term

        # Check columns
        issues: List[Dict[str, Any]] = []
        for col in column_names:
            if col == target_col:
                continue
            if manual_registry and col in manual_registry:
                continue
            info = self.lookup(col)
            matched_code = None
            if info and info.get("variable") in flagged:
                matched_code = info["variable"]
            elif col in flagged:
                matched_code = col
            if matched_code:
                issues.append({
                    "code": "CODEBOOK_DEFINITION_VARIABLE",
                    "message": (
                        f"Column '{col}' maps to '{matched_code}' which is a "
                        f"definition variable for '{target_disease}'."
                    ),
                    "details": {"column": col, "var_code": matched_code,
                                "target_disease": target_disease, "source": "registry_disease_kb"},
                })
        return issues

    def summarize(self) -> Dict[str, Any]:
        self._ensure_loaded()
        return {
            "dataset": self.dataset_key,
            "total_variables": len(self._variables),
            "loaded": self._loaded,
        }


def get_codebook(
    survey_source: str,
    registry_path: str = "references/dataset-codebook-registry.json",
    nhanes_codebook_dir: str = "references/nhanes_codebook",
    ukb_codebook_db: str = "references/ukb_codebook/ukb_codebook.sqlite",
) -> Optional["RegistryCodebook"]:
    """Factory: return the appropriate codebook for a dataset.

    Returns NHANESCodebook for NHANES (with full BM25 + skip-chain),
    UKBCodebook for UK Biobank (with instance-MNAR + temporal leakage),
    RegistryCodebook for BRFSS/MIMIC/others (registry-only validation).
    """
    _DS_KEY_MAP = {
        "nhanes": "nhanes_2017_2020",
        "brfss": "brfss_2022",
        "nhis": "nhis_2022",
        "mimic": "mimic_iv",
        "ukb": "ukb",
        "ukbiobank": "ukb",
    }
    source_lower = survey_source.lower()
    dataset_key = _DS_KEY_MAP.get(source_lower, "")
    if not dataset_key:
        return None

    if source_lower == "nhanes":
        nhanes_dir = Path(nhanes_codebook_dir)
        if (nhanes_dir / "nhanes_variables.tsv").exists():
            return NHANESCodebook(str(nhanes_dir), cycle="2017-2018")
        # Fallback to registry if TSV not available

    if source_lower in ("ukb", "ukbiobank", "biobank"):
        ukb_db = Path(ukb_codebook_db)
        if ukb_db.exists():
            try:
                from ukb_codebook_lookup import UKBCodebook
                return UKBCodebook(ukb_db)
            except ImportError:
                pass
        return None

    return RegistryCodebook(registry_path, dataset_key)


# ── CLI ──────────────────────────────────────────────────

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="NHANES Codebook RAG lookup.")
    parser.add_argument("--data", help="Path to CSV — validate all columns.")
    parser.add_argument("--var", help="Look up a single variable by code.")
    parser.add_argument("--codebook-dir", default="references/nhanes_codebook",
                        help="Path to directory containing Harvard TSV files.")
    parser.add_argument("--cycle", default="2017-2018", help="NHANES cycle.")
    parser.add_argument("--report", help="Write JSON report to this path.")
    parser.add_argument("--registry", default="",
                        help="Path to manual codebook registry (for priority lookup).")
    args = parser.parse_args()

    cb = NHANESCodebook(args.codebook_dir, cycle=args.cycle)

    if not cb._loaded and not (Path(args.codebook_dir) / "nhanes_variables.tsv").exists():
        print(f"[ERROR] Codebook TSV files not found in {args.codebook_dir}.", file=sys.stderr)
        print("Run: curl -sL -o references/nhanes_codebook/nhanes_variables.tsv "
              '"https://raw.githubusercontent.com/ccb-hms/NHANES-metadata/master/metadata/nhanes_variables.tsv"',
              file=sys.stderr)
        return 1

    # Single variable lookup
    if args.var:
        info = cb.lookup(args.var)
        if info is None:
            print(f"Variable '{args.var}' not found in {args.cycle} cycle.")
            return 1
        print(json.dumps(info, indent=2, default=str))
        return 0

    # CSV column validation
    if args.data:
        import pandas as pd
        df = pd.read_csv(args.data, nrows=0)
        columns = list(df.columns)

        manual_reg = None
        if args.registry:
            reg_path = Path(args.registry)
            if reg_path.exists():
                with reg_path.open(encoding="utf-8") as f:
                    reg = json.load(f)
                ds = reg.get("datasets", {}).get("nhanes_2017_2020", {})
                manual_reg = ds.get("variables", {})

        issues = cb.validate_columns(columns, manual_registry=manual_reg)

        summary = cb.summarize()
        summary["csv"] = str(args.data)
        summary["columns_checked"] = len(columns)
        summary["issues_found"] = len(issues)

        result = {"summary": summary, "issues": issues}

        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"Report written to {args.report}")

        # Print summary
        print(f"NHANES Codebook RAG ({args.cycle}): {summary['total_variables']} variables loaded")
        print(f"Checked {len(columns)} columns → {len(issues)} issues found")
        for issue in issues:
            print(f"  [{issue['code']}] {issue['message'][:120]}...")

        return 0

    # Default: print codebook summary
    summary = cb.summarize()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
