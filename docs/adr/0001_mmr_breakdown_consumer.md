# ADR 0001 — `_mmr_breakdown` consumer: SHIP via `mlgg rag --explain`

- Status: Accepted
- Date: 2026-05-17
- Author: W11-I2
- Related: W9-B2 (introduction, d1f5467), W10-R1 (dormancy finding), W11-F3 (passthrough invariant, in-flight)

## 1. Context

`_mmr_breakdown` is a per-rank audit dict attached to every MMR-reranked
result by `scripts/rag/retrieval/hybrid.py::_mmr_rerank`. It records four
fields per pick:

```
{
  "relevance":    float,   # the candidate's _final_score at pick time
  "max_sim":      float,   # the max similarity to any already-selected
  "blocker_id":   str|None,  # which selected candidate produced max_sim
  "blocker_reason": "cosine" | "same_paper" | "none"
}
```

### W9-B2 motivation

W9-B2 (commit d1f5467) added the field as the missing "why was this
ranked here?" signal for the W5 deep audit track. MMR re-ranking is the
one stage in the hybrid pipeline that can demote a candidate purely on
diversity grounds; without the breakdown, an operator who sees a
surprising rank order cannot tell whether the demotion was cosine
near-duplication, same-paper penalty, or simply lower `_final_score`.

### W10-R1 finding (dormant)

W10-R1 confirmed that as of 2026-05-17 the field is **write-only**: the
only readers in the repository are the unit tests in
`tests/test_rag_corroboration.py::TestMMRBreakdown` that assert on its
shape and contents. No CLI, no JSON contract, no gate integration, no
audit tool reads it. The field is paid for (one dict allocation per
picked candidate, roughly 4 small fields × top_k) on every query and
yields zero user-visible value at HEAD.

### B2's self-flagged risk

The W9-B2 commit message and its own follow-up notes flagged exactly
this risk: "the breakdown is a contract; it needs a consumer or it is
just memory pressure with extra steps". Two waves later the consumer
has not materialised, and the field's presence in the public dict
schema also makes it harder to evolve (every change risks breaking
test-only invariants without any real user signal).

### W11-F3 passthrough invariant (sibling, in-flight)

Sibling session W11-F3 is tightening the contract so that
`blocker_reason != "none" ⇒ blocker_id is a non-empty string`, and
extending the passthrough branch (`lam >= 1.0` or single-candidate
input) to emit the same `_mmr_score` / `_mmr_breakdown` schema as the
main branch. That work has standalone value (it removes a class of
downstream null-deref / schema-divergence bugs) and is independent of
the SHIP/CUT decision here.

## 2. Options

### Option A — SHIP

Wire `_mmr_breakdown` into the existing `mlgg rag` CLI via a new
`--explain` flag that prints the per-rank breakdown to **stderr** after
the normal results (table or JSON) are printed to stdout.

| Dimension | Estimate |
|---|---|
| Effort | ~25 LOC in `scripts/rag/query.py`; 1 new flag wired through `main()`; 1 helper `_render_explain(results)` formatter. |
| Files touched | `scripts/rag/query.py` + 1 new integration test file or addition to `tests/test_mlgg_rag_subcommand.py`. |
| Maintenance cost | Small. The breakdown schema is now part of a stable user-facing contract (`--explain` output), which actually *reduces* refactor risk: any future change to the field becomes a user-visible diff with a regression test. |
| User value | Direct. The concrete user flow — "why is concern X at rank 3?" — is answered by one extra flag. Same flow as `git log --decorate` or `pytest -vv`: opt-in verbose diagnostic, off by default, free when off. |
| Risk if wrong | Low. Output goes to stderr so it never pollutes the JSON contract on stdout. If the format proves unhelpful we can iterate without breaking callers. |

### Option B — CUT

Remove all `_mmr_breakdown` writes from `_mmr_rerank` (top-1 init,
per-pick best_breakdown tracking, and the chosen attachment). Keep
W11-F3's `blocker_id` non-None invariant work as dead-letter compatible
in a smaller form, OR drop it entirely with F3's tracking comment.

| Dimension | Estimate |
|---|---|
| Effort | ~25 LOC removed in `hybrid.py` (top-1 init + best_breakdown tracking + chosen attachment); 3 tests removed from `test_rag_corroboration.py`. |
| Files touched | `scripts/rag/retrieval/hybrid.py`, `tests/test_rag_corroboration.py`. |
| Maintenance cost | Small one-shot savings. The dict allocation per pick is genuinely cheap (~µs); removing it does not materially change steady-state latency. |
| User value | Zero now, zero later — by definition since we are deleting the field. |
| Risk if wrong | Medium. The field captures decision provenance that is *expensive to reconstruct after the fact* (it requires re-running MMR with the same candidate ordering and the same numpy state). If a future debugging session needs it, restoring requires re-implementing the tracking from scratch. |

## 3. Decision

**SHIP via `mlgg rag --explain`.**

Justification: a concrete user flow exists today — "I ran `mlgg rag` on
a real failure description, the rank order surprises me, why is concern
X at rank 3 and concern Y at rank 2?" — and `_mmr_breakdown` is *the*
signal that answers it. Reconstructing the same answer without the
breakdown requires re-running MMR with the same candidate ordering and
inspecting intermediate scores in a debugger; that is exactly the kind
of diagnostic that a one-line CLI flag should replace. The wire-up is
small (~25 LOC), the field cost is paid anyway, the output goes to
stderr so the stdout JSON contract is unaffected, and stabilising the
breakdown as a user-visible diagnostic actually lowers long-term
maintenance risk (any future schema change now requires updating a
documented `--explain` regression test, not just an internal-looking
unit test). W11-F3's invariant work (passthrough schema parity +
non-None `blocker_id`) lands cleanly on top and makes the `--explain`
output uniform across all retrieval branches.

## 4. Implementation summary

- `scripts/rag/query.py`:
  - Add `--explain` flag (default `False`) to `_build_parser`.
  - Add `_render_explain(results) -> str` formatter that emits one
    line per pick: `rank=N concern_id=... relevance=0.83 max_sim=0.71
    blocker_id=... blocker_reason=cosine`.
  - In `main()`, after stdout output, if `args.explain` is set, write
    the explain block to `sys.stderr` (so the JSON contract on stdout
    stays clean and tools can opt out by ignoring stderr).
- `tests/test_mlgg_rag_subcommand.py`:
  - Add `test_mlgg_rag_explain_emits_breakdown_to_stderr` —
    subprocess invokes `mlgg rag "calibration" --explain --top-k 3`,
    asserts stdout still contains the table, and stderr contains
    `blocker_reason` + at least one of `cosine|same_paper|none`.

## 5. Out of scope

- Adding the breakdown into the JSON output schema (would be a
  breaking change to existing JSON consumers; defer until a clear
  caller emerges).
- Surfacing the breakdown inside `audit-report` / `audit_external_project.py`
  (no current evidence consumers ask for retrieval-rank provenance).
- Removing or renaming `_mmr_breakdown` fields — schema is now stable
  under the `--explain` contract.
