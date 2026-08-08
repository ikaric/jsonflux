"""
Streaming ingestion tests.

Large file / JSON-string array sources are decoded one element at a time to keep
peak memory low.  These tests force that path (``stream_min_bytes=0``) and prove
it is behaviourally identical to the in-memory bulk path, plus cover the
low-level element iterator and the streaming table builder directly.
"""

from __future__ import annotations

import random
import string

import msgspec
import pytest

from jsonflux import QueryEngine
from jsonflux.core.infer import build_arrow_table, build_arrow_table_streaming
from jsonflux.core.streaming import NotAJsonArray, iter_elements, looks_like_array

# ---------------------------------------------------------------------------
# iter_elements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        [],
        [1],
        [1, 2, 3],
        ["a", "b"],
        [True, False, None],
        [{"a": 1}, {"b": 2}],
        [[1, 2], [3, 4]],
        [1, "two", 3.0, True, None],
        [{"s": 'has "quotes" and \\ backslash, commas [and] brackets {}'}],
        [{"unicode": "café ☕ 日本語 🎉"}],
        [{"nested": {"deep": [1, {"x": 2}]}}],
    ],
)
def test_iter_elements_matches_full_decode(data):
    text = msgspec.json.encode(data).decode("utf-8")
    assert list(iter_elements(text)) == data


def test_iter_elements_rejects_non_array():
    for bad in ('{"a": 1}', "42", '"str"', "true"):
        with pytest.raises(NotAJsonArray):
            list(iter_elements(bad))


def test_iter_elements_malformed_raises():
    with pytest.raises(ValueError):
        list(iter_elements("[1, 2"))  # unterminated


def test_looks_like_array():
    assert looks_like_array(b"  [1,2,3]")
    assert looks_like_array(b'[\n  {"a":1}\n]')
    assert not looks_like_array(b'{"a": 1}')
    assert not looks_like_array(b"  42")
    assert not looks_like_array(b"")


# ---------------------------------------------------------------------------
# Streaming table builder == in-memory builder (fuzzed)
# ---------------------------------------------------------------------------


def _equal_tables(data, chunk_sizes=(1, 2, 7, 1000)):
    ref = build_arrow_table(data)
    raw = msgspec.json.encode(data)
    for cs in chunk_sizes:
        tbl, _ = build_arrow_table_streaming(raw, chunk_size=cs)
        if not tbl.equals(ref, check_metadata=False):
            return False
    return True


@pytest.mark.parametrize(
    "data",
    [
        [{"id": i, "name": f"n{i}", "amt": i * 1.5} for i in range(40)],
        [{"id": i} for i in range(30)] + [{"id": 30, "late": "x"}],
        [{"v": 1}, {"v": 2.5}, {"v": 3}],
        [{"v": 1}, {"v": "a"}],
        [{"v": {"a": 1}}, {"v": 5}],
        [{"big": 123456789012345678901234567890}],
        [{"items": [{"sku": "A", "q": 1}, {"sku": "B", "q": 2}]} for _ in range(10)],
        [1, 2, 3],
        ["a", "b", "c"],
        [[1, 2], [3, 4]],
        [1, "two", 3.0, True, None],
        [],
        [{"v": None}, {"v": 5}],
        [None, {"a": 1}, None, {"a": 2}],  # null elements in a record list
        [{"m": {}}],
        [{"a": [1, "two", 3.0]}],
        [{"s": "café ☕", "t": 'a"b\\c'}, {"s": "日本"}],
    ],
)
def test_streaming_equals_in_memory(data):
    assert _equal_tables(data)


def test_streaming_equivalence_fuzz():
    rng = random.Random(1234)

    def rv(depth=0):
        if depth > 3:
            return rng.choice([1, "x", True, None])
        t = rng.random()
        if t < 0.3:
            return "".join(
                rng.choice(string.printable + '☕,[]{}"\\')
                for _ in range(rng.randint(0, 12))
            )
        if t < 0.5:
            return rng.randint(-(10**12), 10**12)
        if t < 0.7:
            return rng.choice([True, False, None, 1.5])
        if t < 0.85:
            return [rv(depth + 1) for _ in range(rng.randint(0, 4))]
        return {
            f"k{rng.randint(0, 4)}": rv(depth + 1) for _ in range(rng.randint(0, 4))
        }

    for _ in range(200):
        data = [rv() for _ in range(rng.randint(0, 25))]
        assert _equal_tables(data, chunk_sizes=(1, 3, 50))


# ---------------------------------------------------------------------------
# End-to-end through QueryEngine (streaming forced on)
# ---------------------------------------------------------------------------


@pytest.fixture
def records():
    r = random.Random(7)
    return [
        {
            "id": i,
            "region": r.choice(["us", "eu", "apac"]),
            "amount": round(r.uniform(1, 100), 2),
            "items": [{"sku": f"S{j}", "qty": j + 1} for j in range(i % 3)],
        }
        for i in range(500)
    ]


def test_streaming_query_matches_bulk_via_string(records):
    raw = msgspec.json.encode(records).decode("utf-8")
    sql = "SELECT region, count(*) c, round(sum(amount),2) s FROM t GROUP BY region ORDER BY region"

    streamed = QueryEngine(stream_min_bytes=0).register("t", raw)
    bulk = QueryEngine(stream_min_bytes=10**12).register("t", records)
    try:
        assert streamed.query(sql) == bulk.query(sql)
        # nested unnest still works on the streamed table
        assert streamed.query(
            "SELECT sum(it.qty) q FROM (SELECT unnest(items) it FROM t)"
        ) == bulk.query("SELECT sum(it.qty) q FROM (SELECT unnest(items) it FROM t)")
    finally:
        streamed.close()
        bulk.close()


def test_streaming_from_file(tmp_path, records):
    path = tmp_path / "data.json"
    path.write_bytes(msgspec.json.encode(records))
    eng = QueryEngine(stream_min_bytes=0).register("t", str(path))
    try:
        assert eng.query("SELECT count(*) c FROM t")[0]["c"] == 500
        assert eng.tables["t"]["row_count"] == 500
        # schema/prompt still generated from the streamed sample
        assert "region" in eng.describe_tables()
    finally:
        eng.close()


def test_threshold_selects_path(records):
    raw = msgspec.json.encode(records)
    # Below threshold -> bulk path; above -> streaming path.  Both must yield
    # the same queryable table.
    big = QueryEngine(stream_min_bytes=0).register("t", raw.decode("utf-8"))
    small = QueryEngine(stream_min_bytes=len(raw) + 1).register(
        "t", raw.decode("utf-8")
    )
    try:
        assert big.query("SELECT count(*) c FROM t") == small.query(
            "SELECT count(*) c FROM t"
        )
        assert big.tables["t"]["columns"] == small.tables["t"]["columns"]
    finally:
        big.close()
        small.close()


def test_streaming_value_wrapped_primitive_array():
    # A large-ish primitive array streamed still exposes the `value` column.
    raw = msgspec.json.encode(list(range(1000))).decode("utf-8")
    eng = QueryEngine(stream_min_bytes=0).register("nums", raw)
    try:
        assert eng.query("SELECT sum(value) s FROM nums")[0]["s"] == sum(range(1000))
    finally:
        eng.close()
