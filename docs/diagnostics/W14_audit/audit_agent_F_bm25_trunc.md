# Audit Finding m8 — `scripts/rag/retrieval/bm25.py:271` `entries[:5]`

## Function

**`_validate_kb_shape(data: Any) -> None`** at `scripts/rag/retrieval/bm25.py:253`.

Purpose: minimum-shape contract check on the loaded KB JSON; raises `KBMalformedError` early if the top-level traversal would crash retrieval. Returns `None` — pure validation, no data flow.

## Call sites

- `scripts/rag/retrieval/bm25.py:307` — invoked from `_load_kb()` after `json.load()` and before the cache assignment / return.

Only one caller in the entire repo (verified via `grep -rn "_validate_kb_shape" scripts/ tests/`).

## Verdict

**INTENTIONAL — not a bug. Confidence: high.**

### Reasoning

1. `_validate_kb_shape` returns `None`; it does not filter or truncate `entries`. The full `entries` list lives on `data["entries"]` and is unchanged after validation.
2. `_load_kb()` returns the entire `data` dict (line 310). Downstream retrieval loops iterate `kb.get("entries", [])` over the **full** list at three call sites:
   - `scripts/rag/retrieval/bm25.py:352`
   - `scripts/rag/retrieval/bm25.py:767`
   - `scripts/rag/retrieval/bm25.py:815`
3. The `[:5]` is explicitly labeled in the existing comment at line 269–270 as a **sampling check**: cheap defensive guard against pathological KBs whose first few entries are non-dict (which would crash `.get("reviewer_concerns")` in retrieval).
4. The function docstring (lines 254–259) is clear: "We don't validate every field here — retrieval functions handle missing concern-level fields defensively. This guard only rejects shapes that would make the top-level traversal itself raise."

There is no silent retrieval cap. Audit finding m8 is a **false positive**.

### Minor suggestion (optional, not required)

The existing inline comment at lines 269–270 already explains the intent. A future reader skimming line 271 in isolation might still be alarmed by `[:5]` next to the word "entries" in a retrieval module. A one-line tightening would make it bullet-proof:

```python
    # Sampling check: validate only the first 5 entries — this is a
    # cheap shape guard, NOT a retrieval cap. Retrieval downstream
    # iterates the full entries list (see lines 352, 767, 815).
    # Non-dict entries would crash retrieval loops the moment they
    # iterate .get("reviewer_concerns"). Fail loudly here.
    for idx, entry in enumerate(entries[:5]):
```

No code change is warranted. No patch produced.
