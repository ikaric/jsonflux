from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import msgspec

from .core.analyzer import (
    ALL_KINDS,
    KIND_ORDER,
    PRIMITIVE_KINDS,
    Analyzer,
    fmt_count,
    fmt_types,
    kind_of,
    render_bracket,
    render_schema,
    render_tabs,
    render_tree,
    summary_to_schema,
    summary_to_tree,
)
from .core.models import ProfileResult, Summary, TreeNode
from .core.stats import (
    FieldStats,
    StatsResult,
    estimate_json_size,
    fmt_bytes,
    fmt_size,
    format_stats,
    format_stats_compact,
)
from .core.stats import (
    collect_stats as collect_stats_fn,
)
from .query.engine import (
    QueryEngine,
    QueryResult,
    ReadOnlyViolationError,
    ResultTooLargeError,
)
from .query.security import SecurityConfig
from .utils.sampling import ReservoirSampler

# Re-export under original name for public API
collect_stats = collect_stats_fn

# --------------------------
# Version
# --------------------------

__version__ = "1.0.0"

# --------------------------
# Public API exports
# --------------------------

__all__ = [
    # Version
    "__version__",
    # Main class
    "JsonFlux",
    "JsonFluxConfig",
    # Core models
    "ProfileResult",
    "TreeNode",
    "Summary",
    "StatsResult",
    "FieldStats",
    # Analyzer components
    "Analyzer",
    "ReservoirSampler",
    "QueryEngine",
    "QueryResult",
    "ReadOnlyViolationError",
    "ResultTooLargeError",
    "SecurityConfig",
    # Utility functions
    "kind_of",
    "fmt_types",
    "fmt_count",
    "fmt_size",
    "fmt_bytes",
    "estimate_json_size",
    "format_stats",
    "format_stats_compact",
    "collect_stats",
    # Tree rendering
    "summary_to_tree",
    "render_tree",
    "render_tabs",
    "render_bracket",
    # Schema rendering (LLM-friendly)
    "summary_to_schema",
    "render_schema",
    # Constants
    "PRIMITIVE_KINDS",
    "ALL_KINDS",
    "KIND_ORDER",
    # Validation
    "validate",
]


# --------------------------
# Configuration (msgspec.Struct for speed)
# --------------------------


class JsonFluxConfig(msgspec.Struct, gc=False):
    """Configuration for JsonFlux profiler."""

    max_depth: int = 32
    sample_per_kind: int = 200
    sort_keys: bool = True
    max_keys_per_object: int | None = None
    samples: int = 3
    sample_seed: int = 12345
    max_sample_len: int = 60


