"""Tests for _gate_registry.py caching behavior and edge cases."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


import _gate_registry as reg
from _gate_registry import (
    GATE_REGISTRY,
    get_execution_layers,
    topological_sort,
)


class TestExecutionLayersCaching:
    def setup_method(self):
        """Reset cache before each test."""
        reg._cached_layers = None

    def test_cache_populated_after_first_call(self):
        assert reg._cached_layers is None
        get_execution_layers()
        assert reg._cached_layers is not None

    def test_cache_identity_on_second_call(self):
        first = get_execution_layers()
        second = get_execution_layers()
        assert first is second, "Second call should return cached object"

    def test_cache_content_correct(self):
        layers = get_execution_layers()
        all_names = set()
        for _, names in layers:
            all_names.update(names)
        assert all_names == set(GATE_REGISTRY.keys())

    def test_cache_survives_many_calls(self):
        first = get_execution_layers()
        for _ in range(100):
            result = get_execution_layers()
        assert result is first


class TestTopologicalSortCaching:
    def setup_method(self):
        """Reset cache before each test."""
        reg._cached_topo_order = None

    def test_cache_populated_after_first_call(self):
        assert reg._cached_topo_order is None
        topological_sort()
        assert reg._cached_topo_order is not None

    def test_returns_copy_not_cache(self):
        """topological_sort returns a copy so mutations don't corrupt cache."""
        first = topological_sort()
        second = topological_sort()
        assert first is not second, "Should return copy, not cache ref"
        assert first == second, "Content should be identical"

    def test_mutation_safe(self):
        """Mutating returned list should not affect cached result."""
        first = topological_sort()
        first.append("fake_gate")
        second = topological_sort()
        assert "fake_gate" not in second

    def test_cache_survives_many_calls(self):
        for _ in range(100):
            topological_sort()
        assert reg._cached_topo_order is not None
        assert len(reg._cached_topo_order) == 33
