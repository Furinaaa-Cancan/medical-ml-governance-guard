"""LLM review synthesis producer (P1.0a): evidence -> adapter -> review report.

Covers the producer plumbing with the deterministic test double (no network),
the guard that the live adapter never makes an unattended call, and the
producer->consumer integration: a blocking concern fails publication_gate, an
advisory concern only warns.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REVIEW = Path(__file__).resolve().parents[1] / "scripts" / "review"
if str(_REVIEW) not in sys.path:
    sys.path.insert(0, str(_REVIEW))

import pytest  # noqa: E402

from llm_review import (  # noqa: E402
    DeterministicReviewAdapter,
    LiveClaudeReviewAdapter,
    _build_review_prompt,
    gather_evidence,
    gather_rag_concerns,
    run_llm_review,
)
from test_publication_gate import _build_cmd, _make_all_artifacts  # noqa: E402


def _write_report(path: Path, **fields):
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_gather_evidence_reads_reports(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="pass",
                  failure_count=0, warning_count=1, warnings=[{"code": "w1", "message": "m"}], run_id="R1")
    _write_report(tmp_path / "tuning_report.json", gate_name="tuning_gate", status="pass", run_id="R1")

    ctx = gather_evidence(tmp_path)
    assert ctx["gate_count"] == 2
    assert ctx["run_id"] == "R1"
    gates = {g["gate"]: g for g in ctx["gates"]}
    assert gates["leakage_gate"]["warnings"][0]["code"] == "w1"


def test_deterministic_adapter_echoes_warnings(tmp_path: Path):
    ctx = {"gates": [{"gate": "leakage_gate", "warnings": [{"code": "no_dca", "message": "add DCA"}]}],
           "gate_count": 1}
    out = DeterministicReviewAdapter().synthesize(ctx)
    assert out["concerns"][0]["severity"] == "advisory"
    assert out["concerns"][0]["code"] == "echo_no_dca"
    assert out["meta"]["model"] == "deterministic-double"
    assert len(out["meta"]["prompt_hash"]) == 64
    assert out["meta"]["evidence_seen"] == 1


def test_deterministic_adapter_explicit_concerns():
    given = [{"severity": "blocking", "code": "f02", "message": "post-index", "detail": {}}]
    out = DeterministicReviewAdapter(concerns=given).synthesize({"gates": [], "gate_count": 0})
    assert out["concerns"] == given


def test_run_llm_review_writes_p00_schema(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="pass", run_id="RUN-9")
    report = run_llm_review(tmp_path)

    written = json.loads((tmp_path / "llm_review_report.json").read_text())
    assert written == report
    assert "concerns" in written and isinstance(written["concerns"], list)
    assert "meta" in written
    assert written["run_id"] == "RUN-9"


def test_live_adapter_never_calls_when_disabled():
    with pytest.raises(RuntimeError):
        LiveClaudeReviewAdapter().synthesize({"gates": []})
    # enabled but no client → still guarded
    with pytest.raises(RuntimeError):
        LiveClaudeReviewAdapter(enabled=True).synthesize({"gates": []})


# ── producer -> consumer integration ─────────────────────────────────────────

def _run_pub_gate(tmp_path, paths):
    result = subprocess.run(_build_cmd(tmp_path, paths), capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def test_producer_blocking_concern_fails_publication(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    run_llm_review(tmp_path, adapter=DeterministicReviewAdapter(concerns=[
        {"severity": "blocking", "code": "f02_post_index", "message": "post-index feature", "detail": {}},
    ]))
    result, report = _run_pub_gate(tmp_path, paths)
    assert result.returncode == 2
    assert "llm_blocking_concern" in [f.get("code") for f in report.get("failures", [])]


def test_producer_advisory_concern_only_warns(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    run_llm_review(tmp_path, adapter=DeterministicReviewAdapter(concerns=[
        {"severity": "advisory", "code": "minor", "message": "consider NRI", "detail": {}},
    ]))
    result, report = _run_pub_gate(tmp_path, paths)
    assert result.returncode == 0
    assert "llm_advisory_concern" in [w.get("code") for w in report.get("warnings", [])]


# ── P1.0b: LiveClaudeReviewAdapter with a DUCK-TYPED MOCK client (no real/paid call) ────────

class _FakeBlock:
    def __init__(self, type, name=None, input=None):
        self.type = type
        self.name = name
        self.input = input


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, response, calls):
        self._response = response
        self._calls = calls

    def create(self, **kwargs):  # mimics anthropic client.messages.create
        self._calls.append(kwargs)
        return self._response


class _FakeClient:
    """Duck-typed stand-in for anthropic.Anthropic — records calls, makes no network request."""

    def __init__(self, response):
        self.calls: list = []
        self.messages = _FakeMessages(response, self.calls)


def _client_returning(concerns):
    block = _FakeBlock(type="tool_use", name="report_concerns", input={"concerns": concerns})
    return _FakeClient(_FakeResponse([block]))


def test_live_adapter_parses_tool_use_concerns():
    concerns = [{"severity": "blocking", "code": "f02", "message": "post-index feature", "detail": {"feature": "lab_3"}}]
    client = _client_returning(concerns)
    adapter = LiveClaudeReviewAdapter(client=client, enabled=True)

    out = adapter.synthesize({"gates": [{"gate": "leakage_gate", "warnings": [{"code": "w", "message": "m"}]}],
                              "gate_count": 1})

    assert out["concerns"] == concerns
    assert out["meta"]["model"] == "claude-opus-4-8"
    assert len(out["meta"]["prompt_hash"]) == 64
    assert out["meta"]["evidence_seen"] == 1


def test_live_adapter_call_shape_is_correct():
    # Verify the messages.create shape so a real client works when the user enables it.
    client = _client_returning([])
    LiveClaudeReviewAdapter(client=client, model="claude-opus-4-8", enabled=True).synthesize(
        {"gates": [], "gate_count": 0}
    )
    assert len(client.calls) == 1
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-4-8"
    assert kw["tool_choice"] == {"type": "tool", "name": "report_concerns"}
    assert any(t["name"] == "report_concerns" for t in kw["tools"])
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}  # static prompt cached


def test_live_adapter_still_guarded_without_enable():
    # Even with a client, enabled=False must NOT call it (no accidental paid call).
    client = _client_returning([])
    with pytest.raises(RuntimeError):
        LiveClaudeReviewAdapter(client=client, enabled=False).synthesize({"gates": [], "gate_count": 0})
    assert client.calls == []  # never called


def test_run_llm_review_with_live_adapter_writes_report(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="pass", run_id="R-LIVE")
    client = _client_returning([{"severity": "advisory", "code": "c", "message": "m"}])
    report = run_llm_review(tmp_path, adapter=LiveClaudeReviewAdapter(client=client, enabled=True))

    written = json.loads((tmp_path / "llm_review_report.json").read_text())
    assert written == report
    assert written["concerns"][0]["code"] == "c"
    assert written["meta"]["model"] == "claude-opus-4-8"
    assert written["run_id"] == "R-LIVE"


# ── ②→④ wire: RAG peer-review concerns into the reviewer context ──────────────

def _fake_kb_record(concern_id, severity="HIGH", category="preprocessing_leakage",
                    text="Reviewer flagged scaler fit before split."):
    return {
        "concern_id": concern_id, "severity": severity, "category": category,
        "concern_text": text, "tags": ["scaler_leakage"], "_final_score": 0.9,
    }


def test_gather_rag_concerns_queries_only_failing_gates():
    calls = []

    def fake_retriever(query, gate=None, failure_codes=None, top_k=5):
        calls.append({"query": query, "gate": gate, "codes": failure_codes})
        return [_fake_kb_record("PR-001-C01")]

    gates = [
        {"gate": "leakage_gate", "status": "fail",
         "failures": [{"code": "P01", "message": "scaler fit before split"}], "warnings": []},
        {"gate": "tuning_gate", "status": "pass", "failures": [], "warnings": []},
    ]
    out = gather_rag_concerns(gates, fake_retriever)
    # Only the failing gate is queried, with its name + codes + message.
    assert len(calls) == 1
    assert calls[0]["gate"] == "leakage_gate"
    assert calls[0]["codes"] == ["P01"]
    assert "scaler fit before split" in calls[0]["query"]
    # The KB record is formatted into a human-readable line.
    assert len(out) == 1
    assert "[HIGH]" in out[0] and "(preprocessing_leakage)" in out[0]
    assert "KB:PR-001-C01" in out[0]


def test_gather_rag_concerns_none_retriever_is_noop():
    gates = [{"gate": "leakage_gate", "status": "fail",
              "failures": [{"code": "P01", "message": "m"}], "warnings": []}]
    assert gather_rag_concerns(gates, None) == []


def test_gather_rag_concerns_survives_error_and_dedups():
    def boom(query, gate=None, failure_codes=None, top_k=5):
        raise RuntimeError("KB exploded")

    gates = [{"gate": "leakage_gate", "status": "fail",
              "failures": [{"code": "P01", "message": "m"}], "warnings": []}]
    # A retriever error degrades to no concerns — never crashes the review.
    assert gather_rag_concerns(gates, boom) == []

    def dup(query, gate=None, failure_codes=None, top_k=5):
        return [_fake_kb_record("DUP"), _fake_kb_record("DUP")]

    gates2 = [
        {"gate": "a_gate", "status": "fail", "failures": [{"code": "X", "message": "m"}], "warnings": []},
        {"gate": "b_gate", "status": "fail", "failures": [{"code": "Y", "message": "m"}], "warnings": []},
    ]
    assert len(gather_rag_concerns(gates2, dup)) == 1  # deduped by concern_id across gates


def test_gather_evidence_populates_rag_concerns(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="fail",
                  failure_count=1, failures=[{"code": "P01", "message": "scaler fit before split"}])

    def fake_retriever(query, gate=None, failure_codes=None, top_k=5):
        return [_fake_kb_record("PR-009-C02")]

    ctx = gather_evidence(tmp_path, retriever=fake_retriever)
    assert ctx["rag_concerns"] and "KB:PR-009-C02" in ctx["rag_concerns"][0]
    # Default (no retriever) stays retrieval-free.
    assert gather_evidence(tmp_path)["rag_concerns"] == []


def test_live_prompt_renders_rag_concerns():
    ctx = {
        "gates": [{"gate": "leakage_gate", "status": "fail", "failure_count": 1, "warning_count": 0,
                   "failures": [{"code": "P01", "message": "scaler fit before split"}], "warnings": []}],
        "gate_count": 1,
        "rag_concerns": ["[HIGH] (preprocessing_leakage) Reviewer flagged scaler fit. — KB:PR-001-C01"],
    }
    prompt = _build_review_prompt(ctx)
    assert "# Retrieved peer-review concerns" in prompt
    assert "KB:PR-001-C01" in prompt


def test_run_llm_review_records_rag_evidence_count(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="fail",
                  failure_count=1, failures=[{"code": "P01", "message": "m"}])

    def fake_retriever(query, gate=None, failure_codes=None, top_k=5):
        return [_fake_kb_record("PR-1"), _fake_kb_record("PR-2")]

    assert run_llm_review(tmp_path, retriever=fake_retriever)["rag_evidence_count"] == 2


def test_gather_rag_concerns_call_matches_real_rag_query_signature():
    """Guard the ②→④ wire against rag_query signature drift.

    The fake-retriever tests above prove the wiring logic; this asserts the kwargs
    gather_rag_concerns passes (query, gate, failure_codes, top_k) are actually
    accepted by the REAL scripts.rag.query.rag_query — so a future signature
    change can't silently break a live `mlgg llm-review --rag` run. Importing the
    function is torch-free (rag_query defers the dense stack).
    """
    import inspect

    from scripts.rag.query import rag_query

    params = inspect.signature(rag_query).parameters
    for kw in ("query", "gate", "failure_codes", "top_k"):
        assert kw in params, f"rag_query no longer accepts {kw!r}; the ②→④ wire would break"


# ── end-to-end through the real mlgg CLI: producer -> publication_gate consumer ─

_MLGG = Path(__file__).resolve().parents[1] / "scripts" / "orchestration" / "mlgg.py"


def test_cli_llm_review_chain_to_publication_gate(tmp_path: Path):
    """`mlgg llm-review` (CLI) writes the report; publication_gate discovers + folds it.

    Proves the formerly-orphaned advisory layer now runs end-to-end through the
    real entry point: the deterministic adapter echoes a gate warning as an
    advisory concern, which publication_gate consumes (present=True; advisory
    only, so it cannot fail a passing gate without --strict).
    """
    paths = _make_all_artifacts(tmp_path)
    # A warning-bearing report for the deterministic adapter to echo (NOT a
    # publication_gate component — just discovered by gather_evidence's glob).
    _write_report(tmp_path / "extra_warning_report.json", gate_name="calibration_gate",
                  status="pass", warning_count=1,
                  warnings=[{"code": "no_dca", "message": "no decision-curve analysis"}])

    cli = subprocess.run(
        [sys.executable, str(_MLGG), "llm-review", "--evidence-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert cli.returncode == 0, cli.stderr
    review = json.loads((tmp_path / "llm_review_report.json").read_text())
    assert review["meta"]["model"] == "deterministic-double"
    assert any(c.get("severity") == "advisory" for c in review["concerns"])

    result, report = _run_pub_gate(tmp_path, paths)
    assert result.returncode == 0  # advisory only, no --strict
    adv = report["summary"]["llm_advisory_review"]
    assert adv["present"] is True and adv["advisory_count"] >= 1
    assert report["summary"]["claim"]["reviewer_concerns_incorporated"] is True
