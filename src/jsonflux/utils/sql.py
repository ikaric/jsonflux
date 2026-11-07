"""SQL identifier helpers shared by schema rendering and prompt generation."""

from __future__ import annotations

import re

# DuckDB reserved keywords (``SELECT keyword_name FROM duckdb_keywords()
# WHERE keyword_category = 'reserved'``).  A JSON key with one of these names
# must be double-quoted in SQL: ``"end".station`` works, ``end.station`` is a
# parser error.  Kept static so rendering never needs a connection; a test
# checks it against the installed DuckDB.
RESERVED_KEYWORDS = frozenset({
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "asymmetric", "both",
    "case", "cast", "check", "collate", "column", "constraint", "create", "default",
    "deferrable", "desc", "describe", "distinct", "do", "else", "end", "except", "false",
    "fetch", "for", "foreign", "from", "group", "having", "in", "initially", "intersect",
    "into", "lambda", "lateral", "leading", "limit", "not", "null", "offset", "on", "only",
    "or", "order", "pivot", "pivot_longer", "pivot_wider", "placing", "primary", "qualify",
    "references", "returning", "select", "show", "some", "summarize", "symmetric", "table",
    "then", "to", "trailing", "true", "union", "unique", "unpivot", "using", "variadic",
    "when", "where", "window", "with",
})

_PLAIN_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def needs_quoting(name: str) -> bool:
    """True if ``name`` cannot be used as a bare identifier in DuckDB SQL."""
    return not _PLAIN_IDENT.match(name) or name.lower() in RESERVED_KEYWORDS


def quote_ident(name: str) -> str:
    """Double-quote ``name`` only when DuckDB requires it."""
    if not needs_quoting(name):
        return name
    return '"' + name.replace('"', '""') + '"'


# ISO-8601 date / datetime strings, as commonly emitted by JSON APIs.
ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
