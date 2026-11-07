from __future__ import annotations

import random
from typing import Any

from .sql import ISO_DATE

# Track exact distinct values for low-cardinality string fields up to this many.
DISTINCT_CAP = 32
# Strings longer than this are free text, never categorical.
DISTINCT_MAX_LEN = 48


class ReservoirSampler:
    __slots__ = ("k", "rng", "n_seen", "samples", "distinct", "dates")

    def __init__(self, k: int, rng: random.Random):
        self.k = k
        self.rng = rng
        self.n_seen = 0
        self.samples: list[Any] = []
        # Exact set of string values while it stays small (None once it
        # overflows or a non-string value is seen).  Lets the schema list the
        # complete value set of categorical fields ('rain', not 'rainy').
        self.distinct: set[str] | None = set()
        # True while every value seen is an ISO-8601 date/datetime string.
        self.dates = True

    def add(self, v: Any) -> None:
        distinct = self.distinct
        if type(v) is str:
            if distinct is not None and v not in distinct:
                if len(distinct) >= DISTINCT_CAP or len(v) > DISTINCT_MAX_LEN:
                    self.distinct = None
                else:
                    distinct.add(v)
            if self.dates and not ISO_DATE.match(v):
                self.dates = False
        else:
            self.distinct = None
            self.dates = False
        n = self.n_seen = self.n_seen + 1
        samples = self.samples
        k = self.k
        if len(samples) < k:
            samples.append(v)
            return
        # Algorithm R accept test.  random() is several times cheaper than
        # randint() and this line runs once per element past the first k.
        j = int(self.rng.random() * n)
        if j < k:
            samples[j] = v

    def get_exact_k(self) -> list[Any]:
        k = self.k
        if k <= 0:
            return []
        samples = self.samples
        n_seen = self.n_seen
        if n_seen <= 0:
            return [None] * k
        n_samples = len(samples)
        if n_samples >= k:
            return list(samples)
        out = list(samples)
        rng_choice = self.rng.choice
        needed = k - n_samples
        out.extend(rng_choice(samples) for _ in range(needed))
        return out
