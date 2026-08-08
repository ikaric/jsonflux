"""
Low-memory ingestion for JSON whose root is an array.

Decoding a large JSON document with ``msgspec.json.decode`` materialises the
entire Python object graph at once — for nested payloads that peaks at several
times the file size in RAM (the graph dwarfs both the file bytes and the final
Arrow table).  When the root is an array we avoid that by decoding **one element
at a time** with the standard library's position-tracked decoder
(:meth:`json.JSONDecoder.raw_decode`), folding each element into the Arrow table
and then dropping it.  Only one element (plus the source text and the growing
Arrow table) is ever live.

Element-at-a-time ``raw_decode`` is, perhaps surprisingly, about as fast as a
single bulk ``msgspec`` decode, because the scanning happens in C and no
separate structural pass over the bytes is needed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

__all__ = ["NotAJsonArray", "iter_elements", "looks_like_array"]

# Whitespace is skipped with plain char loops rather than a regex: between
# elements of minified JSON there is at most one comma, so the loop exits on
# its first check, while a regex match costs a call + match-object per skip
# (measured ~1.7x slower on minified input, the common case).
_WS = frozenset(" \t\r\n")
_WS_BYTES = b" \t\r\n"
_OPEN_BRACKET = 0x5B  # [


def _reject_constant(name: str) -> Any:
    # msgspec's bulk decoder treats NaN/Infinity as invalid JSON; without this
    # hook the stdlib decoder would accept them and the same document would
    # parse differently depending on which ingestion path it took.
    raise ValueError(f"{name} is not valid JSON")


_raw_decode = json.JSONDecoder(parse_constant=_reject_constant).raw_decode


class NotAJsonArray(Exception):
    """Raised when the text is not a JSON document whose root is ``[…]``."""


def looks_like_array(raw: bytes | str) -> bool:
    """Cheap check: is the first non-whitespace character an opening bracket?

    Scans forward instead of ``lstrip()``-ing, which would copy the whole
    buffer just to inspect one character.
    """
    if isinstance(raw, bytes):
        ws: Any = _WS_BYTES
        bracket: Any = _OPEN_BRACKET
    else:
        ws = _WS
        bracket = "["
    i = 0
    n = len(raw)
    while i < n and raw[i] in ws:
        i += 1
    return i < n and raw[i] == bracket


def first_nonws_char(s: str) -> str:
    """First non-whitespace character of ``s`` (empty string if none).

    Used to sniff "JSON text or file path?" without the full-buffer copy a
    ``strip()`` would make on a multi-megabyte JSON string.
    """
    for ch in s:
        if ch not in _WS:
            return ch
    return ""


def _require_end(text: str, i: int) -> None:
    """
    Reject trailing non-whitespace after the closing bracket.  The bulk
    decoder treats trailing content as malformed JSON, so the streaming path
    must too -- silently ignoring it would mean the same file parses
    differently depending on its size.
    """
    n = len(text)
    while i < n and text[i] in _WS:
        i += 1
    if i < n:
        raise ValueError(f"trailing data after JSON array at position {i}")


def iter_elements(text: str) -> Iterator[Any]:
    """
    Yield each top-level element of the JSON array in ``text``, decoding one
    element at a time so the whole graph is never resident.

    Raises:
        NotAJsonArray: if the root is not an array.
        ValueError: on malformed structure between elements, trailing data
            after the array, or non-JSON constants (``NaN``/``Infinity``).
    """
    n = len(text)
    i = 0
    while i < n and text[i] in _WS:
        i += 1
    if i >= n or text[i] != "[":
        raise NotAJsonArray("root is not a JSON array")
    i += 1
    while i < n and text[i] in _WS:
        i += 1
    if i < n and text[i] == "]":
        _require_end(text, i + 1)
        return  # empty array

    raw_decode = _raw_decode
    while True:
        obj, i = raw_decode(text, i)
        yield obj
        while i < n and text[i] in _WS:
            i += 1
        if i >= n:
            raise ValueError("unterminated JSON array")
        c = text[i]
        if c == "]":
            _require_end(text, i + 1)
            return
        if c != ",":
            raise ValueError(f"expected ',' or ']' at position {i}, found {c!r}")
        i += 1
        while i < n and text[i] in _WS:
            i += 1
