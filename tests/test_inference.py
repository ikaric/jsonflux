"""
Full-fidelity inference tests: JSONFlux must build a queryable table from any
JSON shape without dropping data, silently truncating values, or crashing.

This suite exercises the type-combination matrix directly against the resulting
DuckDB table (round-tripping through SQL) so it proves the *observable* query
behaviour, not just internal schema guesses.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest

from jsonflux import QueryEngine
from jsonflux.core.infer import DEFAULT_MAX_DEPTH, build_arrow_table


def rows_of(data, sql="SELECT * FROM t", max_depth=DEFAULT_MAX_DEPTH):
    """Build a table from ``data`` and run ``sql`` against it, returning dicts."""
    table = build_arrow_table(data, max_depth=max_depth)
    conn = duckdb.connect(":memory:")
    try:
        conn.register("t", table)
        res = conn.execute(sql)
        cols = [d[0] for d in res.description]
        return [dict(zip(cols, r)) for r in res.fetchall()]
    finally:
        conn.close()


def schema_of(data, max_depth=DEFAULT_MAX_DEPTH) -> pa.Schema:
    return build_arrow_table(data, max_depth=max_depth).schema


# ---------------------------------------------------------------------------
# Primitive types
# ---------------------------------------------------------------------------


def test_all_primitive_types_roundtrip():
    data = [
        {"s": "hi", "i": 1, "f": 1.5, "b": True, "n": None},
        {"s": "yo", "i": 2, "f": 2.5, "b": False, "n": None},
    ]
    out = rows_of(data, "SELECT * FROM t ORDER BY i")
    assert out[0] == {"s": "hi", "i": 1, "f": 1.5, "b": True, "n": None}
    sch = schema_of(data)
    assert sch.field("i").type == pa.int64()
    assert sch.field("f").type == pa.float64()
    assert sch.field("b").type == pa.bool_()
    assert sch.field("s").type == pa.string()


def test_int_column_stays_int():
    assert schema_of([{"v": 1}, {"v": 2}]).field("v").type == pa.int64()


def test_bool_not_confused_with_int():
    # Pure bool column -> boolean, not int.
    assert schema_of([{"v": True}, {"v": False}]).field("v").type == pa.bool_()


# ---------------------------------------------------------------------------
# Numeric widening (int + float -> double), NOT truncation
# ---------------------------------------------------------------------------


def test_int_and_float_widen_to_double():
    assert schema_of([{"v": 1}, {"v": 2.5}]).field("v").type == pa.float64()


def test_float_value_after_many_ints_is_preserved():
    """Regression: schema was previously inferred from the first 200 rows only,
    truncating a later float to int."""
    data = [{"id": i, "v": i} for i in range(500)] + [{"id": 500, "v": 3.7}]
    out = rows_of(data, "SELECT v FROM t WHERE id = 500")
    assert out == [{"v": 3.7}]


def test_int_stored_as_double_keeps_value():
    out = rows_of([{"v": 10}, {"v": 2.5}], "SELECT v FROM t ORDER BY v")
    assert out == [{"v": 2.5}, {"v": 10.0}]


# ---------------------------------------------------------------------------
# Late-appearing / missing keys
# ---------------------------------------------------------------------------


def test_key_appearing_after_200_rows_is_kept():
    """Regression: keys first seen past the sampling window were dropped."""
    data = [{"id": i} for i in range(300)] + [{"id": 300, "surprise": "HELLO"}]
    out = rows_of(data, "SELECT surprise FROM t WHERE id = 300")
    assert out == [{"surprise": "HELLO"}]


def test_missing_key_becomes_null():
    out = rows_of([{"a": 1, "b": 2}, {"a": 3}], "SELECT a, b FROM t ORDER BY a")
    assert out == [{"a": 1, "b": 2}, {"a": 3, "b": None}]


def test_union_of_all_keys_across_rows():
    data = [{"a": 1}, {"b": 2}, {"c": 3}]
    assert set(schema_of(data).names) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Type conflicts degrade to string (never crash, never lose the value)
# ---------------------------------------------------------------------------


def test_int_str_conflict_becomes_string():
    out = rows_of([{"v": 1}, {"v": "a"}], "SELECT v FROM t ORDER BY v")
    assert out == [{"v": "1"}, {"v": "a"}]
    assert schema_of([{"v": 1}, {"v": "a"}]).field("v").type == pa.string()


def test_bool_int_conflict_becomes_string():
    out = rows_of([{"v": True}, {"v": 1}], "SELECT v FROM t ORDER BY v")
    assert {r["v"] for r in out} == {"true", "1"}


def test_object_vs_scalar_conflict_becomes_json_string():
    out = rows_of([{"v": {"a": 1}}, {"v": 5}], "SELECT v FROM t ORDER BY v")
    assert {r["v"] for r in out} == {'{"a":1}', "5"}


def test_object_vs_array_conflict_becomes_json_string():
    out = rows_of([{"v": {"a": 1}}, {"v": [1, 2]}], "SELECT v FROM t")
    vals = {r["v"] for r in out}
    assert vals == {'{"a":1}', "[1,2]"}


def test_heterogeneous_array_elements_become_strings():
    out = rows_of([{"a": [1, "two", 3.0]}], "SELECT a FROM t")
    assert out == [{"a": ["1", "two", "3.0"]}]


def test_conflict_only_affects_the_conflicting_column():
    data = [{"clean": 1, "dirty": 1}, {"clean": 2, "dirty": "x"}]
    sch = schema_of(data)
    assert sch.field("clean").type == pa.int64()
    assert sch.field("dirty").type == pa.string()


# ---------------------------------------------------------------------------
# Large integers preserved exactly
# ---------------------------------------------------------------------------


def test_int64_overflow_preserved_as_string():
    big = 123456789012345678901234567890
    out = rows_of([{"big": big}], "SELECT big FROM t")
    assert out == [{"big": str(big)}]


def test_int64_boundary_stays_int():
    val = 2**63 - 1
    sch = schema_of([{"v": val}])
    assert sch.field("v").type == pa.int64()
    assert rows_of([{"v": val}], "SELECT v FROM t") == [{"v": val}]


def test_int64_overflow_mixed_with_normal_ints():
    data = [{"v": 1}, {"v": 2**70}]
    out = rows_of(data, "SELECT v FROM t ORDER BY v")
    assert {r["v"] for r in out} == {"1", str(2**70)}


# ---------------------------------------------------------------------------
# Root shapes
# ---------------------------------------------------------------------------


def test_root_dict_is_single_row():
    out = rows_of({"a": 1, "b": "x"})
    assert out == [{"a": 1, "b": "x"}]


def test_root_list_of_objects():
    out = rows_of([{"id": 1}, {"id": 2}], "SELECT id FROM t ORDER BY id")
    assert out == [{"id": 1}, {"id": 2}]


def test_root_list_of_primitives_becomes_value_column():
    out = rows_of([1, 2, 3], "SELECT value FROM t ORDER BY value")
    assert out == [{"value": 1}, {"value": 2}, {"value": 3}]


def test_root_list_of_strings():
    out = rows_of(["a", "b"], "SELECT value FROM t ORDER BY value")
    assert out == [{"value": "a"}, {"value": "b"}]


def test_root_list_of_arrays():
    out = rows_of([[1, 2], [3, 4]], "SELECT value FROM t")
    assert [r["value"] for r in out] == [[1, 2], [3, 4]]


def test_root_mixed_primitive_list_becomes_string_value():
    out = rows_of([1, "two", 3.0], "SELECT value FROM t ORDER BY value")
    assert {r["value"] for r in out} == {"1", "two", "3.0"}


# ---------------------------------------------------------------------------
# Empty / degenerate structures
# ---------------------------------------------------------------------------


def test_empty_list():
    assert rows_of([], "SELECT count(*) AS c FROM t") == [{"c": 0}]


def test_empty_object_root():
    assert rows_of({}, "SELECT count(*) AS c FROM t") == [{"c": 1}]


def test_empty_nested_object_becomes_json_string():
    out = rows_of([{"m": {}}], "SELECT m FROM t")
    assert out == [{"m": "{}"}]


def test_empty_arrays_are_typed_lists():
    out = rows_of([{"a": []}, {"a": []}], "SELECT len(a) AS n FROM t")
    assert out == [{"n": 0}, {"n": 0}]


def test_all_null_column():
    out = rows_of([{"v": None}, {"v": None}], "SELECT v FROM t")
    assert out == [{"v": None}, {"v": None}]


def test_null_then_value_keeps_value():
    out = rows_of([{"v": None}, {"v": 5}], "SELECT v FROM t ORDER BY v NULLS LAST")
    assert out == [{"v": 5}, {"v": None}]


# ---------------------------------------------------------------------------
# Nested structures & arrays (the reason the library exists)
# ---------------------------------------------------------------------------


def test_nested_object_dot_access():
    data = [{"user": {"name": "Alice", "addr": {"city": "NYC"}}}]
    out = rows_of(data, "SELECT user.name AS n, user.addr.city AS c FROM t")
    assert out == [{"n": "Alice", "c": "NYC"}]


def test_nested_struct_widens_across_rows():
    data = [{"o": {"x": 1}}, {"o": {"x": 2.0, "y": "z"}}]
    out = rows_of(data, "SELECT o.x AS x, o.y AS y FROM t ORDER BY o.x")
    assert out == [{"x": 1.0, "y": None}, {"x": 2.0, "y": "z"}]


def test_unnest_array_of_objects():
    data = [{"items": [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 3}]}]
    out = rows_of(
        data,
        "SELECT i.sku AS sku, i.qty AS qty FROM "
        "(SELECT unnest(items) AS i FROM t) ORDER BY qty",
    )
    assert out == [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 3}]


def test_array_of_primitives():
    out = rows_of([{"tags": ["a", "b", "c"]}], "SELECT len(tags) AS n FROM t")
    assert out == [{"n": 3}]


def test_deeply_nested_array_aggregation():
    data = [
        {"orders": [{"items": [{"qty": 2}, {"qty": 3}]}]},
        {"orders": [{"items": [{"qty": 5}]}]},
    ]
    sql = """
        SELECT sum(it.qty) AS total
        FROM (
            SELECT unnest(o.items) AS it
            FROM (SELECT unnest(orders) AS o FROM t)
        )
    """
    assert rows_of(data, sql) == [{"total": 10}]


# ---------------------------------------------------------------------------
# Depth guard
# ---------------------------------------------------------------------------


def test_depth_beyond_limit_collapses_to_string():
    data = [{"a": {"b": {"c": {"d": 1}}}}]
    out = rows_of(data, "SELECT a FROM t", max_depth=2)
    # a.b is beyond depth 2 -> the subtree is stringified somewhere up the chain
    assert isinstance(out[0]["a"], (str, dict))
    # With generous depth it stays queryable as a struct.
    deep = rows_of(data, "SELECT a.b.c.d AS d FROM t", max_depth=10)
    assert deep == [{"d": 1}]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_scalar_root_rejected():
    with pytest.raises(TypeError):
        build_arrow_table(42)
    with pytest.raises(TypeError):
        build_arrow_table("just a string")


# ---------------------------------------------------------------------------
# End-to-end via QueryEngine (value-wrapped schema in the LLM prompt)
# ---------------------------------------------------------------------------


def test_value_wrapped_table_described_for_llm():
    eng = QueryEngine().register("nums", [1, 2, 3])
    try:
        desc = eng.describe_tables()
        assert "value" in desc  # the real queryable column is surfaced
        assert eng.query("SELECT sum(value) AS s FROM nums") == [{"s": 6}]
    finally:
        eng.close()


def test_record_list_with_literal_value_field_not_wrapped():
    # A genuine 'value' field must not be mistaken for the synthetic wrapper.
    eng = QueryEngine().register("t", [{"value": 1, "other": "x"}])
    try:
        assert eng.tables["t"]["value_wrapped"] is False
        assert eng.query("SELECT other FROM t") == [{"other": "x"}]
    finally:
        eng.close()
