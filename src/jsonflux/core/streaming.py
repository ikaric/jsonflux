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

_WS = frozenset(" \t\r\n")
_OPEN_BRACKET = 0x5B  # [
_raw_decode = json.JSONDecoder().raw_decode


class NotAJsonArray(Exception):
    """Raised when the text is not a JSON document whose root is ``[…]``."""


def looks_like_array(raw: bytes) -> bool:
    """Cheap check: is the first non-whitespace byte an opening bracket?"""
    stripped = raw.lstrip()
    return bool(stripped) and stripped[0] == _OPEN_BRACKET


def iter_elements(text: str) -> Iterator[Any]:
    """
    Yield each top-level element of the JSON array in ``text``, decoding one
    element at a time so the whole graph is never resident.

    Raises:
        NotAJsonArray: if the root is not an array.
        ValueError: on malformed structure between elements.
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
            return
        if c != ",":
            raise ValueError(f"expected ',' or ']' at position {i}, found {c!r}")
        i += 1
        while i < n and text[i] in _WS:
            i += 1
