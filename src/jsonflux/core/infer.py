"""
Full-fidelity JSON -> Arrow table construction.

Unlike the sampling-based :mod:`jsonflux.core.analyzer` (which is optimised for
*displaying* a structural summary to humans and LLMs), this module builds the
**queryable** Arrow table and therefore must be lossless: every row and every
field is scanned so the inferred schema is a true union of everything present.

Design goals
------------
* **No silent data loss.** A key that first appears on row 10,000 still becomes
  a column; a value that is an ``int`` on most rows but a ``float`` on one row
  is widened to ``double`` instead of being truncated.
* **No crashes on messy JSON.** Genuine type conflicts (``int`` mixed with
  ``str``, object mixed with scalar, object mixed with array) are resolved to a
  string column rather than raising.  Integers that overflow ``int64`` are
  preserved exactly as strings.  Root arrays of primitives, empty arrays and
  empty objects are all handled.
* **Fast common path.** When the data has no type conflicts (the overwhelmingly
  common case for real API payloads) the rows are handed to Arrow untouched --
  no per-row Python normalisation.  Coercion runs only for the specific
  subtrees that actually need it.
"""

from __future__ import annotations

from typing import Any

import msgspec
import pyarrow as pa

from .streaming import iter_elements

__all__ = [
    "build_arrow_table",
    "build_arrow_table_streaming",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_CHUNK_SIZE",
]

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

# How deep to model structure before collapsing a subtree to a JSON string.
# Real-world API payloads are rarely deeper than a handful of levels; this bound
# keeps inference recursion safe and predictable.
DEFAULT_MAX_DEPTH = 64

# Elements decoded per chunk in the streaming ingestion path.  Bounds the number
# of Python objects live at once; a whole chunk is decoded in one msgspec call so
# per-element overhead stays amortised.
DEFAULT_CHUNK_SIZE = 2048

_json_encode = msgspec.json.Encoder().encode


def _encode_json(value: Any) -> str:
    return _json_encode(value).decode("utf-8")


# --------------------------------------------------------------------------
# Type accumulation (single pass over all rows)
# --------------------------------------------------------------------------


class _Node:
    """Mutable accumulator for every value observed at one structural path."""

    __slots__ = ("kinds", "fields", "items", "int_overflow", "deep")

    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.fields: dict[str, _Node] = {}
        self.items: _Node | None = None
        self.int_overflow: bool = False
        self.deep: bool = False


def _accumulate(node: _Node, value: Any, depth: int) -> None:
    """Fold ``value`` into ``node`` (recursive, bounded by ``depth``)."""
    kinds = node.kinds
    t = type(value)

    if value is None:
        kinds.add("null")
    elif t is bool:
        kinds.add("bool")
    elif t is int:
        kinds.add("int")
        if value < INT64_MIN or value > INT64_MAX:
            node.int_overflow = True
    elif t is float:
        kinds.add("float")
    elif t is str:
        kinds.add("str")
    elif t is dict:
        kinds.add("object")
        if depth <= 0:
            node.deep = True
            return
        fields = node.fields
        for k, v in value.items():
            key = k if type(k) is str else str(k)
            child = fields.get(key)
            if child is None:
                child = _Node()
                fields[key] = child
            _accumulate(child, v, depth - 1)
    elif t is list:
        kinds.add("array")
        if depth <= 0:
            node.deep = True
            return
        item = node.items
        if item is None:
            item = _Node()
            node.items = item
        for el in value:
            _accumulate(item, el, depth - 1)
    else:
        # Anything msgspec can hand us that we do not model (e.g. datetime from a
        # non-JSON source) is treated as a string.
        kinds.add("str")


# --------------------------------------------------------------------------
# Resolution: _Node -> coercion plan (Arrow type + how to transform values)
# --------------------------------------------------------------------------


# Plan kinds:
#   "scalar"        -> value passes straight through to Arrow (fast path)
#   "string_coerce" -> value must be stringified before Arrow sees it
#   "struct"        -> recurse into `fields`
#   "list"          -> recurse into `item`
class _Plan:
    __slots__ = ("dtype", "dirty", "kind", "fields", "item")

    def __init__(
        self,
        dtype: pa.DataType,
        dirty: bool,
        kind: str,
        fields: dict[str, _Plan] | None = None,
        item: _Plan | None = None,
    ) -> None:
        self.dtype = dtype
        self.dirty = dirty
        self.kind = kind
        self.fields = fields
        self.item = item


def _string_plan(dirty: bool) -> _Plan:
    return _Plan(pa.string(), dirty, "string_coerce" if dirty else "scalar")


