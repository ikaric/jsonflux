"""
Sandboxing for the DuckDB engine.

JSONFlux exists so an LLM can answer data questions by writing SQL instead of
being handed a shell with ``curl``/``jq``.  That only removes risk if the SQL
engine itself cannot reach outside the data it was given.  By default DuckDB
*can*: ``read_text('/etc/passwd')``, ``COPY ... TO '/tmp/x'``,
``INSTALL httpfs`` (network), ``ATTACH`` and friends all work out of the box.
A prompt-injected model -- or a malicious value inside the very JSON being
analysed -- could use any of them to exfiltrate files or data.

:class:`SecurityConfig` produces a DuckDB connection that is locked down at
creation time so none of that is possible, while ordinary in-memory analytical
SQL keeps working unchanged.
"""

from __future__ import annotations

import threading
from typing import Any

import duckdb

__all__ = ["SecurityConfig", "connect", "interrupt_after"]


class SecurityConfig:
    """
    Sandbox and resource policy for a :class:`~jsonflux.QueryEngine`.

    All defaults are the safe choice: the connection cannot touch the
    filesystem or network, cannot load extensions, and cannot have its
    configuration changed after creation.

    Args:
        allow_external_access: When ``False`` (default) DuckDB filesystem and
            network access is disabled -- ``read_csv``/``read_text``/``COPY``/
            ``ATTACH``/``INSTALL`` over local or remote paths all fail.  Set
            ``True`` only if you deliberately want SQL to read files/URLs and
            you trust whoever writes the SQL.
        allow_extensions: When ``False`` (default) extension autoinstall and
            autoload are disabled and community extensions are forbidden.
        memory_limit: DuckDB ``memory_limit`` (e.g. ``"2GB"``).  ``None`` leaves
            DuckDB's default (80% of RAM).  Bounds runaway aggregations/joins.
        threads: Number of DuckDB worker threads.  ``None`` uses DuckDB's
            default.
        query_timeout: Seconds after which a running query is interrupted.
            ``None`` disables the timeout.  Guards against pathological queries
            (huge cross joins, ``range(1e12)``, etc.).
        lock_configuration: When ``True`` (default) the settings above are
            frozen so no later ``SET``/``PRAGMA`` can loosen them.  Only turn
            this off if you need to change settings at runtime.
        read_only: When ``True`` (default) only read statements (``SELECT`` and
            ``EXPLAIN``) are accepted; ``INSERT``/``UPDATE``/``DELETE``/
            ``DROP``/``CREATE``/``ATTACH``/``COPY``/``SET`` and friends are
            rejected before execution.  This is defense-in-depth on top of the
            connection sandbox: it stops hostile SQL from dropping your
            registered tables or otherwise mutating session state.  Set
            ``False`` to allow full SQL when you trust the query author.
        max_result_rows: Maximum number of rows a materialising query
            (``query``/``execute_query``/``format_query``) may return before it
            is rejected.  DuckDB's ``memory_limit`` bounds *DuckDB's* memory,
            not the Python list built from the result, so a ``SELECT`` with no
            ``LIMIT`` could otherwise OOM the host process.  ``None`` disables
            the cap.  Use ``query_iter()`` (streaming) or ``query_arrow()``
            (columnar) for intentionally large results.
        max_result_bytes: Approximate byte ceiling for a single materialised
            result, measured over string/blob cells.  Backstops pathological
            single-cell allocations (e.g. ``repeat('x', 2e9)``) that escape
            ``memory_limit``.  ``None`` disables the cap.
    """

    __slots__ = (
        "allow_external_access",
        "allow_extensions",
        "memory_limit",
        "threads",
        "query_timeout",
        "lock_configuration",
        "read_only",
        "max_result_rows",
        "max_result_bytes",
    )

    def __init__(
        self,
        allow_external_access: bool = False,
        allow_extensions: bool = False,
        memory_limit: str | None = "2GB",
        threads: int | None = None,
        query_timeout: float | None = 30.0,
        lock_configuration: bool = True,
        read_only: bool = True,
        max_result_rows: int | None = 1_000_000,
        max_result_bytes: int | None = 256 * 1024 * 1024,
    ) -> None:
        self.allow_external_access = allow_external_access
        self.allow_extensions = allow_extensions
        self.memory_limit = memory_limit
        self.threads = threads
        self.query_timeout = query_timeout
        self.lock_configuration = lock_configuration
        self.read_only = read_only
        self.max_result_rows = max_result_rows
        self.max_result_bytes = max_result_bytes

    def to_duckdb_config(self) -> dict[str, str]:
        """Render the policy as DuckDB startup config options."""
        config: dict[str, str] = {}

        if not self.allow_external_access:
            config["enable_external_access"] = "false"

        if not self.allow_extensions:
            config["autoinstall_known_extensions"] = "false"
            config["autoload_known_extensions"] = "false"
            config["allow_community_extensions"] = "false"

        if self.memory_limit is not None:
            config["memory_limit"] = self.memory_limit

        if self.threads is not None:
            config["threads"] = str(self.threads)

        # Must be applied together with the options above, in the same startup
        # config, so nothing can be relaxed afterwards.
        if self.lock_configuration:
            config["lock_configuration"] = "true"

        return config

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Open a locked-down in-memory DuckDB connection for this policy."""
        return connect(self)


def connect(config: SecurityConfig | None = None) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection sandboxed per ``config``."""
    if config is None:
        config = SecurityConfig()
    return duckdb.connect(":memory:", config=config.to_duckdb_config())


class interrupt_after:
    """
    Context manager that interrupts ``conn`` if the body runs longer than
    ``timeout`` seconds.  ``timeout`` of ``None`` (or non-positive) is a no-op.

    DuckDB has no built-in per-statement timeout, so we arm a watchdog timer
    that calls :meth:`connection.interrupt` -- which raises inside the running
    query and leaves the connection reusable afterwards.
    """

    __slots__ = ("_conn", "_timeout", "_timer")

    def __init__(self, conn: duckdb.DuckDBPyConnection, timeout: float | None) -> None:
        self._conn = conn
        self._timeout = timeout
        self._timer: threading.Timer | None = None

    def __enter__(self) -> interrupt_after:
        if self._timeout is not None and self._timeout > 0:
            self._timer = threading.Timer(self._timeout, self._conn.interrupt)
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
