# Test Suite

**100 tests | all passing | ~4.6s runtime**

```
============================= 100 passed in 4.61s ==============================
```

Tests run against a deterministic generated dataset (seed=42) containing 1,000 products, 5,000 customers, 15,000 orders, and 7,500 reviews with deeply nested fields, arrays, and nullable values.

---

## Table of Contents

| # | Category | Tests | Coverage |
|---|----------|-------|----------|
| 1 | [Core Analysis & Visualization](#1-core-analysis--visualization) | 10 | Tree formats, schema rendering, statistics, sampling |
| 2 | [SQL Fundamentals](#2-sql-fundamentals) | 24 | SELECT, WHERE, GROUP BY, JOINs, CTEs, window functions |
| 3 | [Cross-Table JOINs](#3-cross-table-joins) | 11 | INNER/LEFT JOIN, multi-table, subquery joins, analytics |
| 4 | [QueryEngine Features](#4-queryengine-features) | 5 | Nested fields, UNNEST, list_contains, format output |
| 5 | [Error Handling & Edge Cases](#5-error-handling--edge-cases) | 7 | Unanalyzed data, invalid SQL, single row, bad formats |
| 6 | [LLM Prompt Generation (basic)](#6-llm-prompt-generation-basic) | 3 | generate_prompt() content, samples on/off |
| 7 | [execute_query() & QueryResult](#7-execute_query--queryresult) | 4 | Success/error results, split preview, column width |
| 8 | [query_print()](#8-query_print) | 2 | Console output, title rendering |
| 9 | [Engine Caching](#9-engine-caching) | 2 | Reuse on repeated queries, invalidation on re-analyze |
| 10 | [Resource Management](#10-resource-management) | 4 | close(), context managers for both classes |
| 11 | [describe_tables()](#11-describe_tables) | 2 | Schema context output, samples toggle |
| 12 | [Validation & Version](#12-validation--version) | 2 | validate() sanity, __version__ accessibility |
| 13 | [Hard / Complex SQL](#13-hard--complex-sql) | 12 | UNNEST+JOIN, QUALIFY, EXISTS, NTILE, EXCEPT, FILTER |
| 14 | [Auto-Generated System Prompt](#14-auto-generated-system-prompt) | 12 | Dynamic examples, join detection, depth limiting |

---

## 1. Core Analysis & Visualization

Tests that verify JSON structure analysis, tree rendering, schema output, sampling, and statistics collection.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 1 | `test_benchmark_performance` | Analysis of 15k+ records completes in under 1 second | `duration < 1.0` |
| 2 | `test_structure_tree_verification` | Tree output contains all top-level sections and box-drawing characters | `catalog`, `transactions`, `orders`, `edge_cases`, `└──`, `├──` present |
| 3 | `test_rendering_formats` | Tabs format uses tab indentation; bracket format uses curly braces | No `└──` in tabs; `{` and `}` in bracket |
| 4 | `test_schema_format` | Schema output is compact TypeScript-like with types and array notation | `[{` present; `str`, `int` present |
| 5 | `test_schema_simple_types` | Schema correctly renders simple objects, arrays of objects, and mixed arrays | `name: str`, `id: int`, `float` for respective inputs |
| 6 | `test_schema_with_samples` | Schema includes sample values when enabled, omits when disabled | `samples=` present/absent based on config |
| 7 | `test_sampling_logic` | Sampling toggle works on large datasets | `samples=[` absent at 0, present at 3 |
| 8 | `test_statistical_report` | Stats report contains expected header fields and per-path breakdown | `JSON STATISTICS`, `Total values:`, `Max depth:`, `📍 $` |
| 9 | `test_query_capabilities` | Basic SQL queries work on analyzed data (count, aggregation, JOIN) | Product count = 1000; status grouping returns rows; JOIN returns category+sales |
| 10 | `test_tabular_query_rendering` | Grid and markdown formats produce expected delimiters | `+`, `\|` in grid; `\|`, `product_id` in markdown |

---

## 2. SQL Fundamentals

Comprehensive SQL feature coverage using the `QueryEngine` with 4 registered tables (products, customers, orders, reviews).

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 11 | `test_sql_basic_select` | SELECT with ORDER BY DESC and LIMIT | 5 rows returned; prices in descending order |
| 12 | `test_sql_count_group_by` | COUNT(*) with GROUP BY | Category counts sum to exactly 1000 |
| 13 | `test_sql_aggregates` | MIN, MAX, AVG, SUM aggregate functions | Total = 1000; min <= max; avg > 0 |
| 14 | `test_sql_where_filter` | WHERE clause with AND condition | All rows have `price > 2000` |
| 15 | `test_sql_case_expression` | CASE WHEN expressions with tier classification | Tier matches price ranges exactly |
| 16 | `test_sql_string_functions` | UPPER(), LENGTH() string functions | category_upper is all-caps; name_length > 0 |
| 17 | `test_sql_having_clause` | GROUP BY with HAVING filter | All returned categories have count > 100 |
| 18 | `test_sql_subquery` | Subquery in WHERE clause (price > avg) | All prices exceed independently-queried average |
| 19 | `test_sql_cte` | Common Table Expression (WITH clause) | Returns category stats with cnt and avg columns |
| 20 | `test_sql_window_functions` | RANK() and ROW_NUMBER() with PARTITION BY | Both rank columns >= 1 |
| 21 | `test_sql_distinct` | SELECT DISTINCT | All returned categories are unique |
| 22 | `test_sql_union` | UNION ALL combining two filtered sets | All rows have tier "high" or "low" |
| 23 | `test_sql_math_operations` | Arithmetic: multiplication, division, rounding | Computed values match within 0.01 tolerance |
| 24 | `test_sql_coalesce_null_handling` | COALESCE replaces NULLs | No NULL values in phone_display |
| 25 | `test_sql_like_pattern` | LIKE pattern matching with wildcard | All product_ids start with "P0001" |
| 26 | `test_sql_in_clause` | IN clause filtering | All categories in the specified set |
| 27 | `test_sql_between` | BETWEEN range filter | All prices in [100, 500] |
| 28 | `test_sql_order_status_distribution` | GROUP BY on order status with percentage calculation | 5 statuses; total = 15,000 orders |
| 29 | `test_sql_customer_segments` | Multi-column GROUP BY (segment + country) | Segments are consumer, small_business, or enterprise |
| 30 | `test_sql_review_ratings` | Rating distribution with percentage | 5 ratings (1-5); all in valid range |
| 31 | `test_sql_format_grid` | Grid format output rendering | Contains `+`, `\|`, and column name |
| 32 | `test_sql_format_markdown` | Markdown format output rendering | Contains `\|` and column name |
| 33 | `test_sql_format_csv` | CSV format output rendering | Header row matches; line count = header + data rows |
| 34 | `test_sql_format_json` | JSON format output parsing | Valid JSON array with expected keys |

---

## 3. Cross-Table JOINs

Multi-table JOIN queries using products, customers, orders, and reviews, including nested field joins.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 35 | `test_sql_inner_join_products_reviews` | INNER JOIN between products and reviews on product_id | 20 rows; ratings in [1, 5] |
| 36 | `test_sql_left_join_products_reviews` | LEFT JOIN with COUNT aggregate | 10 rows; top product has reviews > 0 |
| 37 | `test_sql_join_with_aggregates` | JOIN + COUNT DISTINCT + AVG aggregates per category | Rows contain category and avg_rating |
| 38 | `test_sql_join_products_reviews_customers` | 3-table JOIN (reviews + products + customers) with HAVING | All rows have review_count > 5 |
| 39 | `test_sql_join_with_subquery` | JOIN to a derived table (subquery with HAVING) | All products have review_count >= 5 |
| 40 | `test_sql_cross_table_cte` | Multi-CTE: product_reviews + category_stats with JOIN | All rows have reviews > 0 |
| 41 | `test_sql_customers_orders_join` | JOIN on nested field `o.customer.customer_id = c.customer_id` | 20 rows; non-null IDs |
| 42 | `test_sql_customer_order_aggregates` | Segment-level aggregates via nested field JOIN | 3 segments; orders_per_customer > 0 |
| 43 | `test_sql_order_status_by_country` | Cross-table GROUP BY: country + status | Valid status values only |
| 44 | `test_sql_top_reviewed_by_category` | Window function ROW_NUMBER with PARTITION BY per category | At most 3 products per category |
| 45 | `test_sql_full_analytics_query` | Complex analytics: 2 CTEs + LEFT JOIN across customers, orders, reviews | All segments have customers > 0 |

---

## 4. QueryEngine Features

Tests for nested field access, array flattening, and format output using a smaller hand-crafted dataset with known values.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 46 | `test_llm_schema_context` | `describe_tables()` returns schema with table names | Contains "products", "orders"; length > 50 |
| 47 | `test_query_nested_fields_dot_notation` | Dot notation for nested fields (`specs.cpu`, `specs.ram`) | 2 rows (Laptop, Phone); CPU != "N/A" |
| 48 | `test_unnest_flatten_arrays` | UNNEST + JOIN to aggregate quantities per product | Laptop=2, Phone=3, Monitor=5 (exact values) |
| 49 | `test_complex_nesting_with_list_contains` | UNNEST + JOIN + `list_contains()` filter | Alice and Charlie found; Bob excluded |
| 50 | `test_nested_field_format_output` | `format_query()` works with nested field queries | Grid borders present; product names visible |

---

## 5. Error Handling & Edge Cases

Tests that verify graceful error handling and boundary conditions.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 51 | `test_query_on_unanalyzed_data` | `query()` before `analyze()` raises ValueError | `pytest.raises(ValueError, match="No data analyzed")` |
| 52 | `test_stats_on_unanalyzed_data` | `stats()` before `analyze()` raises ValueError | `pytest.raises(ValueError, match="No data analyzed")` |
| 53 | `test_tree_on_unanalyzed_data` | `tree()` before `analyze()` raises ValueError | `pytest.raises(ValueError, match="No data analyzed")` |
| 54 | `test_invalid_sql_format_query` | Invalid SQL in `format_query()` returns error string | Result starts with `"ERROR:"` |
| 55 | `test_invalid_sql_execute_query` | Invalid SQL in `execute_query()` returns failed QueryResult | `success=False`; `error` is not None; `markdown=""` |
| 56 | `test_single_row_registration` | Registering and querying a single-row list | Returns list with 1 element |
| 57 | `test_invalid_tree_format` | Unknown format string raises ValueError | `pytest.raises(ValueError, match="Unknown format")` |

---

## 6. LLM Prompt Generation (basic)

Basic tests for `generate_prompt()` output content.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 58 | `test_generate_prompt_contains_table_info` | Prompt includes table names, SQL keyword, and UNNEST reference | "products", "orders", "SQL", "UNNEST" present |
| 59 | `test_generate_prompt_with_samples` | Prompt with `samples=3` includes sample values | `"samples="` present |
| 60 | `test_generate_prompt_no_samples` | Prompt with `samples=0` omits sample values | `"samples=["` absent |

---

## 7. execute_query() & QueryResult

Tests for the structured `QueryResult` returned by `execute_query()`.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 61 | `test_execute_query_success` | Successful query returns proper QueryResult | `success=True`; `row_count=3`; `error=None`; markdown contains product name |
| 62 | `test_execute_query_error` | Bad SQL returns failed QueryResult | `success=False`; `error` is not None |
| 63 | `test_execute_query_split` | Split parameter provides preview | `preview` is not None; `row_count=3` |
| 64 | `test_execute_query_max_colwidth` | Column width truncation works | `success=True` (no crash) |

---

## 8. query_print()

Tests for console output via `query_print()`.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 65 | `test_query_print_no_crash` | `query_print()` produces valid stdout output | Captured output contains product name |
| 66 | `test_query_print_with_title` | Title parameter appears in output | `"Test Title"` in captured stdout |

---

## 9. Engine Caching

Tests for internal engine lifecycle within `JsonFlux`.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 67 | `test_jsonflux_engine_caching` | Repeated queries reuse the same cached engine | `engine1 is engine2` |
| 68 | `test_jsonflux_engine_invalidated_on_reanalyze` | Re-analyzing invalidates cache; next query creates fresh engine | `_engine is None` after re-analyze; new engine is different object |

---

## 10. Resource Management

Tests for `close()` methods and context managers.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 69 | `test_query_engine_close` | `QueryEngine.close()` releases resources | `_closed=True`; `tables` is empty |
| 70 | `test_query_engine_context_manager` | `with QueryEngine()` auto-closes on exit | Query works inside; `_closed=True` after |
| 71 | `test_jsonflux_close` | `JsonFlux.close()` clears cached engine | `_engine is None` |
| 72 | `test_jsonflux_context_manager` | `with JsonFlux()` auto-closes on exit | Query works inside; `_engine is None` after |

---

## 11. describe_tables()

Tests for schema context generation.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 73 | `test_describe_tables_contains_info` | Output includes table names and row counts | "products", "orders", "rows" present |
| 74 | `test_describe_tables_with_samples` | Samples appear when requested | `"samples="` present |

---

## 12. Validation & Version

Sanity checks for library integrity.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 75 | `test_validate_returns_empty_on_success` | `validate()` returns empty list when all dependencies are present | `len(errors) == 0` |
| 76 | `test_version_exists` | `__version__` is a dotted version string | `isinstance(str)` and `"."` present |

---

## 13. Hard / Complex SQL

Advanced SQL queries testing DuckDB-specific features, deeply nested fields, UNNEST+JOIN combinations, set operations, and window functions.

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 77 | `test_sql_unnest_items_revenue_by_category` | UNNEST order items + JOIN products for revenue by category | All categories have `total_revenue > 0` |
| 78 | `test_sql_nested_customer_country_group` | GROUP BY on nested `customer.country` with `invoice.amounts.grand_total` avg | All countries have `order_count > 0` and `avg_total > 0` |
| 79 | `test_sql_unnest_items_window_rank` | ROW_NUMBER over unnested items + QUALIFY filter | 20 rows; all have `item_rank = 1` |
| 80 | `test_sql_exists_subquery` | EXISTS subquery: products with 5-star reviews | Each product verified to have a 5-star review via follow-up query |
| 81 | `test_sql_not_exists_subquery` | NOT EXISTS: products with zero reviews | Each product verified to have 0 reviews via follow-up query |
| 82 | `test_sql_ntile_percentile_buckets` | NTILE(4) window function for quartile bucketing | 20 rows; all quartiles in {1, 2, 3, 4} |
| 83 | `test_sql_nested_invoice_breakdown` | Deeply nested field access (`invoice.amounts.grand_total`, `invoice.breakdown.tax`) with arithmetic | `total > 0`, `tax >= 0`, `shipping >= 0` |
| 84 | `test_sql_multi_cte_unnest_join` | Multi-CTE: unnest items, join products, aggregate by brand + segment | `total_qty > 0` and `total_revenue > 0` |
| 85 | `test_sql_except_query` | EXCEPT set operation between review and order customer IDs | Returns a list (no crash) |
| 86 | `test_sql_intersect_query` | INTERSECT: products appearing in both reviews and orders | At least 1 product in common |
| 87 | `test_sql_filter_aggregate` | DuckDB FILTER clause: `COUNT(*) FILTER (WHERE rating >= 4)` | `good_reviews + bad_reviews <= total_reviews` |
| 88 | `test_sql_lateral_unnest_with_nested_join` | Unnest items + join customers (nested FK) + join products | All rows have `purchases > 50` and `spend > 0` |

---

## 14. Auto-Generated System Prompt

Tests that verify `generate_prompt()` dynamically adapts to registered data without hardcoded assumptions. Uses three fixture configurations: multi-table with arrays (K8s pods/nodes), single-table flat (metrics), and multi-table flat (events/hosts).

| # | Test | What It Verifies | Assertion |
|---|------|------------------|-----------|
| 89 | `test_prompt_all_examples_use_real_table_names` | SQL examples in the prompt only reference registered table names | No `FROM TABLE` or `FROM ARR` in any SQL line |
| 90 | `test_prompt_no_generic_placeholders_in_mistakes` | Common Mistakes section uses real field/table names | No `` `arr` `` or `FROM table` in mistakes section |
| 91 | `test_prompt_includes_unnest_when_arrays_exist` | UNNEST pattern appears when data has arrays | "UNNEST" or "unnest" present; "containers" referenced |
| 92 | `test_prompt_includes_dot_notation_when_nested` | Dot notation example for nested objects | `"spec."` or `"Dot Notation"` present |
| 93 | `test_prompt_includes_join_with_detected_keys` | Join keys between tables are detected and shown | "node_name" present; JOIN section with both table names |
| 94 | `test_prompt_includes_unnest_join_pattern` | UNNEST+JOIN pattern is coherent when applicable | Both "pods" and "nodes" in prompt |
| 95 | `test_prompt_includes_table_descriptions` | Descriptions from `register()` appear in prompt | "Active Kubernetes pods", "Cluster nodes with capacity" |
| 96 | `test_prompt_single_table_omits_joins` | Single-table prompt has no JOIN section | "JOIN" absent before DuckDB functions |
| 97 | `test_prompt_flat_data_omits_unnest` | Flat data prompt has no UNNEST pattern in query patterns | "UNNEST" and "unnest(" absent before DuckDB functions |
| 98 | `test_prompt_flat_data_detects_join_keys` | Flat multi-table data correctly detects `event_id` as join key | `"a.event_id = b.event_id"` present in JOIN example |
| 99 | `test_prompt_schema_depth_limits_output` | `max_schema_depth` truncates deep structures | Depth-limited prompt is shorter or equal to unlimited |
| 100 | `test_prompt_with_samples_includes_values` | Sample values from actual data appear in prompt | "samples=" present; actual data values visible |

---

## Test Data

### Design Philosophy

The test data generator (`tests/generator.py`) is purpose-built to produce JSON that covers **every structural pattern you would encounter in real-world APIs, config files, databases exports, and log streams**. The goal is to ensure JSONFlux handles all of them correctly, not just simple flat arrays.

All data is generated deterministically (seed=42) so tests are fully reproducible across machines.

### Generated Tables

| Table | Records | Purpose |
|-------|---------|---------|
| **products** | 1,000 | Nested objects, arrays of primitives, arrays of objects, i18n strings |
| **customers** | 5,000 | Sparse/optional fields, variable-shape objects, deeply nested addresses |
| **orders** | 15,000 | Embedded sub-objects, variable-length item arrays, deeply nested invoices, edge cases |
| **reviews** | 7,500 | Foreign keys to products and customers, simple flat structure for JOIN testing |

### JSON Patterns Covered

The generator deliberately constructs data to exercise every JSON shape you find in the wild:

#### 1. Flat Primitives (strings, ints, floats, booleans)

Every record includes flat scalar fields of all JSON-native types. Products have `price: float`, `active: bool`, `product_id: str`, and customers have `email: str`, `marketing_opt_in: bool`.

#### 2. Nullable Fields

`maybe_null()` randomly inserts `None` at a configurable probability. Product attributes like `color` and `size` randomly include `null`, mimicking real APIs where optional fields are omitted or null. This tests that the analyzer correctly detects and marks nullable types (e.g., `str?`).

#### 3. Sparse / Optional Fields (Shape Variation Within a Collection)

Customer records use `_make_sparse_customer_fields()` to conditionally add fields that only exist on some records — the same key is present on some objects and absent on others:

| Field | Probability | Why It Matters |
|-------|-------------|----------------|
| `phone` | 30% | Simulates optional contact info |
| `company_name` + `vat_number` | 20% | Business-only fields |
| `preferences` (nested object) | 40% | Entire nested object that may not exist |
| `notes` (Unicode string) | 10% | Rare free-text field with special characters |

This is one of the hardest patterns for schema inference — the analyzer must merge schemas across objects that don't share the same keys.

#### 4. Nested Objects (Dot-Notation Access)

Multiple levels of object nesting test dot-notation SQL access:

- `product.attributes.weight_grams` — 2 levels
- `customer.address_book.default_shipping.city` — 3 levels
- `order.invoice.amounts.grand_total` — 3 levels
- `order.invoice.breakdown.tax` — 3 levels
- `order.customer.customer_id` — embedded foreign key inside a nested object

#### 5. Arrays of Objects (UNNEST Required)

The pattern that trips up LLMs the most. The generator creates arrays of objects at multiple depths:

- `order.items[]` — 1-10 line-item objects per order, each with `product_id`, `quantity`, `unit_price`, `discount_rate`, `line_total`
- `product.inventory.warehouse_bins[]` — array of `{bin, qty}` objects inside a nested object
- `customer.address_book.saved_addresses[]` — 0-3 address objects (variable length, can be empty)

#### 6. Arrays of Primitives

Flat arrays that aren't objects — a different UNNEST behavior:

- `product.attributes.dimensions_cm` — `[float, float, float]` (fixed-length numeric array)
- `product.attributes.tags` — `["Electronics", "Books"]` (variable-length string array, 1-3 items)

#### 7. Deeply Nested Structures (32 Levels)

10% of orders contain `edge_cases.deep_nest`, a recursively generated object going 32 levels deep:

```json
{"level": 32, "nested": {"level": 31, "nested": {"level": 30, "nested": ... {"leaf": true, "val": 42}}}}
```

This stress-tests the analyzer's depth handling and verifies that `max_schema_depth` truncation works correctly for LLM prompt generation.

#### 8. Polymorphic Arrays (Mixed-Shape Objects in the Same Array)

10% of orders contain `edge_cases.polymorphic`, an array where each element has a different shape:

```json
[
  {"type": "A", "val": 42},
  {"type": "B", "tags": ["x", "y"]},
  {"type": "C", "meta": {"active": true}}
]
```

This is common in event streams, webhook payloads, and GraphQL responses where a union type produces objects with different field sets. The analyzer must merge these into a unified schema.

#### 9. Mixed-Type Primitive Arrays

The top-level `edge_cases.primitives` array contains all five JSON primitive types in a single array:

```json
["string", 42, 3.14, true, null]
```

This tests that the type analyzer correctly tracks multiple types for one path.

#### 10. Edge-Case Numbers

`edge_cases.all_numbers` contains 10 randomly selected values from extreme numeric cases:

| Value | What It Tests |
|-------|---------------|
| `0`, `-0`, `0.0`, `-0.0` | Zero variants |
| `999999999999999` | Large integers |
| `1.7976931348623157e+308` | Near `Number.MAX_VALUE` (IEEE 754 limit) |
| `2.2250738585072014e-308` | Near `Number.MIN_VALUE` (denormalized float) |
| `1e10`, `1e-10` | Scientific notation |
| `3.141592653589793` | Full-precision float (pi) |

#### 11. Unicode and Special Strings

The `rand_unicode_string()` method produces strings covering real-world encoding challenges:

| Category | Examples |
|----------|----------|
| **Latin extended** | `Ñoño España`, `Ümlauts: äöü ÄÖÜ ß`, `Cześć świat` |
| **CJK** | `日本語テスト` (Japanese) |
| **Cyrillic** | `Привет мир` (Russian) |
| **RTL scripts** | `مرحبا بالعالم` (Arabic), `עברית` (Hebrew) |
| **Thai** | `ไทย` |
| **Greek** | `Ελληνικά` |
| **Emoji** | `🎉 Sale! 50% off 🔥`, `👨‍👩‍👧‍👦 🏳️‍🌈` (multi-codepoint family emoji) |
| **Zero-width chars** | `a\u200bb\u200cc` (invisible joiners) |
| **Control chars** | `\u0001\u0002` |
| **Escape sequences** | `Line1\nLine2\tTabbed`, `Quote: "hello"`, `Backslash: C:\\Users\\data` |
| **Mixed** | `Mixed: Tëst™ © 2025 — Pro·duct` |

These appear in `customer.notes` and `product.localized_names` (en, es, ja, de), testing that parsing and querying handle all encodings without corruption.

#### 12. Empty Structures

Top-level `edge_cases` includes:

- `"empty_obj": {}` — an object with no keys
- `"empty_list": []` — an array with zero elements

These verify that the analyzer and schema renderer don't crash on degenerate inputs.

#### 13. Cross-Table Foreign Keys

Multiple tables share ID columns to enable realistic JOIN testing:

```
products.product_id  <-->  orders.items[].product_id  <-->  reviews.product_id
customers.customer_id  <-->  orders.customer.customer_id  <-->  reviews.customer_id
```

Notably, the customer FK in orders is **nested inside an object** (`orders.customer.customer_id`), not a flat column — forcing the join detection heuristic and SQL queries to handle dot-notation paths in `ON` clauses.

#### 14. Computed / Derived Fields

Order line items have `line_total = quantity * unit_price * (1 - discount_rate)`, and the invoice has `grand_total = subtotal + tax + shipping`. Tests can verify arithmetic in SQL matches these pre-computed values.

#### 15. Variable-Length Arrays

Array lengths are randomized to ensure the analyzer handles varying cardinalities:

| Array | Length Range |
|-------|-------------|
| `order.items` | 1-10 |
| `customer.address_book.saved_addresses` | 0-3 (can be empty) |
| `product.attributes.tags` | 1-3 |
| `product.inventory.warehouse_bins` | always 2 (fixed) |

### Hand-Crafted Fixtures

In addition to the generated dataset, several small hand-crafted fixtures target specific features:

| Fixture | Tables | Purpose |
|---------|--------|---------|
| `rich_query_engine` | products (3), orders (3) | Known exact values for UNNEST+JOIN verification (Laptop=2, Phone=3, Monitor=5) |
| `prompt_engine_multi` | pods (2), nodes (3) | K8s-style data with arrays + nested objects for prompt generation testing |
| `prompt_engine_single` | metrics (2) | Single-table scenario — verifies JOIN sections are omitted |
| `prompt_engine_flat` | events (2), hosts (2) | Flat multi-table data — verifies join key detection without nesting/arrays |

---

## Running Tests

```bash
# All tests
uv run pytest tests/test_jsonflux.py -v

# Specific category
uv run pytest tests/test_jsonflux.py -v -k "prompt"
uv run pytest tests/test_jsonflux.py -v -k "join"
uv run pytest tests/test_jsonflux.py -v -k "unnest"

# With coverage
uv run pytest tests/test_jsonflux.py --cov=jsonflux
```