def _resolve(node: _Node) -> _Plan:
    """Resolve an accumulated node into a concrete Arrow type + coercion plan."""
    kinds = node.kinds - {"null"}

    has_obj = "object" in kinds
    has_arr = "array" in kinds
    has_str = "str" in kinds
    has_bool = "bool" in kinds
    has_int = "int" in kinds
    has_float = "float" in kinds
    numeric = has_int or has_float

    # Count incompatible "families".  int+float unify to double, but anything
    # else mixed together degrades to a string column.
    families = 0
    families += 1 if numeric else 0
    families += 1 if has_bool else 0
    families += 1 if has_str else 0
    families += 1 if has_obj else 0
    families += 1 if has_arr else 0

    # A subtree collapsed for depth is always stringified.
    if node.deep:
        return _string_plan(True)

    if families == 0:
        # Only nulls ever seen (or empty).  A string column of nulls is a safe,
        # queryable placeholder; raw None values pass straight through.
        return _string_plan(False)

    if families > 1:
        # Genuine conflict -> stringify.  Values are non-uniform, so coercion is
        # required.
        return _string_plan(True)

    # --- single family ---
    if numeric:
        if has_float:
            # int values (if any) are cast to double by Arrow automatically.
            return _Plan(pa.float64(), False, "scalar")
        if node.int_overflow:
            # Preserve exact value; int128/decimal cannot always hold it.
            return _string_plan(True)
        return _Plan(pa.int64(), False, "scalar")

    if has_bool:
        return _Plan(pa.bool_(), False, "scalar")

    if has_str:
        return _Plan(pa.string(), False, "scalar")

    if has_obj:
        fields = node.fields
        if not fields:
            # DuckDB/Arrow cannot represent a zero-field struct; stringify the
            # object (e.g. ``{}``) so it stays queryable as text.
            return _string_plan(True)
        field_plans: dict[str, _Plan] = {}
        arrow_fields: list[pa.Field] = []
        dirty = False
        for key in sorted(fields):
            child_plan = _resolve(fields[key])
            field_plans[key] = child_plan
            arrow_fields.append(pa.field(key, child_plan.dtype, nullable=True))
            dirty = dirty or child_plan.dirty
        return _Plan(pa.struct(arrow_fields), dirty, "struct", fields=field_plans)

    if has_arr:
        item = node.items
        if item is None:
            # Only ever saw empty arrays -> list<string> is a harmless default.
            return _Plan(pa.list_(pa.string()), False, "list", item=_string_plan(False))
        item_plan = _resolve(item)
        return _Plan(
            pa.list_(pa.field("item", item_plan.dtype, nullable=True)),
            item_plan.dirty,
            "list",
            item=item_plan,
        )

    return _string_plan(False)


# --------------------------------------------------------------------------
# Coercion (only walked for subtrees whose plan is dirty)
# --------------------------------------------------------------------------


def _coerce(value: Any, plan: _Plan) -> Any:
    if value is None:
        return None

    kind = plan.kind

    if kind == "scalar":
        return value

    if kind == "string_coerce":
        t = type(value)
        if t is str:
            return value
        if t is dict or t is list:
            return _encode_json(value)
        if t is bool:
            return "true" if value else "false"
        return str(value)

    if kind == "struct":
        if type(value) is not dict:
            # Schema says struct but this row has a scalar/list here.  This only
            # happens when the field is *not* a conflict (otherwise the plan
            # would be string_coerce), i.e. a genuinely unexpected shape; drop
            # to null rather than corrupt the column.
            return None
        fields = plan.fields
        out: dict[str, Any] = {}
        for key, child_plan in fields.items():  # type: ignore[union-attr]
            v = value.get(key)
            out[key] = _coerce(v, child_plan) if child_plan.dirty else v
        return out

    if kind == "list":
        if type(value) is not list:
            return None
        item_plan = plan.item
        if item_plan is not None and item_plan.dirty:
            return [_coerce(v, item_plan) for v in value]
        return value

    return value


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def build_arrow_table(data: Any, max_depth: int = DEFAULT_MAX_DEPTH) -> pa.Table:
    """
    Build a lossless Arrow table from decoded JSON ``data``.

    Args:
        data: A ``dict`` (single record -> one-row table) or ``list`` (record
            per element).  Lists of non-objects become a single ``value``
            column.
        max_depth: Structural depth to model before collapsing deeper subtrees
            to JSON strings.

    Returns:
        A :class:`pyarrow.Table` whose schema is the full union of every value
        observed in ``data``.

    Raises:
        TypeError: if ``data`` is neither a ``dict`` nor a ``list``.
    """
    if isinstance(data, dict):
        return _build_from_record(data, max_depth)
    if isinstance(data, list):
        return _build_from_list(data, max_depth)
    raise TypeError(
        f"Cannot build a table from {type(data).__name__}; "
        "expected a JSON object or array."
    )


def _struct_plan_to_schema(plan: _Plan) -> pa.Schema:
    return pa.schema(list(plan.dtype))


