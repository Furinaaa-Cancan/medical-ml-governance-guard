"""
Stress tests for audit chain — large logs, concurrent appends, corruption recovery.

These tests are marked @pytest.mark.slow and designed for overnight CI runs.
Expected runtime: ~30-60 minutes total.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _gate_utils import append_audit_entry, verify_audit_chain


# ────────────────────────────────────────────────────────
# Large audit log stress tests
# ────────────────────────────────────────────────────────

class TestLargeAuditLog:
    @pytest.mark.slow
    def test_10k_entries_append_and_verify(self, tmp_path: Path):
        """Append 10,000 entries and verify chain integrity."""
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(10_000):
            append_audit_entry(
                evidence, f"gate_{i % 31}", "pass",
                failure_count=0, warning_count=i % 3,
                execution_time=0.01 * i,
            )
        result = verify_audit_chain(evidence)
        assert result["valid"] is True
        assert result["entries"] == 10_000

    @pytest.mark.slow
    def test_50k_entries_streaming_verify(self, tmp_path: Path):
        """Append 50,000 entries — verify streaming doesn't OOM."""
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(50_000):
            append_audit_entry(
                evidence, f"gate_{i % 31}", "pass" if i % 5 != 0 else "fail",
                failure_count=1 if i % 5 == 0 else 0,
                execution_time=0.001,
            )
        result = verify_audit_chain(evidence)
        assert result["valid"] is True
        assert result["entries"] == 50_000

    @pytest.mark.slow
    def test_large_extra_metadata(self, tmp_path: Path):
        """Entries with large extra metadata payloads."""
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        big_extra = {"features": [f"feat_{i}" for i in range(500)],
                     "metrics": {f"m{i}": 0.5 + i * 0.001 for i in range(200)}}
        for i in range(1_000):
            append_audit_entry(
                evidence, "big_gate", "pass",
                extra=big_extra, execution_time=1.5,
            )
        result = verify_audit_chain(evidence)
        assert result["valid"] is True
        assert result["entries"] == 1_000


# ────────────────────────────────────────────────────────
# Tamper detection stress
# ────────────────────────────────────────────────────────

class TestTamperDetection:
    def _build_log(self, evidence: Path, n: int) -> None:
        for i in range(n):
            append_audit_entry(evidence, f"gate_{i}", "pass", execution_time=0.01)

    @pytest.mark.slow
    def test_tamper_first_entry_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 5000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        # Tamper with first entry
        entry = json.loads(lines[0])
        entry["status"] = "TAMPERED"
        lines[0] = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False
        assert result["broken_at"] == 0

    @pytest.mark.slow
    def test_tamper_middle_entry_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 5000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        mid = len(lines) // 2
        entry = json.loads(lines[mid])
        entry["failure_count"] = 999
        lines[mid] = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False
        assert result["broken_at"] == mid

    @pytest.mark.slow
    def test_tamper_last_entry_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 5000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[-1])
        entry["gate_name"] = "HACKED"
        lines[-1] = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False

    @pytest.mark.slow
    def test_deleted_entry_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 5000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        # Delete entry in the middle
        del lines[2500]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False

    @pytest.mark.slow
    def test_inserted_entry_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 5000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        fake = json.dumps({
            "timestamp_utc": "2026-01-01T00:00:00",
            "gate_name": "injected",
            "status": "pass",
            "failure_count": 0,
            "warning_count": 0,
            "execution_time_seconds": 0,
            "pid": 1,
            "hostname": "fake",
            "chain_hash": "0" * 64,
        })
        lines.insert(2500, fake)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False

    @pytest.mark.slow
    def test_reorder_entries_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self._build_log(evidence, 1000)
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        # Swap two adjacent entries
        lines[500], lines[501] = lines[501], lines[500]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False


# ────────────────────────────────────────────────────────
# Corruption resilience
# ────────────────────────────────────────────────────────

class TestCorruptionResilience:
    @pytest.mark.slow
    def test_truncated_json_line(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(100):
            append_audit_entry(evidence, "gate", "pass")
        log = evidence / ".gate_audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        lines[50] = lines[50][:20]  # Truncate a line
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is False
        assert result["broken_at"] == 50

    @pytest.mark.slow
    def test_binary_garbage_in_log(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(100):
            append_audit_entry(evidence, "gate", "pass")
        log = evidence / ".gate_audit.jsonl"
        content = log.read_bytes()
        # Inject garbage in the middle
        mid = len(content) // 2
        corrupted = content[:mid] + b"\xff\xfe\x00GARBAGE\n" + content[mid:]
        log.write_bytes(corrupted)
        result = verify_audit_chain(evidence)
        assert result["valid"] is False

    def test_empty_log_file(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        (evidence / ".gate_audit.jsonl").write_text("", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is True
        assert result["entries"] == 0

    def test_only_blank_lines(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        (evidence / ".gate_audit.jsonl").write_text("\n\n\n\n", encoding="utf-8")
        result = verify_audit_chain(evidence)
        assert result["valid"] is True
        assert result["entries"] == 0
