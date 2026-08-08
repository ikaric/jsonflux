"""
JSONFlux micro-benchmarks.

Run with:

    uv run python bench/benchmark.py
    uv run python bench/benchmark.py --rows 50000 --repeat 5

Measures the operations an LLM agent actually pays for:

* ``register``  -- decode + full-fidelity Arrow table construction
* ``query``     -- a representative aggregation, materialised to dicts
* ``describe``  -- schema/prompt generation the model is fed
* sandbox overhead -- secure vs. permissive connection

All timings are wall-clock best-of-N (lower is better).  These are the numbers
quoted in the README; re-run after changes to keep them honest.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from typing import Callable

from jsonflux import QueryEngine, SecurityConfig
from jsonflux.core.infer import build_arrow_table


def make_orders(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    regions = ["us", "eu", "apac", "latam"]
    orders = []
    for i in range(n):
        orders.append(
            {
                "id": i,
                "customer": f"C{i % 1000}",
                "amount": round(rng.uniform(1, 9999), 2),
                "status": rng.choice(["paid", "pending", "refunded"]),
                "region": rng.choice(regions),
                "items": [
                    {"sku": f"S{rng.randint(0, 500)}", "qty": rng.randint(1, 5)}
                    for _ in range(rng.randint(1, 4))
                ],
                "meta": {"vip": rng.random() > 0.8, "channel": rng.choice("abcd")},
            }
        )
    return orders


def bench(label: str, fn: Callable[[], object], repeat: int) -> float:
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    best = min(times)
    med = statistics.median(times)
    print(f"  {label:<34} best={best * 1000:8.2f} ms   median={med * 1000:8.2f} ms")
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=15000)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    n = args.rows
    repeat = args.repeat
    print(f"\nJSONFlux benchmark — {n:,} order records, best-of-{repeat}\n")

    data = make_orders(n)

    # --- inference / table construction ---
    print("Table construction:")
    bench("build_arrow_table (full scan)", lambda: build_arrow_table(data), repeat)

    def do_register():
        eng = QueryEngine().register("orders", data)
        eng.close()

    bench("QueryEngine.register (secure)", do_register, repeat)

    # --- queries on a pre-registered engine ---
    print("\nQueries (engine already registered):")
    eng = QueryEngine().register("orders", data)
    try:
        agg_sql = """
            SELECT region, status, count(*) AS n, sum(amount) AS revenue
            FROM orders GROUP BY region, status ORDER BY revenue DESC
        """
        bench("GROUP BY aggregation -> dicts", lambda: eng.query(agg_sql), repeat)

        unnest_sql = """
            SELECT it.sku, sum(it.qty) AS qty
            FROM (SELECT unnest(items) AS it FROM orders)
            GROUP BY it.sku ORDER BY qty DESC LIMIT 20
        """
        bench("UNNEST + GROUP BY (nested)", lambda: eng.query(unnest_sql), repeat)

        bench(
            "point filter (WHERE)",
            lambda: eng.query("SELECT * FROM orders WHERE id = 1234"),
            repeat,
        )

        bench("describe_tables (LLM prompt)", lambda: eng.describe_tables(), repeat)
    finally:
        eng.close()

    # --- sandbox overhead ---
    print("\nSandbox overhead (connection open + one query):")

    def secure():
        e = QueryEngine(security=SecurityConfig()).register("t", data[:100])
        e.query("SELECT count(*) FROM t")
        e.close()

    def permissive():
        e = QueryEngine(
            security=SecurityConfig(
                allow_external_access=True,
                lock_configuration=False,
                memory_limit=None,
            )
        ).register("t", data[:100])
        e.query("SELECT count(*) FROM t")
        e.close()

    bench("secure connection", secure, repeat)
    bench("permissive connection", permissive, repeat)
    print()


if __name__ == "__main__":
    main()