def _list_schema(root_items: _Node) -> tuple[_Plan, pa.Schema, str]:
    """
    Resolve a list's element node into ``(plan, arrow schema, mode)``.

    ``mode`` selects how each element becomes an Arrow row:
    ``record_fast`` (elements are all dicts, no coercion — passed straight
    through), ``record_nullsafe`` (dicts plus ``null`` elements),
    ``record_coerce`` (dicts needing string coercion), ``value_fast`` /
    ``value_coerce`` (non-object roots wrapped in a synthetic ``value`` column).
    """
    kinds = root_items.kinds - {"null"}
    has_null_elem = "null" in root_items.kinds
    is_record_list = (
        kinds == {"object"} and bool(root_items.fields) and not root_items.deep
    )
    plan = _resolve(root_items)
    if is_record_list:
        schema = _struct_plan_to_schema(plan)
        if plan.dirty:
            mode = "record_coerce"
        elif has_null_elem:
            mode = "record_nullsafe"
        else:
            mode = "record_fast"
    else:
        # Heterogeneous / primitive / array root -> single "value" column.
        schema = pa.schema([pa.field("value", plan.dtype, nullable=True)])
        mode = "value_coerce" if plan.dirty else "value_fast"
    return plan, schema, mode


def _chunk_to_rows(chunk: list, plan: _Plan, mode: str) -> list:
    """Turn decoded elements into Arrow-ready row dicts for the given mode.

    A ``null`` element in an otherwise-object array becomes an all-null row
    (``{}``); Arrow's ``from_pylist`` cannot take a bare ``None`` for a struct.
    """
    if mode == "record_fast":
        return chunk
    if mode == "record_nullsafe":
        return [r if type(r) is dict else {} for r in chunk]
    if mode == "record_coerce":
        return [_coerce(r, plan) if type(r) is dict else {} for r in chunk]
    if mode == "value_fast":
        return [{"value": el} for el in chunk]
    return [{"value": _coerce(el, plan)} for el in chunk]


def _build_from_record(record: dict, max_depth: int) -> pa.Table:
    root = _Node()
    _accumulate(root, record, max_depth)
    plan = _resolve(root)

    if plan.kind != "struct":
        # Empty object or otherwise non-struct root -> single stringified column.
        schema = pa.schema([pa.field("value", pa.string(), nullable=True)])
        cell = _coerce(record, plan) if plan.dirty else record
        return pa.Table.from_pylist([{"value": cell}], schema=schema)

    schema = _struct_plan_to_schema(plan)
    row = _coerce(record, plan) if plan.dirty else record
    return pa.Table.from_pylist([row], schema=schema)


def _build_from_list(data: list, max_depth: int) -> pa.Table:
    root_items = _Node()
    for el in data:
        _accumulate(root_items, el, max_depth)
    plan, schema, mode = _list_schema(root_items)
    rows = _chunk_to_rows(data, plan, mode)
    return pa.Table.from_pylist(rows, schema=schema)


def build_arrow_table_streaming(
    raw: bytes,
    max_depth: int = DEFAULT_MAX_DEPTH,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    sample_limit: int = 1000,
) -> tuple[pa.Table, list]:
    """
    Build a lossless Arrow table from the raw bytes of a **JSON array** without
    ever holding the whole decoded object graph in memory.

    Two passes over the source (see :mod:`jsonflux.core.streaming`), each
    decoding one element at a time and dropping it:

    1. fold every element into the type model, keeping the first
       ``sample_limit`` elements aside for the display schema/examples;
    2. build the Arrow table one ``chunk_size``-element ``RecordBatch`` at a
       time.

    Peak memory is therefore ``source text + one chunk + final Arrow table``
    rather than ``full Python graph + Arrow table``.

    Args:
        raw: JSON bytes whose root is an array (caller guarantees this).
        max_depth: structural depth before collapsing to JSON strings.
        chunk_size: elements accumulated per Arrow ``RecordBatch``.
        sample_limit: how many leading elements to retain for the display schema.

    Returns:
        ``(table, sample_elements)`` — the sample list feeds the existing
        sampled display-schema pipeline so ingestion memory drops without
        changing what the LLM sees.
    """
    keep = sample_limit if sample_limit and sample_limit > 0 else 0
    text = raw.decode("utf-8")

    # Pass 1: type model + a bounded head sample.
    root_items = _Node()
    sample_elems: list = []
    for el in iter_elements(text):
        _accumulate(root_items, el, max_depth)
        if len(sample_elems) < keep:
            sample_elems.append(el)

    plan, schema, mode = _list_schema(root_items)

    # Pass 2: build Arrow one chunk at a time, dropping each chunk as we go.
    batches: list[pa.RecordBatch] = []
    buf: list = []
    for el in iter_elements(text):
        buf.append(el)
        if len(buf) >= chunk_size:
            batches.append(
                pa.RecordBatch.from_pylist(
                    _chunk_to_rows(buf, plan, mode), schema=schema
                )
            )
            buf = []
    if buf:
        batches.append(
            pa.RecordBatch.from_pylist(_chunk_to_rows(buf, plan, mode), schema=schema)
        )

    if batches:
        table = pa.Table.from_batches(batches, schema)
    else:
        table = pa.Table.from_pylist([], schema=schema)
    return table, sample_elems