class JsonFlux:
    """
    Main entry point for JSON structure analysis and querying.

    Example:
        flux = JsonFlux(max_depth=20, samples=5)
        result = flux.analyze(data)
        print(flux.tree())
        print(flux.stats())
    """

    __slots__ = (
        "config",
        "analyzer",
        "security",
        "data",
        "_last_profile",
        "_engine",
        "_last_stats",
        "_last_stats_max_unique",
    )

    def __init__(
        self,
        max_depth: int = 32,
        sample_per_kind: int = 200,
        sort_keys: bool = True,
        max_keys_per_object: int | None = None,
        samples: int = 3,
        sample_seed: int = 12345,
        max_sample_len: int = 60,
        security: SecurityConfig | None = None,
    ):
        """
        Args:
            security: Sandbox/resource policy for the SQL engine used by
                :meth:`query`.  When ``None`` a secure default is used
                (no filesystem/network access, no extensions, locked config,
                2GB memory limit, 30s query timeout).  See
                :class:`~jsonflux.SecurityConfig`.
        """
        self.config = JsonFluxConfig(
            max_depth=max_depth,
            sample_per_kind=sample_per_kind,
            sort_keys=sort_keys,
            max_keys_per_object=max_keys_per_object,
            samples=samples,
            sample_seed=sample_seed,
            max_sample_len=max_sample_len,
        )
        self.analyzer = Analyzer(
            max_depth=max_depth,
            sample_per_kind=sample_per_kind,
            sort_keys=sort_keys,
            max_keys_per_object=max_keys_per_object,
        )
        self.security = security
        self.data: Any = None
        self._last_profile: ProfileResult | None = None
        self._engine: QueryEngine | None = None
        self._last_stats: StatsResult | None = None
        self._last_stats_max_unique: int = 0

    def analyze(
        self,
        source: dict | list | str | list[str] | Path,
        collect_stats: bool = False,
        max_unique: int = 100,
        progress: Callable[[int, int], None] | None = None,
    ) -> JsonFlux:
        """
        Load and analyze JSON data using msgspec for fast parsing.

        Args:
            source: JSON data source (dict, list, JSON string, file path, etc.)
            collect_stats: If True, also collect statistics during analysis
                to avoid a second traversal when calling stats() later.
            max_unique: Maximum unique values to track per field (only used
                when collect_stats is True).
            progress: Optional callback invoked as ``progress(current, total)``
                during analysis of list data.  Called periodically, not on
                every element.
        """
        config = self.config

        # Invalidate caches
        if self._engine is not None:
            self._engine.close()
            self._engine = None
        self._last_stats = None
        self._last_stats_max_unique = 0

        # Parse JSON (timed)
        t0 = time.perf_counter()
        data, source_type = self._load_source(source)
        self.data = data
        parse_time = time.perf_counter() - t0

        # Build structure summary (timed)
        t0 = time.perf_counter()
        summary = self.analyzer.summarize(
            data, self.analyzer.max_depth, progress=progress
        )
        analyze_time = time.perf_counter() - t0

        # Collect samples if enabled (timed)
        t0 = time.perf_counter()
        sample_store: dict[tuple[str, ...], ReservoirSampler] = {}
        if config.samples > 0:
            rng = random.Random(config.sample_seed)
            self.analyzer.collect_samples(data, sample_store, k=config.samples, rng=rng)
        sample_time = time.perf_counter() - t0

        self._last_profile = ProfileResult(
            summary=summary,
            sample_store=sample_store,
            source=source_type,
            parse_time=parse_time,
            analyze_time=analyze_time,
            sample_time=sample_time,
        )

        # Optionally collect stats in the same call to avoid a second traversal
        if collect_stats:
            self._last_stats = collect_stats_fn(self.data, max_unique=max_unique)
            self._last_stats_max_unique = max_unique

        return self

    def _load_source(
        self, source: dict | list | str | list[str] | Path
    ) -> tuple[Any, str]:
        """Load JSON from various source types using msgspec for speed."""
        t = type(source)
        if t is dict:
            return source, "dict"
        if t is list:
            # Check if list of JSON strings
            if source and isinstance(source[0], str):
                return [msgspec.json.decode(s) for s in source], "json_strings"
            return source, "list"
        if isinstance(source, Path):
            with open(source, "rb") as f:
                return msgspec.json.decode(f.read()), "file"
        if t is str:
            # Check if it's an existing file first (avoids misinterpreting
            # filenames like "[config].json" as JSON content)
            if os.path.exists(source):
                with open(source, "rb") as f:
                    return msgspec.json.decode(f.read()), "file"
            source_stripped = source.strip()
            if source_stripped.startswith("{") or source_stripped.startswith("["):
                return msgspec.json.decode(source), "json_string"
            # Try parsing as a JSON scalar (e.g. "true", "42", '"hello"')
            try:
                return msgspec.json.decode(source), "json_string"
            except msgspec.DecodeError:
                pass
            # Nothing worked -- give a clear error instead of FileNotFoundError
            raise ValueError(
                f"Source string is not valid JSON and no file found at path: {source!r}"
            )
        raise TypeError(f"Unsupported source type: {t}")

    def tree(
        self,
        format: str = "tree",
        indent: str = "\t",
        root_label: str = "<root>",
    ) -> str:
        """
        Return a structural report of the JSON data.

        Args:
            format: Output format:
                - "tree": Box-drawing connectors (├── └──)
                - "tabs": Tab-indented (TSV-like)
                - "bracket": Curly brace nesting
                - "schema": Compact TypeScript-like (LLM-optimized, token-efficient)
            indent: Indentation string for tabs/bracket formats (default: tab character)
            root_label: Label for the root node (not used in schema format)

        Returns:
            Formatted structure string

        Examples:
            flux.tree()                    # Box-drawing tree with samples
            flux.tree(format="tabs")       # Tab-indented
            flux.tree(format="schema")     # Compact schema for LLMs
        """
        if not self._last_profile:
            raise ValueError("No data analyzed yet. Call analyze() first.")

        # Schema format uses different renderer (works on Summary, not TreeNode)
        if format == "schema":
            return render_schema(
                self._last_profile.summary,
                sample_store=self._last_profile.sample_store,
                max_sample_len=self.config.max_sample_len,
                samples_k=self.config.samples,
            )

        # Other formats use TreeNode-based rendering
        root_node = self._build_tree(self._last_profile, root_label)

        if format == "tree":
            return render_tree(root_node)
        elif format == "tabs":
            return render_tabs(root_node, indent)
        elif format == "bracket":
            return render_bracket(root_node, indent)
        else:
            raise ValueError(
                f"Unknown format: {format}. Use 'tree', 'tabs', 'bracket', or 'schema'."
            )

    def stats(
        self, compact: bool = False, top_n: int = 50, max_unique: int = 100
    ) -> str:
        """
        Return a statistical report of the data.

        Args:
            compact: If True, return compact summary without per-path breakdown
            top_n: Number of top paths to show (for non-compact mode)
            max_unique: Maximum unique values to track per field

        Returns:
            Formatted statistics string
        """
        result = self.stats_result(max_unique=max_unique)

        if compact:
            return format_stats_compact(result)
        return format_stats(result, top_n=top_n)

    def stats_result(self, max_unique: int = 100) -> StatsResult:
        """
        Return the raw StatsResult object for programmatic access.

        Results are cached: repeated calls with the same ``max_unique``
        return the cached result without re-traversing the data.  The
        cache is invalidated whenever ``analyze()`` is called.

        Args:
            max_unique: Maximum unique values to track per field

        Returns:
            StatsResult struct with all collected statistics
        """
        if self.data is None:
            raise ValueError("No data analyzed yet. Call analyze() first.")
        # Return cached result if available and max_unique matches
        if self._last_stats is not None and self._last_stats_max_unique == max_unique:
            return self._last_stats
        result = collect_stats_fn(self.data, max_unique=max_unique)
        self._last_stats = result
        self._last_stats_max_unique = max_unique
        return result

    def _get_engine(self) -> QueryEngine:
        """Return the cached QueryEngine, creating it on first use."""
        if self.data is None:
            raise ValueError("No data analyzed yet. Call analyze() first.")
        if self._engine is None:
            self._engine = QueryEngine(
                security=self.security, max_depth=self.config.max_depth
            )
            self._engine.register("data", self.data)
        return self._engine

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Query the analyzed data using SQL."""
        return self._get_engine().query(sql)

    def query_iter(self, sql: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]:
        """
        Query the analyzed data and yield results as dicts.

        Fetches rows in batches for memory efficiency on large result sets.

        Args:
            sql: SQL query string
            batch_size: Number of rows to fetch per batch (default 1000)

        Yields:
            dict for each result row
        """
        return self._get_engine().query_iter(sql, batch_size=batch_size)

    def query_table(
        self,
        sql: str,
        format: str = "grid",
        max_rows: int | None = 20,
        max_colwidth: int | None = 50,
    ) -> str:
        """
        Execute SQL and return a formatted tabular string.

        Args:
            sql: SQL query string
            format: Output format - 'simple', 'grid', 'pipe', 'markdown', 'csv', 'json'
            max_rows: Limit rows shown (None = all, default 20)
            max_colwidth: Max column width (None = unlimited, default 50)

        Returns:
            Formatted string, or an error message prefixed with "ERROR: "
            if the query fails.
        """
        return self._get_engine().format_query(
            sql, format=format, max_rows=max_rows, max_colwidth=max_colwidth
        )

    def _build_tree(self, result: ProfileResult, root_label: str) -> TreeNode:
        """Build TreeNode from ProfileResult using optimized summary_to_tree."""
        summary = result.summary
        sample_store = result.sample_store
        config = self.config

        children: list[TreeNode] = []

        if summary.obj is not None:
            for key in summary.obj.keys():
                children.append(
                    summary_to_tree(
                        key,
                        summary.obj[key],
                        (key,),
                        sample_store,
                        config.max_sample_len,
                        config.samples,
                    )
                )
            if summary.truncated:
                children.append(TreeNode(label="…", children=[]))
        else:
            children.append(
                summary_to_tree(
                    "<value>",
                    summary,
                    ("<value>",),
                    sample_store,
                    config.max_sample_len,
                    config.samples,
                )
            )

        return TreeNode(label=root_label, children=children)

    def profile_result(self) -> ProfileResult | None:
        """Return the raw ProfileResult for programmatic access."""
        return self._last_profile

    def timing(self) -> dict[str, float]:
        """Return timing information from the last analysis."""
        if not self._last_profile:
            return {}
        return {
            "parse_time": self._last_profile.parse_time,
            "analyze_time": self._last_profile.analyze_time,
            "sample_time": self._last_profile.sample_time,
            "total_time": (
                self._last_profile.parse_time
                + self._last_profile.analyze_time
                + self._last_profile.sample_time
            ),
        }

    def close(self) -> None:
        """Close the cached query engine and release resources."""
        if self._engine is not None:
            self._engine.close()
            self._engine = None

    def __repr__(self) -> str:
        if self._last_profile:
            return f"JsonFlux(analyzed=True, source={self._last_profile.source!r})"
        return "JsonFlux(analyzed=False)"

    def __enter__(self) -> JsonFlux:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


# --------------------------
# Validation function
# --------------------------


def validate() -> list[str]:
    """
    Validate profiler output against known test cases.

    Returns:
        Empty list if all checks pass, otherwise a list of error strings.
    """
    # Test case: comprehensive JSON with all types
    test_data = {
        "string_field": "hello",
        "int_field": 42,
        "float_field": 3.14,
        "bool_field": True,
        "null_field": None,
        "empty_object": {},
        "empty_array": [],
        "nested": {"level2": {"level3": {"deep_value": 999}}},
        "array_of_ints": [1, 2, 3],
        "array_of_strings": ["a", "b", "c"],
        "array_of_objects": [
            {"id": 1, "name": "one"},
            {"id": 2, "name": "two"},
        ],
        "mixed_array": [1, "two", 3.0, True, None, {}, []],
        "array_of_arrays": [[1, 2], [3, 4], [5, 6]],
    }

    flux = JsonFlux(max_depth=32, samples=0)
    flux.analyze(test_data)
    result = flux.profile_result()

    if result is None:
        return ["No profile result"]

    summary = result.summary
    errors: list[str] = []

    # Check top-level is object
    if summary.obj is None:
        errors.append("Top-level should be object")
    else:
        # Check expected keys exist
        expected_keys = {
            "string_field",
            "int_field",
            "float_field",
            "bool_field",
            "null_field",
            "empty_object",
            "empty_array",
            "nested",
            "array_of_ints",
            "array_of_strings",
            "array_of_objects",
            "mixed_array",
            "array_of_arrays",
        }
        actual_keys = set(summary.obj.keys())
        missing = expected_keys - actual_keys
        if missing:
            errors.append(f"Missing keys: {missing}")

        # Check primitive types detected correctly
        def check_primitive(key: str, expected_type: str) -> None:
            if key not in summary.obj:
                errors.append(f"Key '{key}' missing")
                return
            s = summary.obj[key]
            if expected_type not in s.primitives:
                errors.append(
                    f"'{key}' should have type '{expected_type}', got {s.primitives}"
                )

        check_primitive("string_field", "str")
        check_primitive("int_field", "int")
        check_primitive("float_field", "float")
        check_primitive("bool_field", "bool")
        check_primitive("null_field", "null")

        # Check nested object depth
        if "nested" in summary.obj:
            nested = summary.obj["nested"]
            if nested.obj is None:
                errors.append("'nested' should be object")
            elif "level2" not in nested.obj:
                errors.append("'nested.level2' missing")
            elif nested.obj["level2"].obj is None:
                errors.append("'nested.level2' should be object")
            elif "level3" not in nested.obj["level2"].obj:
                errors.append("'nested.level2.level3' missing")

        # Check array detection
        if "array_of_ints" in summary.obj:
            arr_sum = summary.obj["array_of_ints"].arr
            if arr_sum is None:
                errors.append("'array_of_ints' should be array")
            elif arr_sum.kind_minmax.get("int", (0, 0))[1] != 3:
                errors.append("'array_of_ints' should have 3 ints")

        # Check mixed array
        if "mixed_array" in summary.obj:
            arr_sum = summary.obj["mixed_array"].arr
            if arr_sum is None:
                errors.append("'mixed_array' should be array")
            else:
                kinds_found = {
                    k for k, (_, mx) in arr_sum.kind_minmax.items() if mx > 0
                }
                expected_kinds = {
                    "int",
                    "str",
                    "float",
                    "bool",
                    "null",
                    "object",
                    "array",
                }
                missing_kinds = expected_kinds - kinds_found
                if missing_kinds:
                    errors.append(f"'mixed_array' missing kinds: {missing_kinds}")

    # Check render doesn't crash
    try:
        for fmt in ["tree", "tabs", "bracket"]:
            output = flux.tree(format=fmt)
            if len(output) < 100:
                errors.append(f"'{fmt}' render output suspiciously short")
    except Exception as e:
        errors.append(f"Render crashed: {e}")

    return errors
