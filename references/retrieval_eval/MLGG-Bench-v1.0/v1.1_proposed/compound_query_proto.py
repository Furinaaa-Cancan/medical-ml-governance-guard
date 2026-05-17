"""v1.1 prototype: compound-query bundle-detector + decompose-and-merge retrieval.

Addresses DIAGNOSIS.md Failure 1: bench_03 compound queries hit@5=0.20 because
hybrid retrieval concentrates on a single dominant CP per query. Fix:
1. Detect bundling markers in the query (numbered lists, "Independently/Moreover",
   sentence-level keyword divergence)
2. Split into sub-queries
3. Retrieve top-K for each
4. Round-robin merge

Run:  cd /Volumes/Seagate/Skill/ml-leakage-guard && python3 /tmp/mlgg_benchmark/v1.1_compound_decompose_proto.py
"""
from __future__ import annotations
import json, re, sys, os
sys.path.insert(0, '/Volumes/Seagate/Skill/ml-leakage-guard')

BUNDLE_PATTERNS = [
    re.compile(r'\(\s*\d+\s*\)[^()]{20,}?\(\s*\d+\s*\)', re.S),     # (1) ... (2) ...
    re.compile(r'\bfirst[,\.]?\b.*?\bsecond[ly]?\b', re.S | re.I),    # "First, X. Second, Y."
    re.compile(r'\b(?:independently|separately|moreover|additionally|furthermore)\b', re.I),
    re.compile(r'\btwo (?:issues|concerns|problems|points)\b', re.I),
    re.compile(r';\s*(?:and|also|moreover|furthermore)\b', re.I),
]

METHOD_KEYS = {
    'leakage', 'validation', 'calibration', 'metric', 'external',
    'cohort', 'bias', 'outcome', 'feature', 'split', 'fairness',
    'subgroup', 'auroc', 'auc', 'dca', 'tripod', 'probast',
}

def looks_compound(query: str) -> bool:
    """Heuristic: 2+ distinct methodological concerns bundled."""
    if len(query.split()) < 25:
        return False
    for pat in BUNDLE_PATTERNS:
        if pat.search(query):
            return True
    # Sentence-keyword divergence
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', query) if len(s.split()) >= 4]
    if len(sentences) >= 2:
        ks = [{k for k in METHOD_KEYS if k in s.lower()} for s in sentences[:3]]
        # If any two sentences have disjoint non-empty keyword sets → compound
        for i in range(len(ks)):
            for j in range(i+1, len(ks)):
                if ks[i] and ks[j] and not (ks[i] & ks[j]):
                    return True
    return False

def decompose(query: str) -> list[str]:
    # Numbered list
    m = re.match(r'.*?\(\s*1\s*\)\s*(.+?)\s*\(\s*2\s*\)\s*(.+?)(?:\(\s*3\s*\)\s*(.+))?$',
                 query, re.S)
    if m:
        return [g.strip().rstrip('.') for g in (m.group(1), m.group(2), m.group(3)) if g]
    # Sentence split (only if compound)
    sentences = [s.strip().rstrip('.') for s in re.split(r'(?<=[.!?])\s+', query)
                 if len(s.split()) >= 5]
    return sentences if len(sentences) >= 2 else [query]

def compound_retrieve(query: str, *, gate=None, failure_codes=None, top_k=5):
    from scripts.rag import rag_query
    if not looks_compound(query):
        return rag_query(query, gate=gate, failure_codes=failure_codes, top_k=top_k), False
    subs = decompose(query)
    if len(subs) <= 1:
        return rag_query(query, gate=gate, failure_codes=failure_codes, top_k=top_k), False
    sub_hits = [rag_query(sq, gate=gate, failure_codes=failure_codes, top_k=top_k) for sq in subs]
    seen = set(); merged = []
    max_len = max(len(h) for h in sub_hits)
    for rank in range(max_len):
        for sub in sub_hits:
            if rank < len(sub):
                cid = sub[rank].get('concern_id')
                if cid not in seen:
                    merged.append(sub[rank])
                    seen.add(cid)
                    if len(merged) == top_k:
                        return merged, True
    return merged, True

def evaluate():
    os.chdir('/Volumes/Seagate/Skill/ml-leakage-guard')
    bench = json.load(open('/tmp/mlgg_benchmark/MLGG-Bench-v1.0.json'))
    compound = [s for s in bench['scenarios'] if s['_slice'] == 'bench_03_compound']
    print(f'\nEvaluating compound prototype on bench_03 (n={len(compound)})\n')
    baseline_hits = 0; proto_hits = 0
    baseline_cp_hits = 0; proto_cp_hits = 0
    decomposed = 0
    from scripts.rag import rag_query as base_rag
    for s in compound:
        exp_tags = set(s.get('expected_tags', []))
        exp_cps = set(s.get('expected_canonical_pattern_ids', []))
        gate = s.get('gate_name') or None
        codes = s.get('failure_codes') or None
        q = s.get('query_text', '')
        # baseline
        b_hits = base_rag(q, gate=gate, failure_codes=codes, top_k=5)
        b_tag_hit = any(exp_tags & set(h.get('tags') or []) for h in b_hits)
        b_cp_hit = any(h.get('canonical_pattern_id') in exp_cps for h in b_hits if h.get('canonical_pattern_id'))
        # proto
        p_hits, used = compound_retrieve(q, gate=gate, failure_codes=codes, top_k=5)
        if used: decomposed += 1
        p_tag_hit = any(exp_tags & set(h.get('tags') or []) for h in p_hits)
        p_cp_hit = any(h.get('canonical_pattern_id') in exp_cps for h in p_hits if h.get('canonical_pattern_id'))
        baseline_hits += int(b_tag_hit); proto_hits += int(p_tag_hit)
        baseline_cp_hits += int(b_cp_hit); proto_cp_hits += int(p_cp_hit)
        delta = ''
        if p_tag_hit and not b_tag_hit: delta = '  WIN'
        elif b_tag_hit and not p_tag_hit: delta = '  LOSS'
        print(f'  [{s["scenario_id"][:50]:50s}] base hit={b_tag_hit} cp={b_cp_hit} | proto hit={p_tag_hit} cp={p_cp_hit} decomposed={used}{delta}')
    n = len(compound)
    print(f'\n=== Result on bench_03 (n={n}) ===')
    print(f'baseline: hit@5={baseline_hits/n:.2f}  cp_hit@5={baseline_cp_hits/n:.2f}')
    print(f'proto:    hit@5={proto_hits/n:.2f}  cp_hit@5={proto_cp_hits/n:.2f}')
    print(f'decomposed: {decomposed}/{n}')
    print(f'tag-hit delta: {proto_hits-baseline_hits:+d}  | cp-hit delta: {proto_cp_hits-baseline_cp_hits:+d}')

if __name__ == '__main__':
    evaluate()
