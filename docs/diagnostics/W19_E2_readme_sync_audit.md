# W19-E2 README CN/EN Sync Audit

**Date**: 2026-05-17 · **Auditor**: Wave 19 strict-review (E2) · **Mode**: READ-ONLY
**Inputs**: `README.md` (1922 lines, CN) · `README_EN.md` (1581 lines, EN)
**Design context (W12-A2)**: EN is intentionally shorter and link-redirects to `docs/reference/*.md`. Structural divergence is OK; **semantic / numeric drift is not**.

---

## 1. Section overlap

CN has **24** `## ` sections, EN has **20** `## ` sections.

| CN section | EN equivalent | Status |
|---|---|---|
| MLGG vs Claude Skill — 架构边界 | MLGG vs Claude Skill — Architecture Boundary | OK |
| 目录 | Table of Contents | OK |
| 为什么需要 MLGG | Why MLGG | OK |
| 审稿级审查机制 | Reviewer-Grade Review Mechanism | OK |
| 系统能力总览 | System Overview | OK |
| 快速开始 | Quick Start | OK |
| 9 阶段工作流 | 9-Phase Workflow | OK |
| 33 道安全门控 | 33 Safety Gates | OK |
| 12 维量化评分 | 12-Dimension Scoring | OK |
| 33 条方法论规则 | 33 Methodology Rules | OK |
| 23 个模型族 | 23 Model Families | OK (EN is just a link) |
| 16 个医学数据集 | 16 Medical Datasets | OK (EN is just a link) |
| 28 条静态分析规则 | 28 Static Analysis Rules | OK |
| 21 项分析工具 | 21 Analysis Tools | OK |
| NHANES Codebook RAG 系统 | **MISSING in EN** | DRIFT |
| 安全加固层 | Security Hardening Layer | OK |
| 基准测试结果 | **MISSING in EN** | DRIFT |
| 项目结构 | Project Structure | OK |
| 安装指南 | Installation Guide | OK |
| 命令参考 | Command Reference | OK |
| 文献基础 | Literature Foundation | OK |
| Claude Code 集成 | Claude Code Integration | OK |
| CI/CD | CI/CD | OK |
| 文档地图 | Documentation Map | OK (content drift, see §3) |
| 许可证与引用 | License & Citation | OK |

**EN-only**: none. **CN-only**: `NHANES Codebook RAG 系统`, `基准测试结果`. Neither has an EN equivalent nor a `docs/reference/*` link in EN.

---

## 2. Number / fact drift (badges + straplines)

| Claim | CN value | EN value | Ground truth | Verdict |
|---|---|---|---|---|
| tests badge | 4712 passed | 4712 passed | (assumed match) | OK |
| gates badge | 33 fail-closed | 33 fail-closed | 33 (registry) | OK |
| **datasets badge** | **16 medical** | **14 medical** | 16 CSVs in `examples/` | **RED — EN stale** |
| **code badge** | **147K lines** | **145K lines** | n/a | **YELLOW — out of sync** |
| **lint-rules badge** | **28 (R001-R028)** | **(no badge)** | 28 | **YELLOW — EN missing badge** |
| Strapline trailing item | "28 条静态分析规则" | "21 Analysis Tools" | both true | **YELLOW — different items emphasised** |
| KB curated | 154 抽 + 181 待抽 (=335) | 154 curated + 181 pending (=335) | matches `peer-review-kb.json` | OK |
| Datasets row count | "630K+ 行" | "630K+ rows" | match | OK |
| SKILL.md size | 290 行 | 290 lines | match | OK |
| Disease KB pending | 11/11 pending (line 1572) | 11 pending (line 62) | match | OK |
| `WEIGHT_DENSE` historical | 0.5 (clearly labelled "旧"/"old") | 0.5 (clearly labelled "old") | demoted to 0.10 in W13-P0; both READMEs document this | OK (historical refs are correct) |
| `WEIGHT_DENSE` current | 0.10 (W13-P0) | 0.10 (W13-P0) | matches `tests/test_rag_config.py` invariant | OK |

**Top RED**: EN datasets badge says `14 medical` but CN and `examples/` say 16. This is the exact failure mode `check_readme_stats.py` was built to catch — yet it shipped.

