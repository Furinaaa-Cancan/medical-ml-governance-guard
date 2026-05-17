# Security Policy

`ml-governance-guard` is a research framework for retrospective-cohort medical-ML governance. It does not process patient data at runtime — but its outputs (gate decisions, RAG retrievals, peer-review concern matching) directly influence clinical-ML publication and deployment decisions. We take security and integrity reports seriously.

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security reports.** Please use one of:

1. **GitHub Private Vulnerability Reporting** (preferred) — go to the [Security tab](https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/security) → "Report a vulnerability". This routes to maintainers privately.
2. **Email** — `cancansauce@163.com` with subject prefix `[mlgg-security]`. PGP key available on request.

We aim to:
- Acknowledge within **3 business days**
- Provide an initial assessment within **14 days**
- Publish a fix or mitigation advisory within **90 days** for HIGH/CRITICAL; **120 days** for MEDIUM
- Credit reporters in the resulting [Security Advisory](https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/security/advisories) unless anonymity is requested

## Scope — what we consider in-scope

### High priority

- **Knowledge-base integrity attacks**: anything that could cause the RAG (`scripts/rag/`) to retrieve concerns from a tampered or malicious `references/case-studies/peer-review-kb.json`. The runner verifies KB SHA256 against the bench artifact (`references/retrieval_eval/MLGG-Bench-v1.0/runner.sh`) — bypasses or false-pass conditions are HIGH severity.
- **Gate logic bypass**: the 33 fail-closed gates under `scripts/gates/` are the project's primary safety surface (e.g., `leakage_gate`, `clinical_metrics_gate`). A path that lets a violating manuscript pass without triggering the gate is HIGH severity.
- **LLM-generated content promoted to canonical KB without provenance**: per the `disease-KB` provenance policy, KB entries with `_provenance` containing `"LLM-DRAFT"` MUST NOT appear in `references/case-studies/peer-review-kb.json`. A code path that admits them is a publication-integrity defect (HIGH).
- **Prompt injection** in scenarios consumed by `scripts/rag/evals/run_eval.py` or in OOD WebFetched content that would alter retrieval behavior.
- **Secret exposure** — API keys, model keys, credentials in commits or scenario text.

### Medium priority

- **Reproducibility-fingerprint forgery**: the runner records `git_sha`, `kb_sha256`, `embedding_model`. Forging any of these to claim reproduced results.
- **Test-set leakage**: `SPLITS=test` is guarded by `ALLOW_TEST=1` in the runner. Bypass paths.
- **Eval metric manipulation**: feeding crafted scenarios that game `hit@5` / `cp_hit@5` against tag overlap rather than genuine retrieval relevance.

### Lower priority

- DoS via crafted-large scenarios (max-sized JSON inputs)
- CI workflow misconfiguration that reveals secrets via job logs

## Out-of-scope

- Issues in upstream dependencies — report to the dependency project (we track via Dependabot)
- Self-XSS or social-engineering scenarios that require the victim to run code they wrote
- Bugs requiring modifications to local config files (`scripts/rag/config.py` weight tweaks etc.) — these are user-controlled
- Performance issues that are not exploitable
- Best-practice nits that don't change a defended surface

## Supply-chain commitments

- **Dependabot alerts**: enabled on this repository (`Settings → Code security`).
- **Code scanning (CodeQL)**: enabled via `.github/workflows/codeql.yml`, runs on push to `main`, PRs, and weekly schedule.
- **Secret scanning**: enabled (GitHub native).
- **Branch protection on `main`**: per-commit CI required; recommended you don't merge red CI builds.
- **CODEOWNERS** on `references/` and `scripts/rag/` requires maintainer review.

## Known limitations and unfixed risks

We are transparent about open weaknesses (these are documented in `references/retrieval_eval/MLGG-Bench-v1.0.2/INDEPENDENT_REVIEW.md`):

- **`_provenance: "LLM-DRAFT-pending-clinical-review"` marker enforcement is partial** — `tests/test_kb_llm_draft_guard.py` blocks LLM-DRAFT entries from being committed to `peer-review-kb.json`, but a manual merge that strips the marker would not be detected. Mitigation: code review on every KB-touching PR.
- **CI environment race** on the README test-count drift check has produced sporadic red builds on `main` from concurrent sessions. Not a security defect; an integrity / process concern.

## Acknowledgments

This security policy was drafted 2026-05-17 alongside the v1.0.2 INDEPENDENT_REVIEW findings (R9 provenance lane). It is a living document — substantive updates are reflected in commit history.
