"""
Tests for performance improvements and bug fixes.

Covers:
- Stats caching
- Converter msgspec fix
- Iterative merge_summary
- Combined analysis + stats
- Streaming query results (query_iter)
- Progress callbacks
- __repr__
- _load_source edge cases
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import msgspec
import pytest

from jsonflux import JsonFlux, QueryEngine
from jsonflux.core.analyzer import merge_summary
from jsonflux.core.converter import normalize_data
from jsonflux.core.models import ArraySummary, Summary

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_data():
    """Simple list of records for testing."""
    return [
        {"id": 1, "name": "Alice", "score": 95.5, "active": True},
        {"id": 2, "name": "Bob", "score": 87.3, "active": False},
        {"id": 3, "name": "Charlie", "score": 92.1, "active": True},
    ]


@pytest.fixture
def large_list():
    """Larger list for progress callback testing."""
    return [{"idx": i, "val": f"item-{i}"} for i in range(500)]


@pytest.fixture
def flux_analyzed(sample_data):
    """JsonFlux instance with data already analyzed."""
    flux = JsonFlux(samples=0)
    flux.analyze(sample_data)
    return flux


# =========================================================================
# 1. Stats caching
# =========================================================================


class TestStatsCaching:
    def test_stats_cached_on_repeated_calls(self, flux_analyzed):
        """stats_result() should return the cached object on the second call."""
        result1 = flux_analyzed.stats_result(max_unique=100)
        result2 = flux_analyzed.stats_result(max_unique=100)
        assert result1 is result2

    def test_stats_cache_invalidated_on_reanalyze(self, flux_analyzed, sample_data):
        """Re-calling analyze() should clear the stats cache."""
        result1 = flux_analyzed.stats_result(max_unique=100)
        flux_analyzed.analyze(sample_data)
        result2 = flux_analyzed.stats_result(max_unique=100)
        # New object after re-analysis
        assert result1 is not result2

    def test_stats_cache_respects_max_unique(self, flux_analyzed):
        """Different max_unique values should produce different results."""
        result_100 = flux_analyzed.stats_result(max_unique=100)
        result_10 = flux_analyzed.stats_result(max_unique=10)
        # Different max_unique => cache miss => new object
        assert result_100 is not result_10
        # But calling with same param again returns cached
        result_10b = flux_analyzed.stats_result(max_unique=10)
        assert result_10 is result_10b


# =========================================================================
# 2. Converter msgspec fix
# =========================================================================


class TestConverterMsgspec:
    def test_normalize_data_serializes_dicts(self):
        """Dicts should be serialized to JSON strings via msgspec, not json."""
        import pyarrow as pa

        data = {"key": "value", "num": 42}
        result = normalize_data(data, pa.string())
        assert isinstance(result, str)
        # Verify it's valid JSON by round-tripping through msgspec
        decoded = msgspec.json.decode(result)
        assert decoded == data

    def test_normalize_data_serializes_lists(self):
        """Lists should be serialized to JSON strings via msgspec."""
        import pyarrow as pa

        data = [1, "two", 3.0]
        result = normalize_data(data, pa.string())
        assert isinstance(result, str)
        decoded = msgspec.json.decode(result)
        assert decoded == data


# =========================================================================
# 3. Iterative merge_summary
# =========================================================================


class TestIterativeMergeSummary:
    def test_merge_deeply_nested_no_overflow(self):
        """merge_summary should handle 200+ levels without stack overflow."""
        # Build two deeply nested summaries
        def make_deep(depth: int) -> Summary:
            s = Summary(primitives=frozenset(("int",)))
            for _ in range(depth):
                s = Summary(obj={"nested": s})
            return s

        a = make_deep(200)
        b = make_deep(200)
        # Should not raise RecursionError
        result = merge_summary(a, b)
        # Walk down to verify structure
        current = result
        for _ in range(200):
            assert current.obj is not None
            assert "nested" in current.obj
            current = current.obj["nested"]
        assert "int" in current.primitives

    def test_merge_produces_correct_result(self):
        """Merged summary should have the union of both sides."""
        a = Summary(
            obj={
                "name": Summary(primitives=frozenset(("str",))),
                "age": Summary(primitives=frozenset(("int",))),
            }
        )
        b = Summary(
            obj={
                "name": Summary(primitives=frozenset(("str",))),
                "email": Summary(primitives=frozenset(("str",))),
            }
        )
        result = merge_summary(a, b)
        assert result.obj is not None
        assert set(result.obj.keys()) == {"name", "age", "email"}
        assert "str" in result.obj["name"].primitives
        assert "int" in result.obj["age"].primitives
        assert "str" in result.obj["email"].primitives

    def test_merge_empty_summaries(self):
        """Merging two empty summaries should produce an empty summary."""
        a = Summary()
        b = Summary()
        result = merge_summary(a, b)
        assert result.primitives == frozenset()
        assert result.obj is None
        assert result.arr is None

    def test_merge_with_array_summaries(self):
        """merge_summary should handle ArraySummary merging correctly."""
        a = Summary(
            arr=ArraySummary(
                len_min=2,
                len_max=5,
                kind_minmax={"int": (2, 5), "str": (0, 0)},
                kind_summaries={},
            )
        )
        b = Summary(
            arr=ArraySummary(
                len_min=1,
                len_max=10,
                kind_minmax={"int": (1, 3), "str": (1, 2)},
                kind_summaries={},
            )
        )
        result = merge_summary(a, b)
        assert result.arr is not None
        assert result.arr.len_min == 1
        assert result.arr.len_max == 10
        assert result.arr.kind_minmax["int"] == (1, 5)
        assert result.arr.kind_minmax["str"] == (0, 2)

    def test_merge_with_nested_array_kind_summaries(self):
        """Array kind_summaries should be merged recursively."""
        obj_a = Summary(obj={"x": Summary(primitives=frozenset(("int",)))})
        obj_b = Summary(
            obj={
                "x": Summary(primitives=frozenset(("int",))),
                "y": Summary(primitives=frozenset(("str",))),
            }
        )
        a = Summary(
            arr=ArraySummary(
                len_min=1,
                len_max=3,
                kind_minmax={"object": (1, 3)},
                kind_summaries={"object": obj_a},
            )
        )
        b = Summary(
            arr=ArraySummary(
                len_min=2,
                len_max=4,
                kind_minmax={"object": (2, 4)},
                kind_summaries={"object": obj_b},
            )
        )
        result = merge_summary(a, b)
        merged_obj = result.arr.kind_summaries["object"]
        assert merged_obj.obj is not None
        assert set(merged_obj.obj.keys()) == {"x", "y"}


# =========================================================================
# 4. Combined analysis + stats
# =========================================================================


class TestCombinedAnalysisStats:
    def test_collect_stats_flag_populates_cache(self, sample_data):
        """analyze(collect_stats=True) should populate the stats cache."""
        flux = JsonFlux(samples=0)
        flux.analyze(sample_data, collect_stats=True)
        # Cache should be populated — calling stats_result shouldn't recompute
        result = flux.stats_result(max_unique=100)
        assert result is not None
        assert result.total_values > 0

    def test_combined_stats_match_separate(self, sample_data):
        """Stats from combined pass should match stats from separate call."""
        flux1 = JsonFlux(samples=0)
        flux1.analyze(sample_data, collect_stats=True, max_unique=100)
        combined = flux1.stats_result(max_unique=100)

        flux2 = JsonFlux(samples=0)
        flux2.analyze(sample_data)
        separate = flux2.stats_result(max_unique=100)

        assert combined.total_values == separate.total_values
        assert combined.total_objects == separate.total_objects
        assert combined.total_primitives == separate.total_primitives
        assert combined.max_depth == separate.max_depth

    def test_combined_stats_cached_after_analyze(self, sample_data):
        """After analyze(collect_stats=True), stats_result returns the cached object."""
        flux = JsonFlux(samples=0)
        flux.analyze(sample_data, collect_stats=True, max_unique=100)
        r1 = flux.stats_result(max_unique=100)
        r2 = flux.stats_result(max_unique=100)
        assert r1 is r2


# =========================================================================
# 5. Streaming query results (query_iter)
# =========================================================================


class TestQueryIter:
    def test_query_iter_returns_all_rows(self, sample_data):
        """query_iter should yield every row."""
        engine = QueryEngine()
        engine.register("t", sample_data)
        rows = list(engine.query_iter("SELECT * FROM t ORDER BY id"))
        assert len(rows) == 3
        assert rows[0]["id"] == 1
        assert rows[2]["id"] == 3
        engine.close()

    def test_query_iter_batch_size(self, sample_data):
        """query_iter should work correctly with various batch sizes."""
        engine = QueryEngine()
        engine.register("t", sample_data)
        # Very small batch size
        rows = list(engine.query_iter("SELECT * FROM t", batch_size=1))
        assert len(rows) == 3
        # Larger than result set
        rows2 = list(engine.query_iter("SELECT * FROM t", batch_size=10000))
        assert len(rows2) == 3
        engine.close()

    def test_query_iter_empty_result(self, sample_data):
        """query_iter should handle empty results gracefully."""
        engine = QueryEngine()
        engine.register("t", sample_data)
        rows = list(engine.query_iter("SELECT * FROM t WHERE id > 999"))
        assert rows == []
        engine.close()

    def test_flux_query_iter(self, flux_analyzed):
        """JsonFlux.query_iter should delegate to the engine correctly."""
        rows = list(
            flux_analyzed.query_iter("SELECT * FROM data ORDER BY id", batch_size=2)
        )
        assert len(rows) == 3
        assert rows[0]["name"] == "Alice"


# =========================================================================
# 6. Progress callbacks
# =========================================================================


class TestProgressCallbacks:
    def test_progress_callback_invoked(self, large_list):
        """Progress callback should be called with (current, total) tuples."""
        calls: list[tuple[int, int]] = []

        def on_progress(current: int, total: int) -> None:
            calls.append((current, total))

        flux = JsonFlux(samples=0)
        flux.analyze(large_list, progress=on_progress)

        # Should have been called at least twice (first element + final)
        assert len(calls) >= 2
        # Final call should be (total, total)
        assert calls[-1] == (500, 500)
        # All calls should have correct total
        assert all(total == 500 for _, total in calls)

    def test_progress_none_is_fine(self, sample_data):
        """progress=None (default) should work without error."""
        flux = JsonFlux(samples=0)
        flux.analyze(sample_data, progress=None)
        assert flux.profile_result() is not None

    def test_progress_total_matches_data(self):
        """The total reported should match the length of the input list."""
        data = [{"x": i} for i in range(123)]
        totals: set[int] = set()

        def on_progress(current: int, total: int) -> None:
            totals.add(total)

        flux = JsonFlux(samples=0)
        flux.analyze(data, progress=on_progress)
        assert totals == {123}

    def test_progress_not_called_for_dict_root(self):
        """Progress callback should NOT be called when root is a dict."""
        calls: list[tuple[int, int]] = []

        def on_progress(current: int, total: int) -> None:
            calls.append((current, total))

        flux = JsonFlux(samples=0)
        flux.analyze({"key": "value"}, progress=on_progress)
        assert calls == []


# =========================================================================
# 7. __repr__
# =========================================================================


class TestRepr:
    def test_repr_before_analyze(self):
        """repr should indicate not yet analyzed."""
        flux = JsonFlux()
        assert repr(flux) == "JsonFlux(analyzed=False)"

    def test_repr_after_analyze(self, sample_data):
        """repr should indicate analyzed with source type."""
        flux = JsonFlux(samples=0)
        flux.analyze(sample_data)
        r = repr(flux)
        assert "analyzed=True" in r
        assert "source=" in r


# =========================================================================
# 8. _load_source edge cases
# =========================================================================


class TestLoadSourceEdgeCases:
    def test_scalar_json_true(self):
        """'true' should parse as a JSON boolean."""
        flux = JsonFlux(samples=0)
        flux.analyze("true")
        assert flux.data is True

    def test_scalar_json_number(self):
        """'42' should parse as a JSON integer."""
        flux = JsonFlux(samples=0)
        flux.analyze("42")
        assert flux.data == 42

    def test_scalar_json_string(self):
        """A quoted JSON string should parse correctly."""
        flux = JsonFlux(samples=0)
        flux.analyze('"hello"')
        assert flux.data == "hello"

    def test_invalid_string_raises_valueerror(self):
        """A string that is neither valid JSON nor a file should raise ValueError."""
        flux = JsonFlux(samples=0)
        with pytest.raises(ValueError, match="not valid JSON"):
            flux.analyze("this is not json or a file path!!!")

    def test_file_path_still_works(self, sample_data):
        """File paths should still load correctly."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="wb", delete=False) as f:
            f.write(msgspec.json.encode(sample_data))
            fpath = f.name

        try:
            flux = JsonFlux(samples=0)
            flux.analyze(fpath)
            assert isinstance(flux.data, list)
            assert len(flux.data) == 3
        finally:
            import os

            os.unlink(fpath)

    def test_path_object_still_works(self, sample_data):
        """pathlib.Path objects should still load correctly."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="wb", delete=False) as f:
            f.write(msgspec.json.encode(sample_data))
            fpath = Path(f.name)

        try:
            flux = JsonFlux(samples=0)
            flux.analyze(fpath)
            assert isinstance(flux.data, list)
            assert len(flux.data) == 3
        finally:
            fpath.unlink()


# =========================================================================
# 9. Additional edge-case tests for existing behaviour
# =========================================================================


class TestExistingBehaviourPreserved:
    def test_stats_formatted_output(self, flux_analyzed):
        """stats() should return formatted string (compact and full)."""
        full = flux_analyzed.stats()
        assert "JSON STATISTICS" in full
        assert "Total values:" in full

        compact = flux_analyzed.stats(compact=True)
        assert "COMPACT" in compact

    def test_analyze_returns_self(self, sample_data):
        """analyze() should return self for chaining."""
        flux = JsonFlux(samples=0)
        result = flux.analyze(sample_data)
        assert result is flux

    def test_timing_present(self, flux_analyzed):
        """timing() should contain expected keys."""
        t = flux_analyzed.timing()
        assert "parse_time" in t
        assert "analyze_time" in t
        assert "sample_time" in t
        assert "total_time" in t