---

## 3. Documentation map drift

Rows present in CN doc map (lines 1893-1911) but **missing in EN doc map** (lines 1525-1541):

1. `references/methodology/DISEASE_KB_REVIEW.md` — clinician review checklist (audience: 临床审稿人)
2. `agents/README.md` — extractor / reviewer agent split (audience: API agent users)
3. `references/attestation/README.md` — trusted_signers + execution attestation (audience: security/compliance)
4. Trailing pre-commit footnote: "数字漂移由 `check_readme_stats.py` 和 `check_docs_consistency.py` 守门"

Rows present in **both** but with content mismatch:
- CN: `docs/adr/` — "ADR 0001: `_mmr_breakdown` consumer"
- EN: `docs/adr/` — "ADR 0001: `_mmr_breakdown` SHIP decision"
- Reality: 4 ADRs exist (0001-0004); both READMEs only mention 0001. ADRs 0002 (race-proof commit), 0003 (unused analysis tools wiring), 0004 (worktrees default) are not listed in either map.

**New docs from W15-W18 absent from both maps**: 19 audit files under `docs/diagnostics/W1[5-8]_*.md` (e.g. `W15_A1_exit_code_audit.md`, `W17_C1_kb_integrity_audit.md`, `W18_D3_mmr_effect_audit.md`). Acceptable to skip (they are wave-internal diagnostics, not user-facing), but no roll-up index exists.

---

## 4. Stale references / dead links

- **No `DENSE=0.5` claim presented as current** in either README — all `0.5` mentions are explicitly labelled "old / 旧" with the W13-P0 demotion to 0.10 documented immediately after. CLEAN.
- All `docs/reference/*.md` links resolve (ANALYSIS_TOOLS, DATASETS, GATES, LINT_RULES, MODEL_FAMILIES). CLEAN.
- All `docs/adr/0001_*.md` links resolve. CLEAN.
- All `docs/*.md` links in both maps resolve. CLEAN.
- No deprecated baseline-file mentions found.

---

## 5. Wave update parity

- W11-I1 ablation finding: both READMEs reflect it (CN line 224, EN line 244).
- W13-P0 dense-weight demote: both READMEs document the fix (CN lines 244-254, EN lines 218-228).
- W14 ADRs (0002 race-proof, 0003 analysis-tools, 0004 worktrees): **neither README mentions them**.
- W15-W18 audits: not surfaced in either README (acceptable for internal audit docs, but worth a `## Recent Audits` pointer).

---

## 6. Verdict: **YELLOW**

One RED-tier numeric drift (EN datasets badge `14` vs CN `16` and reality `16`); several YELLOW-tier badge / doc-map gaps. No false-current technical claims, no dead links, no deprecated-file mentions. Pre-commit `check_readme_stats.py` exists but evidently does not cover the datasets badge regex — or was bypassed.

---

## 7. Wave-N+ fix candidates (smallest first)

1. **One-line badge fix (5 min)**: change EN line 16 from `datasets-14%20medical` to `datasets-16%20medical`.
2. **Strapline parity (10 min)**: EN line 31 ends with "21 Analysis Tools" while CN ends with "28 条静态分析规则" — pick one canonical order, mirror in both.
3. **EN lint-rules badge (5 min)**: add the `lint%20rules-28%20(R001--R028)-orange` badge to EN.
4. **EN code badge (5 min)**: align EN `145K` with CN `147K` (or recompute and align both to live LOC).
5. **EN doc map +3 rows (10 min)**: add `references/methodology/DISEASE_KB_REVIEW.md`, `agents/README.md`, `references/attestation/README.md` to EN map.
6. **ADR row update (5 min)**: change both maps' `docs/adr/` description from "ADR 0001 only" to "ADR 0001-0004"; reconcile the "consumer" vs "SHIP decision" wording.
7. **check_readme_stats.py coverage gap (30 min)**: extend the script to assert datasets-badge / code-badge / lint-rules-badge parity. The whole point of this audit was already supposed to be automated.
8. **Optional**: add EN `## NHANES Codebook RAG System` and `## Benchmark Results` sections, even as 1-paragraph link stubs, to close the structural gap.

