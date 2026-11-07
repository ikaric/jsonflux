"""LLM-facing schema fidelity: what generate_prompt()/describe_tables() show a model.

Each test pins a failure mode observed when small models wrote SQL from the
generated prompt (see PR description): missing samples on nullable fields,
guessed category values, reserved-word keys, 0-based indexing, date strings.
"""

from __future__ import annotations

import re

import duckdb
import pytest

from jsonflux.query.engine import QueryEngine
from jsonflux.utils.sql import RESERVED_KEYWORDS, needs_quoting, quote_ident


def _rows(n: int = 40) -> list[dict]:
    return [
        {
            "id": i,
            "temp": None if i % 5 == 0 else 20.5 + i,
            "station": "X",
            "cond": ["rain", "sun", "rain", "fog"][i % 4],
            "name": f"user-{i}",
            "date": f"2025-06-{i % 28 + 1:02d}",
            "show": {"title": ["A", "B"][i % 2]},
            "end": {"station": "Bascarsija"},
            "first-name": "Ana",
            "coords": [1.0, 2.0, float(i)],
            "tags": ["x", "y"][: i % 3],
        }
        for i in range(n)
    ]


@pytest.fixture
def engine():
    eng = QueryEngine()
    eng.register("t", _rows())
    yield eng
    eng.close()


def _field_line(schema: str, key: str) -> str:
    """Top-level field line (two-space indent inside the root ``[{``)."""
    for line in schema.splitlines():
        if line.startswith(f"  {key}:"):
            return line.strip()
    raise AssertionError(f"{key} not in schema:\n{schema}")


def test_nullable_field_keeps_samples(engine):
    line = _field_line(engine.describe_tables(), "temp")
    assert line.startswith("temp: float? samples=[")
    assert "null" not in line  # nulls are not examples


def test_samples_are_deduplicated(engine):
    line = _field_line(engine.describe_tables(), "station")
    # single-valued field: one sample, not ["X", "X", "X"]
    assert line == 'station: str samples=["X"]'


def test_categorical_field_lists_all_values(engine):
    line = _field_line(engine.describe_tables(), "cond")
    assert line == 'cond: str one of ["fog", "rain", "sun"]'


def test_high_cardinality_field_is_not_an_enum(engine):
    line = _field_line(engine.describe_tables(), "name")
    assert "one of" not in line and "samples=[" in line


def test_enum_can_be_disabled(engine):
    line = _field_line(engine.describe_tables(enum_max=0), "cond")
    assert "one of" not in line and "samples=[" in line


def test_enum_from_sampled_rows_is_marked_partial():
    import random

    rng = random.Random(0)
    eng = QueryEngine(sample_scan_limit=50)
    eng.register("t", [{"cond": rng.choice(["rain", "sun", "fog"])} for _ in range(2000)])
    line = _field_line(eng.describe_tables(), "cond")
    eng.close()
    assert line.startswith("cond: str e.g. one of [")


def test_no_samples_means_no_enum(engine):
    assert "one of" not in engine.describe_tables(samples=0)


def test_reserved_and_special_keys_are_quoted(engine):
    schema = engine.describe_tables()
    assert '"show": ' in schema
    assert '"end": ' in schema
    assert '"first-name": ' in schema
    assert "\n  id: " in schema  # plain keys stay bare


def test_iso_dates_are_tagged(engine):
    line = _field_line(engine.describe_tables(), "date")
    assert line.startswith("date: str (ISO date) samples=[")
    assert "(ISO date)" not in _field_line(engine.describe_tables(), "name")


def test_prompt_explains_new_notation(engine):
    prompt = engine.generate_prompt()
    assert "`one of [...]` = every value" in prompt
    assert "`str (ISO date)`" in prompt and "CAST(col AS DATE)" in prompt
    assert "must be double-quoted in SQL" in prompt


def test_prompt_rules_absent_when_not_needed():
    eng = QueryEngine()
    eng.register("p", [{"id": i, "score": i * 1.5} for i in range(10)])
    prompt = eng.generate_prompt()
    eng.close()
    assert "one of [...]" not in prompt
    assert "ISO date" not in prompt
    assert "double-quoted" not in prompt


def test_prompt_teaches_one_based_indexing(engine):
    prompt = engine.generate_prompt()
    assert "1-based" in prompt
    assert "use UNNEST instead" not in prompt
    # and the rule is true:
    assert engine.query("SELECT coords[1] AS a, coords[0] AS z FROM t LIMIT 1") == [
        {"a": 1.0, "z": None}
    ]


@pytest.mark.parametrize(
    "rows",
    [
        _rows(),
        # reserved/special names in every position the examples draw from
        [{"order": i, "group": f"g{i % 3}", "end": {"from": i}, "select": ["a", "b"]}
         for i in range(10)],
        [{"user-id": i, "e-mail": f"u{i}@x", "items": [{"unit-price": 1.5}]} for i in range(10)],
    ],
)
def test_every_example_query_in_prompt_executes(rows):
    eng = QueryEngine()
    eng.register("t", rows)
    prompt = eng.generate_prompt()
    blocks = re.findall(r"```sql\n(.*?)```", prompt, re.S)
    assert blocks
    for sql in blocks:
        if "<key>" in sql:  # placeholder join template, not runnable by design
            continue
        eng.query(sql)  # raises on any parser/binder error
    eng.close()


def test_quoted_schema_path_works_in_sql(engine):
    assert engine.query('SELECT "show".title FROM t LIMIT 1')
    assert engine.query('SELECT "first-name" FROM t LIMIT 1')
    with pytest.raises(duckdb.Error):
        engine.query("SELECT show.title FROM t LIMIT 1")


def test_reserved_keywords_match_installed_duckdb():
    live = {k for (k,) in duckdb.sql(
        "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'"
    ).fetchall()}
    assert RESERVED_KEYWORDS == live


def test_quote_ident():
    assert quote_ident("price") == "price"
    assert quote_ident("end") == '"end"'
    assert quote_ident("ORDER") == '"ORDER"'
    assert quote_ident("first-name") == '"first-name"'
    assert quote_ident('we"ird') == '"we""ird"'
    assert not needs_quoting("_private1")
