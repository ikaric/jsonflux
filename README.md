<div align="center">

# 📊 JSONFlux

**Let a small model filter a big API response — without pasting it into the context window or running generated code**

[![PyPI](https://img.shields.io/pypi/v/jsonflux?color=306998&logo=pypi&logoColor=white)](https://pypi.org/project/jsonflux/)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Platforms](https://img.shields.io/badge/Platforms-Linux%20%7C%20macOS%20%7C%20Windows-4c1)](https://pypi.org/project/jsonflux/#files)
[![Tests](https://github.com/ikaric/jsonflux/actions/workflows/tests.yml/badge.svg)](https://github.com/ikaric/jsonflux/actions/workflows/tests.yml)
[![DuckDB](https://img.shields.io/badge/DuckDB-SQL%20Engine-FFF000?logo=duckdb&logoColor=black)](https://duckdb.org)
[![msgspec](https://img.shields.io/badge/msgspec-Fast%20JSON-5B4FC3)](https://jcristharif.com/msgspec/)
[![PyArrow](https://img.shields.io/badge/PyArrow-Zero%20Copy-E34F26)](https://arrow.apache.org/docs/python/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*Turn a JSON payload into a compact schema a model can read, and a sandbox its SQL can't escape.*

[Why This Exists](#-why-this-exists) •
[Quick Start](#-quick-start) •
[Structure Analysis](#-structure-analysis) •
[SQL Queries](#-sql-queries) •
[LLM Integration](#-llm-integration) •
[Configuration](#%EF%B8%8F-configuration)

</div>

---

## 🎯 Why This Exists

You call an API. It returns 7 MB of nested JSON. You need the model to pull three rows out of it.

The usual options are both bad:

1. **Paste the payload into the context window.** It may not fit, you pay for every token, and a small model's accuracy degrades sharply as you bury the answer in noise.
2. **Have the model write and execute filtering code.** Now you are running generated Python against your machine, and you own every consequence of that.

JSONFlux is the third option. It reads the payload once and hands the model a **schema instead of the data** — table names, field paths, types, nullability, and a few real sample values, neatly formatted and small enough to sit in any context window. The model writes SQL against that schema. The SQL runs in a DuckDB connection that is locked down before it ever sees a query: no filesystem, no network, no extensions, no writes.

> The USGS earthquake feed used in the tests below is **7.3 MB / 10,741 records**. `generate_prompt()` describes it in **~3,400 characters (roughly 900 tokens)** — about 0.05% of the raw payload, with every field name and type the model needs to query it correctly.

**This is built for small, cheap, local models.** The schema is deliberately flat and explicitly typed because that is what a weak model needs to produce correct SQL — not because a frontier model couldn't infer it. Structure is presented once, plainly, so the model spends its capacity on the query rather than on guessing the shape of your data.

### You don't write the system prompt — `generate_prompt()` does

Register your JSON, and the whole system prompt is generated for you: the DuckDB dialect rules, the schema notation, and worked query patterns **written against your actual registered tables**. The examples name your table and your fields, so the model is copying a working query rather than translating a generic one.

```python
engine = QueryEngine()
engine.register("quakes", "feed.json", path="$.features")

system_prompt = engine.generate_prompt()   # ready to send, no hand-writing
```

Excerpt of what comes out for that table:

````text
You are a DuckDB SQL query generator. Convert natural language data
requests into SQL queries.

RULES:
- Return ONLY the raw SQL query text.
- No explanations, no markdown fences, no code blocks, no comments.

## Schema Notation
- `field: str` = string, `int` = integer, `float` = number
- `field: str?` = nullable (may be null)
- Nested objects use dot notation: `quakes.properties.tsunami`

## Query Patterns

### Basic Query
```sql
SELECT type, id FROM quakes ORDER BY type LIMIT 10
```

### Nested Objects (Dot Notation)
```sql
SELECT properties.tsunami FROM quakes
```

## DuckDB Functions
- Aggregation: `SUM()`, `AVG()`, `COUNT()`, `MIN()`, `MAX()`
...
````

Note `quakes`, `properties.tsunami`, `type`, `id` — those are read out of the registered data, not placeholders. Small models fail at SQL mostly by inventing column names, guessing at nesting, or reaching for a dialect the engine doesn't speak. Naming all three up front, in the prompt, removes most of that failure surface before the model writes a token.

### When you *don't* need this

Be honest about the alternative: if you are writing the SQL yourself, or a frontier model is, and you trust the query, then DuckDB already does this in one line:

```sql
SELECT * FROM read_json_auto('data.json');
```

JSONFlux earns its place when **the SQL author is small, cheap, or untrusted** — and when you would rather not find out what a hallucinated query does to a database connection with filesystem access. It is also a genuinely useful inspection tool on its own: `read_json_auto` samples and coerces, while JSONFlux scans every value and reports union types (`mag: int | float`), nullability (`alert: str?`), and per-field statistics.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔒 **Sandboxed by Default** | SQL runs in a locked-down DuckDB — no filesystem, network, extensions, or writes. Safe to point generated queries at. |
| 📝 **Self-Writing System Prompt** | `generate_prompt()` emits DuckDB dialect rules and query patterns using *your* table and field names — no prompt engineering |
| 🤖 **Built for Small Models** | Flat, explicitly-typed schemas, so a weak model gets the query right on the first try |
| 🪶 **Context-Window Friendly** | Megabytes of JSON become a few hundred tokens of schema — the data never enters the prompt |
| 🎯 **Lossless Ingestion** | Every row and field is scanned; no dropped keys, no truncated values, no sampled guesses |
| 🔍 **Structure Analysis** | Union types, nullability, nesting, and patterns — what `read_json_auto` won't tell you |
| 🌳 **Tree Visualization** | Multiple formats: tree, tabs, bracket, and compact schema |
| 📊 **Statistics** | Comprehensive stats: counts, sizes, distributions, nulls |
| 🔎 **SQL Queries** | Full DuckDB SQL (JOINs, CTEs, window functions) over nested JSON |
| 🚀 **High Performance** | msgspec for parsing, Arrow for zero-copy data transfer |
| 📁 **Multiple Sources** | Load from dicts, lists, strings, or files |

---

## 📑 Table of Contents

- [Why This Exists](#-why-this-exists)
- [Quick Start](#-quick-start)
- [Security & Sandboxing](#-security--sandboxing)
- [Lossless Ingestion](#-lossless-ingestion)
- [Installation](#-installation)
- [Structure Analysis](#-structure-analysis)
  - [Tree Visualization](#tree-visualization)
  - [Output Formats](#output-formats)
  - [Statistics](#statistics)
- [SQL Queries](#-sql-queries)
  - [Basic Queries](#basic-queries)
  - [QueryEngine (Multi-Table)](#queryengine-multi-table)
  - [Nested Fields & Arrays](#nested-fields--arrays)
- [LLM Integration](#-llm-integration)
- [Configuration](#%EF%B8%8F-configuration)
- [Input Sources](#-input-sources)
- [Performance](#-performance)
- [API Reference](#-api-reference)
- [Development](#-development)

---

## 🚀 Quick Start

```python
from jsonflux import JsonFlux

# Your JSON data
data = {
    "users": [
        {"id": 1, "name": "Alice", "score": 95.5, "active": True},
        {"id": 2, "name": "Bob", "score": 87.0, "active": False},
    ],
    "metadata": {"version": "1.0", "count": 2}
}

# Analyze structure
flux = JsonFlux().analyze(data)

# Visualize as tree
print(flux.tree())

# Get compact schema (great for LLMs)
print(flux.tree(format="schema"))

# Query with SQL
results = flux.query("SELECT unnest(users) as u FROM data WHERE u.score > 90")
```

Use as a context manager to ensure resources are released automatically:

```python
with JsonFlux() as flux:
    flux.analyze(data)
    print(flux.tree())
    results = flux.query("SELECT * FROM data LIMIT 10")
# DuckDB connection is automatically closed
```

---

## 🔒 Security & Sandboxing

JSONFlux exists so an LLM can answer data questions by **writing SQL instead of
being handed a shell** with `curl`/`jq`/filesystem access. That only reduces
risk if the SQL engine itself cannot reach outside the data you gave it — so by
default it can't.

Out of the box, DuckDB can read your filesystem, write files, reach the network,
and load extensions directly from SQL:

```sql
-- All of this works in a *default* DuckDB connection:
SELECT content FROM read_text('/etc/passwd');       -- exfiltrate files
COPY (SELECT ...) TO '/tmp/out' (FORMAT csv);        -- write files
INSTALL httpfs; SELECT * FROM read_csv('https://…'); -- reach the network
ATTACH '/some/other.db';                             -- open other databases
```

A prompt-injected model — or a malicious value inside the very JSON being
analyzed — could emit any of these. **JSONFlux blocks them all by default.**
Every `QueryEngine` (and every `JsonFlux.query()`) runs on a DuckDB connection
that is locked down at creation time:

| Protection | Effect |
|-----------|--------|
| `enable_external_access=false` | `read_csv`/`read_text`/`COPY`/`ATTACH`/`glob` over any local or remote path fail |
| Extensions disabled | No `INSTALL`/`LOAD`, no autoload, no community extensions (blocks `httpfs` network access) |
| `lock_configuration=true` | The settings above **cannot** be re-enabled by a later `SET`/`PRAGMA`/`RESET` |
| **Read-only mode** (default) | Only `SELECT`/`EXPLAIN` run; `DROP`/`DELETE`/`INSERT`/`CREATE`/`ATTACH`/`COPY`/`SET` are rejected **at parse time** — hostile SQL can't drop your registered tables |
| `memory_limit` (default `2GB`) | Bounds runaway aggregations / cross joins inside DuckDB |
| `query_timeout` (default `30s`) | A pathological query is interrupted, not run to completion |
| **`max_result_rows`** (default `1M`) | Caps the Python-side result so a `LIMIT`-less `SELECT` can't OOM the host (DuckDB's `memory_limit` does **not** bound this) |
| **`max_result_bytes`** (default `256MB`) | Backstops pathological giant-cell results (e.g. `repeat('x', 2e9)`), recursing into nested values |
| Identifier validation | Registered / described table names must be plain SQL identifiers (no injection) |

The read-only guard uses DuckDB's own parser (`extract_statements`), so comments,
whitespace, and multi-statement SQL (`SELECT 1; DROP VIEW data`) can't smuggle a
write past it. Complex reads — CTEs, window functions, subqueries, `UNNEST` — all
still work. For intentionally large results, use `query_iter()` (streaming) or
`query_arrow()` (columnar), which bypass the row cap safely.

```python
from jsonflux import QueryEngine

engine = QueryEngine().register("data", my_json)  # sandboxed by default

engine.query("SELECT content FROM read_text('/etc/passwd')")
# duckdb.PermissionException: file system operations are disabled

engine.query("INSTALL httpfs")
# duckdb.PermissionException: extension installation is disabled

engine.query("SELECT category, SUM(price) FROM data GROUP BY category")  # ✅ works
```

### Tuning the policy

Everything is configurable via `SecurityConfig`. The defaults are the safe
choice; loosen only what you need and trust.

```python
from jsonflux import QueryEngine, SecurityConfig

# Convenience overrides
engine = QueryEngine(
    memory_limit="512MB",
    query_timeout=10.0,
)

# Full control
engine = QueryEngine(security=SecurityConfig(
    allow_external_access=False,  # keep the filesystem/network locked (default)
    allow_extensions=False,       # keep extensions disabled (default)
    read_only=True,               # only SELECT/EXPLAIN (default)
    memory_limit="1GB",
    threads=4,
    query_timeout=15.0,
    lock_configuration=True,      # freeze all of the above (default)
    max_result_rows=1_000_000,    # cap Python-side result rows (default)
    max_result_bytes=256 * 1024 * 1024,  # cap result payload bytes (default)
))

# Opt in to writes/DDL when you trust the query author (sandbox still applies):
writable = QueryEngine(read_only=False)

# Opt in to filesystem access ONLY if you trust whoever writes the SQL:
trusted = QueryEngine(allow_external_access=True)
```

`JsonFlux` accepts the same policy: `JsonFlux(security=SecurityConfig(...))`.

> **Why this matters for small models.** The whole point of JSONFlux is that a
> small model like Haiku can safely drive complex aggregations on your behalf.
> The sandbox is what makes "safely" true — even if the model is wrong or
> adversarial, the blast radius is the JSON you registered and nothing else.

---

## 🎯 Lossless Ingestion

Real-world API JSON is messy: fields appear only in some records, a value is an
`int` on most rows and a `float` on one, IDs overflow 64 bits, a field is
sometimes an object and sometimes a scalar. If ingestion silently drops or
truncates any of that, an aggregation over it is quietly **wrong** — the worst
kind of bug for a data tool.

JSONFlux scans **every row and every field** to build the queryable table, and
resolves conflicts predictably instead of crashing or corrupting:

| Input across rows | Result column | Guarantee |
|-------------------|---------------|-----------|
| `int` + `float` | `DOUBLE` | widened, never truncated (`3.7` stays `3.7`) |
| Key first seen on row 10,000 | its own column | never dropped |
| `int` beyond 64-bit | `VARCHAR` | preserved **exactly**, no overflow |
| `int` + `str` (genuine conflict) | `VARCHAR` | both values kept as text |
| object ⟷ scalar / array | `VARCHAR` (JSON) | kept as JSON text, still queryable |
| Root array of primitives | `value` column | `SELECT value FROM t` |
| Empty `[]` / `{}` | valid empty table / string | no crash |

```python
# A float that appears only after thousands of int rows is NOT truncated:
engine = QueryEngine().register("t",
    [{"id": i, "v": i} for i in range(10_000)] + [{"id": 10_000, "v": 3.7}])
engine.query("SELECT v FROM t WHERE id = 10000")   # -> [{'v': 3.7}]  ✅
```

The full scan is cheap because clean data (no type conflicts) is handed to Arrow
without any per-row Python normalization; only conflicting columns are coerced.
For large files, ingestion also **streams** — decoding one element at a time
instead of building the whole Python object graph up front — which cuts peak
memory 2-3x (see [Performance](#-performance)).

---

## 📦 Installation

### Using pip

```bash
pip install jsonflux
```

### Using uv (recommended)

```bash
uv add jsonflux
```

### Dependencies

JSONFlux uses high-performance libraries under the hood:

| Library | Purpose |
|---------|---------|
| **msgspec** | Ultra-fast JSON parsing |
| **DuckDB** | In-process analytical SQL engine |
| **PyArrow** | Zero-copy data transfer |
| **tabulate** | Beautiful table formatting |

---

## 🔍 Structure Analysis

### Tree Visualization

Analyze JSON and visualize its structure with types and sample values.

```python
from jsonflux import JsonFlux

data = {
    "users": [
        {"id": 1, "name": "Alice", "score": 95.5},
        {"id": 2, "name": "Bob", "score": 87.0},
    ],
    "metadata": {"version": "1.0", "count": 2}
}

flux = JsonFlux(samples=2).analyze(data)
print(flux.tree())
```

**Output:**
```
<root>
├── metadata
│   ├── count: int samples=[2, 2]
│   └── version: str samples=["1.0", "1.0"]
└── users
    └── object [2]
        ├── id: int samples=[1, 2]
        ├── name: str samples=["Alice", "Bob"]
        └── score: float samples=[95.5, 87.0]
```

### Output Formats

JSONFlux supports multiple output formats for different use cases:

#### 1. Tree Format (default)
Box-drawing connectors for visual clarity.

```python
flux.tree(format="tree")
```

```
<root>
├── users
│   └── object [2]
│       ├── id: int
│       └── name: str
└── metadata
    └── version: str
```

#### 2. Tabs Format
Tab-indented output, great for TSV export.

```python
flux.tree(format="tabs")
```

```
<root>
	metadata
		count: int
		version: str
	users
		object [2]
			id: int
			name: str
```

#### 3. Bracket Format
Curly brace nesting, JSON-like structure.

```python
flux.tree(format="bracket")
```

```
<root> {
	metadata {
		count: int
		version: str
	}
	users {
		object [2] {
			id: int
			name: str
		}
	}
}
```

#### 4. Schema Format (LLM-Optimized)
Compact TypeScript-like schema, ~3x fewer tokens than tree output.

```python
flux = JsonFlux(samples=0).analyze(data)
print(flux.tree(format="schema"))
```

```typescript
{
  metadata: {count: int, version: str}
  users: [{id: int, name: str, score: float}]
}
```

**Why use schema format?**
- **Token-efficient** — Saves tokens when sending to LLMs
- **Native Types** — TypeScript-inspired syntax familiar to LLMs
- **Clear Nesting** — Preserves structure for query generation
- **Nullable Markers** — `score: float?` indicates optional fields

### Statistics

Get comprehensive statistics about your JSON data.

```python
flux = JsonFlux().analyze(data)

# Full statistics with per-path breakdown
print(flux.stats())

# Compact summary
print(flux.stats(compact=True))
```

**Full stats output:**
```
======================================================================
JSON STATISTICS
======================================================================
Total values:     15
  Objects:        4
  Arrays:         1
  Primitives:     10
Estimated size:   245 B
Max depth:        3
Unique paths:     8
Collection time:  0.001s
----------------------------------------------------------------------

📍 $.users[].name
   Count: 2  |  Size: 15 B
   Types: str:2(100.0%)
   String: len=3..5, avg=4.0
   Unique(2): ['Alice', 'Bob']

📍 $.users[].score
   Count: 2  |  Size: 9 B
   Types: float:2(100.0%)
   Numeric: min=87.0, max=95.5, avg=91.25
```

**Compact stats output:**
```
============================================================
JSON STATISTICS (COMPACT)
============================================================
Total values:       15
  Objects:          4 (26.7%)
  Arrays:           1 (6.7%)
  Primitives:       10 (66.7%)

TYPE DISTRIBUTION:
  str                   4  ( 26.7%)
  int                   3  ( 20.0%)
  float                 2  ( 13.3%)

SIZE:
  Estimated total:  245 B
  Avg per value:    16 B

STRUCTURE:
  Max depth:        3
  Unique paths:     8
============================================================
```

#### Programmatic Access to Stats

```python
stats = flux.stats_result()

print(f"Total values: {stats.total_values}")
print(f"Max depth: {stats.max_depth}")
print(f"Size: {stats.total_size_bytes} bytes")

# Access per-field statistics
for path, field_stats in stats.field_stats.items():
    print(f"{path}: {field_stats.total_seen} values")
```

---

## 🔎 SQL Queries

### Basic Queries

Query analyzed data directly with SQL.

```python
from jsonflux import JsonFlux

data = {
    "products": [
        {"id": 1, "name": "Laptop", "price": 999.99, "category": "Electronics"},
        {"id": 2, "name": "Book", "price": 29.99, "category": "Books"},
        {"id": 3, "name": "Phone", "price": 699.99, "category": "Electronics"},
    ]
}

flux = JsonFlux().analyze(data)

# Query returns list of dicts
results = flux.query("""
    SELECT * FROM unnest(data.products) 
    WHERE price > 100
    ORDER BY price DESC
""")
print(results)
# [{'id': 1, 'name': 'Laptop', 'price': 999.99, 'category': 'Electronics'}, ...]
```

### Formatted Output

Get beautiful tabular output with `query_table()`:

```python
# Grid format (default)
print(flux.query_table("""
    SELECT name, price, category
    FROM unnest(data.products)
    ORDER BY price DESC
""", format="grid"))
```

```
+--------+---------+-------------+
| name   |   price | category    |
+========+=========+=============+
| Laptop |  999.99 | Electronics |
+--------+---------+-------------+
| Phone  |  699.99 | Electronics |
+--------+---------+-------------+
| Book   |   29.99 | Books       |
+--------+---------+-------------+
```

**Available formats:**
- `grid` — ASCII table with borders
- `simple` — Minimal formatting
- `markdown` — GitHub-flavored markdown
- `csv` — Comma-separated values
- `json` — JSON array

```python
# Markdown format
print(flux.query_table(sql, format="markdown"))

# CSV format
print(flux.query_table(sql, format="csv"))

# JSON format
print(flux.query_table(sql, format="json"))
```

### QueryEngine (Multi-Table)

For querying multiple JSON sources with JOINs:

```python
from jsonflux import QueryEngine

# Sample data
products = [
    {"id": "P1", "name": "Laptop", "price": 999.99},
    {"id": "P2", "name": "Phone", "price": 699.99},
    {"id": "P3", "name": "Monitor", "price": 299.99},
]

orders = [
    {"order_id": 101, "product_id": "P1", "customer": "Alice", "qty": 1},
    {"order_id": 102, "product_id": "P2", "customer": "Bob", "qty": 2},
    {"order_id": 103, "product_id": "P1", "customer": "Charlie", "qty": 1},
]

customers = [
    {"id": "Alice", "country": "USA"},
    {"id": "Bob", "country": "UK"},
    {"id": "Charlie", "country": "USA"},
]

# Register all tables
engine = QueryEngine()
engine.register("products", products)
engine.register("orders", orders)
engine.register("customers", customers)

# Query with JOINs
results = engine.query("""
    SELECT 
        c.country,
        p.name as product,
        SUM(o.qty) as total_qty,
        SUM(o.qty * p.price) as total_revenue
    FROM orders o
    JOIN products p ON o.product_id = p.id
    JOIN customers c ON o.customer = c.id
    GROUP BY c.country, p.name
    ORDER BY total_revenue DESC
""")

print(results)
```

#### Context Manager

Use `with` to ensure resources are released:

```python
with QueryEngine() as engine:
    engine.register("products", products)
    engine.register("orders", orders)
    results = engine.query("SELECT * FROM products LIMIT 5")
# DuckDB connection is automatically closed
```

#### Chained Registration

```python
engine = (
    QueryEngine()
    .register("products", products)
    .register("orders", orders)
    .register("customers", customers)
)
```

#### Register Multiple Tables

```python
engine = QueryEngine()
engine.register_many({
    "products": products,
    "orders": orders,
    "customers": customers,
})
```

#### Loading from Files

```python
engine = QueryEngine()

# From file path
engine.register("products", "data/products.json")

# With JSON path extraction
engine.register("items", "api_response.json", path="$.data.items")

# Using register_many with paths
engine.register_many({
    "products": ("catalog.json", "$.catalog.products"),
    "orders": "orders.json",  # No path, use root
})
```

### Nested Fields & Arrays

#### Dot Notation for Nested Fields

```python
products = [
    {"id": "P1", "name": "Laptop", "specs": {"cpu": "i7", "ram": "16GB"}},
    {"id": "P2", "name": "Phone", "specs": {"cpu": "M3", "ram": "8GB"}},
]

engine = QueryEngine().register("products", products)

# Access nested fields with dot notation
results = engine.query("""
    SELECT name, specs.cpu, specs.ram
    FROM products
    WHERE specs.ram = '16GB'
""")
```

#### Unnesting Arrays

```python
orders = [
    {"order_id": 101, "customer": "Alice", "items": [
        {"product": "Laptop", "qty": 1},
        {"product": "Mouse", "qty": 2}
    ]},
    {"order_id": 102, "customer": "Bob", "items": [
        {"product": "Phone", "qty": 1}
    ]},
]

engine = QueryEngine().register("orders", orders)

# Flatten array and query
results = engine.query("""
    SELECT 
        customer,
        item.product,
        item.qty
    FROM (
        SELECT customer, unnest(items) as item
        FROM orders
    )
    WHERE item.qty > 1
""")
```

#### Array Functions

```python
products = [
    {"name": "Laptop", "colors": ["silver", "space gray"]},
    {"name": "Phone", "colors": ["black", "white", "blue"]},
]

engine = QueryEngine().register("products", products)

# Check if array contains value
results = engine.query("""
    SELECT name
    FROM products
    WHERE list_contains(colors, 'silver')
""")

# Get array length
results = engine.query("""
    SELECT name, len(colors) as num_colors
    FROM products
""")
```

### Query Utilities

#### View Table Information

```python
engine.print_tables()
```

```
Registered tables:
  products:
    source: memory
    rows: 3
  orders:
    source: memory
    rows: 3
```

#### View Table Schema

```python
engine.print_schema("products")
```

```
Schema of 'products':
  id: VARCHAR
  name: VARCHAR
  price: DOUBLE
```

#### Explain Query Plan

```python
print(engine.explain("""
    SELECT * FROM products WHERE price > 100
"""))
```

---

## 🤖 LLM Integration

JSONFlux is designed with LLM workflows in mind, providing ready-to-use system prompts for SQL generation.

The prompt is written for the weakest model you are likely to point at it. It states the schema explicitly rather than expecting the model to infer it, spells out the notation, and shows worked query patterns — which is what a small or local model needs to emit correct SQL on the first attempt. Any model in the example below can be swapped for a local one; nothing here assumes a frontier model.

### Quick Start: One-Shot SQL Generation

The fastest way to use JSONFlux with an LLM:

```python
from jsonflux import QueryEngine
from pydantic_ai import Agent

# 1. Register your data
engine = QueryEngine()
engine.register("orders", orders_data)
engine.register("products", products_data)

# 2. Create agent with built-in system prompt
agent = Agent("openai:gpt-4o", system_prompt=engine.generate_prompt())

# 3. Ask questions, get SQL, execute
async def query(question: str) -> str:
    result = await agent.run(question)
    return engine.format_query(result.data, format="markdown")

# Usage
print(await query("What are total sales by product category?"))
```

### Built-in System Prompt

`engine.generate_prompt()` returns a comprehensive prompt that includes:

- **Schema interpretation** — How to read the TypeScript-like notation
- **Query patterns** — 6 patterns from simple to complex JOINs
- **UNNEST examples** — Critical for array handling (the #1 mistake LLMs make)
- **DuckDB functions** — Common functions the LLM can use
- **Common mistakes** — What to avoid
- **Your table schemas** — Automatically appended

```python
# Get the complete system prompt
print(engine.generate_prompt())
```

**Example output:**
```
You are a SQL query generator for JSON data...

## How This Works
...

## Query Patterns

### Pattern 3: Arrays (UNNEST) — CRITICAL
**Arrays MUST be flattened with UNNEST before grouping/aggregation.**
...

---

# YOUR DATA

## Available Tables

### orders (150 rows)

{order_id: int, customer: str, items: [{product: str, qty: int, price: float}]}

...
```

### Using with Different LLM Libraries

#### pydantic-ai

```python
from pydantic_ai import Agent
from jsonflux import QueryEngine

engine = QueryEngine().register("data", my_json)

agent = Agent("openai:gpt-4o", system_prompt=engine.generate_prompt())
result = await agent.run("Show top 5 customers by total spend")
print(engine.format_query(result.data, format="grid"))
```

#### OpenAI SDK

```python
from openai import OpenAI
from jsonflux import QueryEngine

client = OpenAI()
engine = QueryEngine().register("data", my_json)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": engine.generate_prompt()},
        {"role": "user", "content": "What are total sales by region?"}
    ]
)
sql = response.choices[0].message.content
print(engine.format_query(sql, format="markdown"))
```

#### Anthropic SDK

```python
from anthropic import Anthropic
from jsonflux import QueryEngine

client = Anthropic()
engine = QueryEngine().register("data", my_json)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    system=engine.generate_prompt(),
    messages=[{"role": "user", "content": "Show monthly revenue trends"}]
)
sql = response.content[0].text
print(engine.format_query(sql, format="markdown"))
```

### Custom System Prompts

If you want to customize the prompt, you can use the schema context separately:

```python
from jsonflux import QueryEngine

engine = QueryEngine().register("data", my_json)

# Use just the schema context (for your own prompt)
schema_only = engine.describe_tables()

# Combine with your own instructions
custom_prompt = f"""
You are a SQL query generator.

ADDITIONAL INSTRUCTIONS:
- Always limit results to 100 rows
- Use snake_case for column aliases

{engine.describe_tables()}
"""
```

### Schema Context Only

Use `describe_tables()` for just the schema (minimal tokens):

```python
context = engine.describe_tables()
print(context)
```

**Output:**
```markdown
## Available Tables

### products (3 rows)

```typescript
{
  id: str
  name: str
  price: float
  category: str
}
```

### orders (3 rows)

```typescript
{
  order_id: int
  product_id: str
  customer: str
  qty: int
}
```

## SQL Notes

- Use standard SQL syntax (DuckDB)
- Access nested objects with dot notation: `table.nested.field`
- **Arrays require UNNEST for grouping/aggregation:**
  ```sql
  SELECT item.field, SUM(item.qty)
  FROM (SELECT unnest(array_column) as item FROM table)
  GROUP BY item.field
  ```
- JOINs, CTEs, and window functions are supported
```

### Natural Language to SQL Workflow

```python
from jsonflux import QueryEngine

# 1. Set up your data
engine = QueryEngine()
engine.register("products", products_data)
engine.register("orders", orders_data)
engine.register("customers", customers_data)

# 2. Generate context for LLM
context = engine.describe_tables()

# 3. Send to LLM with user question
prompt = f"""
Given these tables:

{context}

User question: "What are total sales by country?"

Generate a SQL query to answer this question.
"""

# 4. LLM generates SQL (example output)
sql = """
SELECT 
    c.country,
    SUM(o.qty * p.price) as total_sales
FROM customers c
JOIN orders o ON c.id = o.customer
JOIN products p ON o.product_id = p.id
GROUP BY c.country
ORDER BY total_sales DESC
"""

# 5. Execute and format results
print(engine.format_query(sql, format="markdown"))
```

### Schema with Samples

Include sample values to help LLMs understand data patterns:

```python
flux = JsonFlux(samples=3).analyze(data)
print(flux.tree(format="schema"))
```

```typescript
{
  users: [{
    id: int samples=[1, 2, 3]
    name: str samples=["Alice", "Bob", "Charlie"]
    score: float samples=[95.5, 87.0, 92.3]
  }]
}
```

### SQL Query Patterns for LLMs

When generating SQL queries, LLMs should use these patterns:

#### Pattern 1: Flat Data with Dot Notation

For nested objects, use dot notation directly:

```sql
-- Schema: {user: {name: str, address: {city: str, country: str}}}
SELECT 
    user.name,
    user.address.city,
    user.address.country
FROM data
WHERE user.address.country = 'USA'
```

#### Pattern 2: UNNEST for Array Aggregation

**This is the key pattern for grouping/aggregating array data.**

When data has arrays that need to be grouped or aggregated, use `UNNEST` in a subquery:

```sql
-- Schema: {orders: [{customer: str, items: [{product: str, qty: int, price: float}]}]}

-- Step 1: Unnest orders array
-- Step 2: Unnest items array within each order  
-- Step 3: Group and aggregate

SELECT 
    o.customer,
    i.product,
    SUM(i.qty) as total_qty,
    SUM(i.qty * i.price) as total_spent
FROM (
    SELECT unnest(orders) as o
    FROM data
) orders_flat,
LATERAL (
    SELECT unnest(o.items) as i
) items_flat
GROUP BY o.customer, i.product
ORDER BY total_spent DESC
```

#### Pattern 3: Simple Array Flattening

For a single array level:

```sql
-- Schema: {products: [{name: str, price: float, category: str}]}

SELECT 
    p.category,
    COUNT(*) as count,
    AVG(p.price) as avg_price
FROM (
    SELECT unnest(products) as p
    FROM data
)
GROUP BY p.category
```

#### Pattern 4: Multi-Table JOINs with Arrays

When joining tables that have arrays:

```sql
-- products: [{id: str, name: str, price: float}]
-- orders: [{order_id: int, items: [{product_id: str, qty: int}]}]

SELECT 
    p.name,
    SUM(item.qty) as total_sold,
    SUM(item.qty * p.price) as revenue
FROM products p
JOIN (
    SELECT unnest(items) as item
    FROM orders
) o ON o.item.product_id = p.id
GROUP BY p.name
ORDER BY revenue DESC
```

#### Pattern 5: Filtering Before and After UNNEST

```sql
-- Filter parent rows BEFORE unnest (more efficient)
SELECT i.product, i.qty
FROM (
    SELECT unnest(items) as i
    FROM orders
    WHERE customer = 'Alice'  -- Filter before unnest
)
WHERE i.qty > 1  -- Filter after unnest
```

#### UNNEST Quick Reference

| Goal | SQL Pattern |
|------|-------------|
| Flatten array | `SELECT unnest(arr) as item FROM table` |
| Access flattened fields | `SELECT item.field FROM (SELECT unnest(arr) as item FROM table)` |
| Count items | `SELECT COUNT(*) FROM (SELECT unnest(arr) FROM table)` |
| Group by array field | `SELECT item.category, COUNT(*) FROM (SELECT unnest(arr) as item FROM table) GROUP BY item.category` |
| Nested arrays | Use `LATERAL` with multiple unnests |

---

## ⚙️ Configuration

### JsonFlux Options

```python
flux = JsonFlux(
    max_depth=32,           # Max nesting depth to analyze
    sample_per_kind=200,    # Max samples per type in arrays
    sort_keys=True,         # Sort object keys alphabetically
    max_keys_per_object=None,  # Limit keys shown (None = all)
    samples=3,              # Number of sample values to collect
    sample_seed=12345,      # Seed for reproducible sampling
    max_sample_len=60,      # Max length for sample strings
)
```

| Option | Default | Description |
|--------|---------|-------------|
| `max_depth` | 32 | Maximum nesting depth to traverse |
| `sample_per_kind` | 200 | Max samples per type when analyzing arrays |
| `sort_keys` | True | Sort object keys alphabetically in output |
| `max_keys_per_object` | None | Limit number of keys shown per object |
| `samples` | 3 | Number of sample values to collect (0 to disable) |
| `sample_seed` | 12345 | Random seed for reproducible sampling |
| `max_sample_len` | 60 | Maximum character length for string samples |

### QueryEngine Options

```python
# Format query options
engine.format_query(
    sql,
    format="grid",        # Output format
    max_rows=20,          # Limit rows (None = all)
    max_colwidth=50,      # Max column width (None = unlimited)
)
```

---

## 📁 Input Sources

JSONFlux accepts multiple input types:

```python
from pathlib import Path
from jsonflux import JsonFlux

flux = JsonFlux()

# Dict
flux.analyze({"key": "value"})

# List
flux.analyze([{"id": 1}, {"id": 2}])

# JSON string
flux.analyze('{"key": "value"}')

# File path (string)
flux.analyze("data.json")

# File path (Path object)
flux.analyze(Path("data.json"))

# List of JSON strings (batch processing)
flux.analyze(['{"id": 1}', '{"id": 2}', '{"id": 3}'])
```

---

## ⚡ Performance

JSONFlux is optimized for speed *and* peak memory:

| Optimization | Description |
|--------------|-------------|
| **msgspec** | 2-10x faster JSON parsing than stdlib |
| **DuckDB** | Columnar, vectorized SQL execution |
| **PyArrow** | Zero-copy data transfer between Python and DuckDB |
| **Streaming ingestion** | Large files decode one element at a time → ~2-3x lower peak RAM |
| **Fast/slow inference split** | Clean data skips per-row Python normalization |
| **`__slots__`** | Memory-efficient class instances |

### Benchmarks

All numbers come from [`bench/benchmark.py`](bench/benchmark.py), which measures
honestly: every timing is the **mean ± stddev over 7 repeats** after a warm-up,
throughput is reported in the unit that matters (MB/s, records/s, rows/s), and
peak memory is measured as **peak RSS in an isolated subprocess** (so it captures
the msgspec object graph *and* the Arrow allocation, not just Python heap).

Machine: the figures below are from one development machine; run it yourself with
`uv run python bench/benchmark.py --repeat 7 --sizes 20000,100000`.

**Ingestion throughput** (register). In-memory `dict`/`list` sources and files
below `stream_min_bytes` (default 4 MB) take the fast bulk path; larger files
stream.

| Shape | Records | JSON | Source | Time | MB/s | records/s |
|-------|--------:|-----:|--------|-----:|-----:|----------:|
| flat | 100k | 8.2 MB | memory | 78 ms | 106 | 1,290,000 |
| flat | 100k | 8.2 MB | file (stream) | 167 ms | 50 | 600,000 |
| nested | 100k | 20.4 MB | memory | 257 ms | 79 | 389,000 |
| nested | 100k | 20.4 MB | file (stream) | 478 ms | 43 | 209,000 |
| wide | 100k | 50.6 MB | memory | 437 ms | 116 | 229,000 |

**Ingestion peak memory** — the headline improvement. Streaming decode replaces
the "decode the whole file into a Python graph first" approach; peak RSS over the
import baseline, as a multiple of the JSON size:

| Shape | Records | JSON | Bulk (before) | Streaming (after) | Saved |
|-------|--------:|-----:|--------------:|------------------:|------:|
| flat | 100k | 8.2 MB | 69 MB (8.4×) | **32 MB (3.9×)** | 53% |
| nested | 100k | 20.4 MB | 196 MB (9.6×) | **64 MB (3.1×)** | 67% |
| wide | 100k | 50.6 MB | 279 MB (5.5×) | **136 MB (2.7×)** | 51% |

Streaming trades ~30-50% ingestion throughput for that memory (a one-time cost on
`register`); it applies only to file/JSON-string array sources at or above
`stream_min_bytes`. Tune or disable it per engine:

```python
QueryEngine(stream_min_bytes=0)        # always stream (lowest memory)
QueryEngine(stream_min_bytes=10**12)   # never stream (fastest ingest)
```

**Queries** (nested, 100k rows) — unaffected by the ingestion changes:

| Query | Time | rows out | rows/s |
|-------|-----:|---------:|-------:|
| `GROUP BY` aggregation | 4.4 ms | 3 | — |
| filter (`WHERE`) | 8.5 ms | 1,000 | 118,000 |
| `UNNEST` + `GROUP BY` | 10.5 ms | 501 | 47,000 |
| full scan → list of dicts | 398 ms | 100,000 | 251,000 |

A full-table scan into Python dicts costs ~2 KB/row (100k nested rows ≈ 218 MB
resident). For large result sets, prefer `query_arrow()` (columnar, streaming
reader) or `query_iter()` (batched) — both bypass that materialization.

### Timing Information

```python
flux = JsonFlux().analyze(large_data)

timing = flux.timing()
print(f"Parse time: {timing['parse_time']:.3f}s")
print(f"Analyze time: {timing['analyze_time']:.3f}s")
print(f"Sample time: {timing['sample_time']:.3f}s")
print(f"Total: {timing['total_time']:.3f}s")
```

---

## 📡 API Reference

### JsonFlux Class

| Method | Description |
|--------|-------------|
| `analyze(source)` | Load and analyze JSON data |
| `tree(format, indent, root_label)` | Return structure visualization |
| `stats(compact, top_n, max_unique)` | Return statistics report |
| `stats_result(max_unique)` | Return raw StatsResult object |
| `query(sql)` | Execute SQL, return list of dicts |
| `query_table(sql, format, max_rows, max_colwidth)` | Execute SQL, return formatted string |
| `timing()` | Return timing information |
| `profile_result()` | Return raw ProfileResult |
| `close()` | Close cached query engine and release resources |

### QueryEngine Class

**Constructor:** `QueryEngine(security=None, *, allow_external_access=None, memory_limit=None, query_timeout=None, read_only=None, max_result_rows=…, max_depth=64, sample_scan_limit=1000, stream_min_bytes=4194304)` — sandboxed and read-only by default; file/JSON-string array sources ≥ `stream_min_bytes` stream for low memory. See [Security & Sandboxing](#-security--sandboxing) and [Performance](#-performance).

| Method | Description |
|--------|-------------|
| `register(name, source, path)` | Register a JSON source as table (name must be a plain SQL identifier) |
| `register_many(tables)` | Register multiple tables at once |
| `query(sql)` | Execute SQL, return list of dicts |
| `query_arrow(sql)` | Execute SQL, return PyArrow Table |
| `execute(sql)` | Execute SQL, return raw DuckDB result |
| `execute_query(sql, split, max_colwidth)` | Execute SQL, return structured QueryResult |
| `format_query(sql, format, max_rows, max_colwidth)` | Execute SQL, return formatted string |
| `generate_prompt(samples)` | Generate complete LLM system prompt |
| `describe_tables(samples)` | Generate LLM-friendly schema context |
| `explain(sql)` | Show query execution plan |
| `tables_info()` | Show registered tables info |
| `schema(table)` | Show schema of a table |
| `close()` | Close DuckDB connection and release resources |

### SecurityConfig Class

Sandbox and resource policy for the SQL engine. All defaults are the safe choice.

| Option | Default | Description |
|--------|---------|-------------|
| `allow_external_access` | `False` | Allow SQL filesystem/network access (`read_csv`, `COPY`, `ATTACH`, …) |
| `allow_extensions` | `False` | Allow extension install/load (incl. community extensions) |
| `read_only` | `True` | Accept only `SELECT`/`EXPLAIN`; reject writes/DDL/`SET` at parse time |
| `memory_limit` | `"2GB"` | DuckDB memory cap (`None` = DuckDB default) |
| `threads` | `None` | DuckDB worker threads (`None` = DuckDB default) |
| `query_timeout` | `30.0` | Seconds before a running query is interrupted (`None` = no timeout) |
| `lock_configuration` | `True` | Freeze the above so `SET`/`PRAGMA`/`RESET` can't loosen them at runtime |
| `max_result_rows` | `1_000_000` | Max rows a materialising query may return (`None` = no cap) |
| `max_result_bytes` | `268_435_456` | Max string/blob payload bytes in a result (`None` = no cap) |

Exceptions: a query exceeding the row/byte caps raises `ResultTooLargeError`; a
non-read statement in read-only mode raises `ReadOnlyViolationError`; a query
past `query_timeout` raises `TimeoutError`. All three are exported from
`jsonflux`.

### Output Formats

| Format | `tree()` | `format_query()` | Description |
|--------|----------|------------------|-------------|
| `tree` | ✅ | | Box-drawing connectors |
| `tabs` | ✅ | | Tab-indented |
| `bracket` | ✅ | | Curly brace nesting |
| `schema` | ✅ | | Compact TypeScript-like |
| `grid` | | ✅ | ASCII table with borders |
| `simple` | | ✅ | Minimal formatting |
| `pipe` | | ✅ | Pipe-delimited table |
| `markdown` | | ✅ | GitHub-flavored markdown |
| `csv` | | ✅ | Comma-separated values |
| `json` | | ✅ | JSON array |

---

## 🛠️ Development

### Setup

```bash
git clone https://github.com/ikaric/jsonflux.git
cd jsonflux

# Install with dev dependencies
uv sync --extra dev

# Or with pip
pip install -e ".[dev]"
```

### Testing

The suite contains **289 tests** across five files:

| File | Tests | Focus |
|------|-------|-------|
| `test_jsonflux.py` | 100 | SQL fundamentals, JOINs, nested/UNNEST queries, LLM prompt generation |
| `test_inference.py` | 39 | Every JSON type combination & conflict — lossless, crash-free ingestion |
| `test_security.py` | 82 | Sandbox, read-only mode, result caps, timeout, memory, injection, creative file-write vectors |
| `test_streaming.py` | 36 | Low-memory streaming ingestion == bulk path (fuzzed element iterator + table builder) |
| `test_performance.py` | 32 | Caching, iterative merge, streaming, regression guards |

`test_jsonflux.py` runs against a deterministic generated dataset (seed=42) with
15k+ orders and deeply nested structures. See **[TEST_CATALOG.md](TEST_CATALOG.md)**
for the annotated catalog.

```bash
# Run everything
uv run pytest

# With coverage
uv run pytest --cov=jsonflux --cov-report=term-missing

# Focused runs
uv run pytest tests/test_security.py -v    # sandbox guarantees
uv run pytest tests/test_inference.py -v   # type-combination matrix
uv run pytest -k "join or unnest" -v       # JOIN / UNNEST behaviour
```

### Linting

```bash
# Check code
uv run ruff check src/

# Format code
uv run ruff format src/
```

### Validation

JSONFlux includes a built-in validation function:

```python
from jsonflux import validate

# Returns empty list on success, or list of error strings
errors = validate()
if errors:
    print("Validation failed:", errors)
```

---

## 📄 License

This project is licensed under the **MIT License**.

---

<div align="center">

**[⬆ Back to Top](#-jsonflux)**

Made with ❤️ for the Python community

</div>
