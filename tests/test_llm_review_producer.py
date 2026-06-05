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
    gather_evidence,
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
