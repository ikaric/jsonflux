"""
JSONFlux benchmark harness — throughput and memory, measured honestly.

Design notes (to avoid the usual benchmarking mistakes):

* **Repeat + summarise.** Every timing is repeated ``--repeat`` times after a
  warm-up run; we report mean, median, stddev and min, not a single sample.
* **Peak memory is measured in an isolated subprocess.** Peak RSS
  (``ru_maxrss``) is monotonic per process, so each (operation, dataset) runs in
  a fresh ``python`` worker and reports its own peak — this captures the msgspec
  object graph *and* the Arrow allocation together, which in-process
  ``tracemalloc`` cannot.
* **Throughput is reported in the unit that matters** — MB/s and records/s for
  ingestion, rows/s for queries — using the encoded JSON size as the "work".

Usage::

    uv run python bench/benchmark.py                     # default matrix
    uv run python bench/benchmark.py --repeat 9 --sizes 20000,100000
    uv run python bench/benchmark.py --markdown           # emit README tables

Each worker prints one JSON line; the parent aggregates and renders a report.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time

import msgspec

# ---------------------------------------------------------------------------
# Deterministic dataset generation (no Math.random equivalents — seeded RNG)
# ---------------------------------------------------------------------------

_WORDS = "fast slow reliable premium value cheap durable smooth heavy light".split()


def make_dataset(shape: str, n: int, seed: int = 42) -> list[dict]:
    import random

    rng = random.Random(seed)
    out = []
    if shape == "flat":
        for i in range(n):
            out.append(
                {
                    "id": i,
                    "name": f"item_{i}",
                    "amount": round(rng.uniform(1, 9999), 2),
                    "status": rng.choice(["paid", "pending", "refunded"]),
                    "active": rng.random() > 0.5,
                }
            )
    elif shape == "nested":
        for i in range(n):
            out.append(
                {
                    "id": i,
                    "customer": f"C{i % 1000}",
                    "amount": round(rng.uniform(1, 9999), 2),
                    "status": rng.choice(["paid", "pending", "refunded"]),
                    "region": rng.choice(["us", "eu", "apac", "latam"]),
                    "items": [
                        {"sku": f"S{rng.randint(0, 500)}", "qty": rng.randint(1, 5)}
                        for _ in range(rng.randint(1, 4))
                    ],
                    "meta": {
                        "vip": rng.random() > 0.8,
                        "note": " ".join(rng.choices(_WORDS, k=4)),
                    },
                }
            )
    elif shape == "wide":
        for i in range(n):
            row = {"id": i}
            for c in range(30):
                row[f"col_{c}"] = round(rng.uniform(0, 1000), 3)
            out.append(row)
    else:
        raise ValueError(f"unknown shape {shape}")
    return out


# ---------------------------------------------------------------------------
# Worker: runs one (operation, shape, size) and prints a JSON result line
# ---------------------------------------------------------------------------


def _rss_mb() -> float:
    # Peak RSS over the process lifetime; ru_maxrss is KiB on Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _cur_rss_mb() -> float:
    # Current (resident) RSS from /proc — used to isolate an operation's cost
    # from an earlier transient peak that inflated ru_maxrss.
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * resource.getpagesize() / 1e6
    except OSError:
        return _rss_mb()


def _stats(times: list[float]) -> dict:
    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stddev": statistics.pstdev(times) if len(times) > 1 else 0.0,
        "min": min(times),
    }


_QUERIES = {
    "query_agg": "SELECT status, count(*) c, sum(amount) s FROM t GROUP BY status",
    "query_filter": "SELECT * FROM t WHERE id % 100 = 0",
    "query_scan": "SELECT * FROM t",
    "query_unnest": (
        "SELECT it.sku, sum(it.qty) q FROM "
        "(SELECT unnest(items) it FROM t) GROUP BY it.sku"
    ),
}


def _dataset_path(shape: str, n: int, seed: int) -> str:
    return os.path.join(
        os.environ.get("TMPDIR", "/tmp"), f"jf_bench_{shape}_{n}_{seed}.json"
    )


def run_worker(op: str, shape: str, n: int, repeat: int, seed: int) -> dict:
    """
    Each worker is a fresh process.  ``ru_maxrss`` (peak RSS) is therefore the
    peak for *this* worker only.  Memory workers avoid generating the dataset
    in-process (that would spike the high-water mark above what the operation
    needs); they read a file written out-of-band by ``gen``.
    """
    from jsonflux import QueryEngine

    path = _dataset_path(shape, n, seed)
    json_bytes = os.path.getsize(path)
    result = {"op": op, "shape": shape, "n": n, "json_mb": json_bytes / 1e6}

    # --- baseline: imports only, no data ---
    if op == "baseline":
        result["peak_rss_mb"] = _rss_mb()
        return result

    # --- ingestion memory (file source): the honest large-data peak.
    #     _bulk forces the full-graph decode; _stream forces the low-memory
    #     path, so the two rows show the before/after directly. ---
    if op in ("mem_register_bulk", "mem_register_stream"):
        threshold = 10**15 if op == "mem_register_bulk" else 0
        eng = QueryEngine(stream_min_bytes=threshold).register("t", path)
        result["peak_rss_mb"] = _rss_mb()
        eng.close()
        return result

    # --- query-result memory: resident bytes the dict result adds, isolated
    #     from register's transient decode spike via current-RSS deltas ---
    if op.startswith("mem_query_"):
        import gc

        qkey = "query_" + op[len("mem_query_") :]
        eng = QueryEngine(max_result_rows=None).register("t", path)
        gc.collect()
        before = _cur_rss_mb()
        rows = eng.query(_QUERIES[qkey])
        after = _cur_rss_mb()
        result["result_mb"] = after - before
        result["rows_out"] = len(rows)
        result["bytes_per_row"] = (after - before) * 1e6 / len(rows) if rows else 0
        eng.close()
        return result

    # --- timing/throughput (repeat + summarise) ---
    if op in ("register_mem", "register_file"):
        src = path
        if op == "register_mem":
            with open(path, "rb") as f:
                src = msgspec.json.decode(f.read())
        eng = QueryEngine().register("t", src)  # warm-up
        eng.close()
        times = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            eng = QueryEngine().register("t", src)
            times.append(time.perf_counter() - t0)
            eng.close()
        st = _stats(times)
        result.update(
            {
                "times": st,
                "mb_per_s": (json_bytes / 1e6) / st["mean"],
                "rec_per_s": n / st["mean"],
            }
        )
        return result

    if op.startswith("query_"):
        with open(path, "rb") as f:
            data = msgspec.json.decode(f.read())
        eng = QueryEngine(max_result_rows=None).register("t", data)
        del data
        sql = _QUERIES[op]
        nrows = len(eng.query(sql))  # warm-up + count
        times = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            r = eng.query(sql)
            times.append(time.perf_counter() - t0)
            del r
        st = _stats(times)
        result.update(
            {
                "times": st,
                "rows_out": nrows,
                "rows_per_s": nrows / st["mean"] if st["mean"] else 0,
            }
        )
        eng.close()
        return result

    raise ValueError(f"unknown op {op}")


# ---------------------------------------------------------------------------
# Parent: spawn workers, aggregate, render
# ---------------------------------------------------------------------------


def _spawn(op: str, shape: str, n: int, repeat: int, seed: int) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            __file__,
            "--worker",
            "--op",
            op,
            "--shape",
            shape,
            "--n",
            str(n),
            "--repeat",
            str(repeat),
            "--seed",
            str(seed),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"worker {op}/{shape}/{n} failed: {proc.stderr[-800:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _gen_file(shape: str, n: int, seed: int) -> None:
    # Generate in a subprocess so the generation peak never pollutes a
    # measurement worker's ru_maxrss.
    subprocess.run(
        [
            sys.executable,
            __file__,
            "--gen",
            "--shape",
            shape,
            "--n",
            str(n),
            "--seed",
            str(seed),
        ],
        check=True,
    )


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--gen", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--op")
    ap.add_argument("--shape")
    ap.add_argument("--n", type=int)
    ap.add_argument("--repeat", type=int, default=7)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sizes", default="20000,100000")
    args = ap.parse_args()

    if args.gen:
        path = _dataset_path(args.shape, args.n, args.seed)
        with open(path, "wb") as f:
            f.write(msgspec.json.encode(make_dataset(args.shape, args.n, args.seed)))
        return

    if args.worker:
        print(
            json.dumps(run_worker(args.op, args.shape, args.n, args.repeat, args.seed))
        )
        return

    sizes = [int(s) for s in args.sizes.split(",")]
    shapes = ["flat", "nested", "wide"]

    for shape in shapes:
        for n in sizes:
            _gen_file(shape, n, args.seed)

    baseline = _spawn("baseline", "flat", sizes[0], 1, args.seed)["peak_rss_mb"]

    print(
        f"\nJSONFlux benchmark — mean±sd over {args.repeat} repeats; "
        f"peak RSS per isolated worker (import baseline {baseline:.0f} MB)\n"
    )

    # ---- Ingestion throughput ----
    print("== Ingestion throughput (register) ==")
    header = (
        f"{'shape':7} {'n':>7} {'JSON MB':>8} {'source':>7} "
        f"{'mean ms':>9} {'±sd':>6} {'MB/s':>7} {'rec/s':>11}"
    )
    print(header + "\n" + "-" * len(header))
    for shape in shapes:
        for n in sizes:
            for op, src in (("register_mem", "memory"), ("register_file", "file")):
                r = _spawn(op, shape, n, args.repeat, args.seed)
                t = r["times"]
                print(
                    f"{shape:7} {n:>7} {r['json_mb']:>8.1f} {src:>7} "
                    f"{_fmt_ms(t['mean']):>9} {_fmt_ms(t['stddev']):>6} "
                    f"{r['mb_per_s']:>7.1f} {r['rec_per_s']:>11,.0f}"
                )

    # ---- Ingestion memory: bulk vs streaming (peak above import baseline) ----
    print("\n== Ingestion peak memory over baseline (register from file) ==")
    mh = (
        f"{'shape':7} {'n':>7} {'JSON MB':>8} {'bulk MB':>8} {'bulk x':>7} "
        f"{'stream MB':>10} {'stream x':>9} {'saved':>7}"
    )
    print(mh + "\n" + "-" * len(mh))
    for shape in shapes:
        for n in sizes:
            b = _spawn("mem_register_bulk", shape, n, 1, args.seed)
            s = _spawn("mem_register_stream", shape, n, 1, args.seed)
            jm = b["json_mb"]
            bo = b["peak_rss_mb"] - baseline
            so = s["peak_rss_mb"] - baseline
            saved = (1 - so / bo) * 100 if bo > 0 else 0
            print(
                f"{shape:7} {n:>7} {jm:>8.1f} {bo:>8.0f} {bo / max(jm, 0.01):>6.1f}x "
                f"{so:>10.0f} {so / max(jm, 0.01):>8.1f}x {saved:>6.0f}%"
            )

    # ---- Queries (nested, largest) ----
    big = sizes[-1]
    print(f"\n== Queries (nested shape, n={big:,}) ==")
    qh = f"{'query':10} {'mean ms':>9} {'±sd':>6} {'rows out':>10} {'rows/s':>12}"
    print(qh + "\n" + "-" * len(qh))
    for op in ("query_agg", "query_filter", "query_unnest", "query_scan"):
        r = _spawn(op, "nested", big, args.repeat, args.seed)
        t = r["times"]
        print(
            f"{op.replace('query_', ''):10} {_fmt_ms(t['mean']):>9} "
            f"{_fmt_ms(t['stddev']):>6} {r['rows_out']:>10,} "
            f"{r['rows_per_s']:>12,.0f}"
        )

    # ---- Query-result memory (resident cost of the dict result) ----
    print(
        f"\n== Query-result memory: cost of materialising dicts (nested, n={big:,}) =="
    )
    print(f"{'query':10} {'rows out':>10} {'result MB':>10} {'bytes/row':>10}")
    print("-" * 44)
    for op in ("mem_query_scan", "mem_query_filter"):
        r = _spawn(op, "nested", big, 1, args.seed)
        print(
            f"{op[len('mem_query_') :]:10} {r.get('rows_out', 0):>10,} "
            f"{r['result_mb']:>10.1f} {r['bytes_per_row']:>10.0f}"
        )

    # cleanup
    for shape in shapes:
        for n in sizes:
            p = _dataset_path(shape, n, args.seed)
            if os.path.exists(p):
                os.unlink(p)
    print()


if __name__ == "__main__":
    main()
