"""Read a table from a live PostgreSQL database, for import and scheduled refresh.

The server connects on someone's behalf, so the same rules as links apply:
the host name's every address must pass ``link.address_problem`` (public only,
unless the instance allows private networks; loopback and cloud metadata
never), and libpq connects to the checked address (``hostaddr``) so DNS cannot
change between the check and the connection.

Reading is as harmless as Prism can make it, whatever the account may do:

* a read-only transaction, a statement timeout and a lock timeout;
* only a table or view the account can see, chosen from a list, named with
  quoted identifiers — no SQL is ever taken from the user;
* rows fetched in batches up to the row limit, and one deadline overall.

The rows become a Parquet file in memory (``Fetched.kind == "parquet"``) so the
existing import, review, versioning and refresh pipeline handles them as it
would an uploaded Parquet file. ``Fetched.etag`` carries an order-independent
fingerprint of the rows: a refresh that reads the same rows in another order is
still recognised as unchanged.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import io
import ipaddress
import json
import re
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from core.errors import ConnectorError
from data.connectors.link import (
    Fetched,
    LinkPolicy,
    Resolver,
    address_problem,
    system_resolver,
)

SCHEME = "postgresql"
SSL_MODES = ("require", "verify-full", "disable")
DEFAULT_PORT = 5432
BATCH = 5_000
_MASK = (1 << 256) - 1


class DatabaseError(ConnectorError):
    """The database cannot be reached or read (refused, unreachable, or no such table)."""


@dataclass(frozen=True)
class PgSource:
    """Where a dataset's rows live. The password is kept elsewhere, encrypted."""

    host: str
    database: str
    user: str
    port: int = DEFAULT_PORT
    table: str = ""  # "schema.table"
    sslmode: str = "require"

    def to_url(self) -> str:
        """A password-free address, stored as the dataset's source and shown to authors."""
        query = {"sslmode": self.sslmode}
        if self.table:
            query["table"] = self.table
        host = f"[{self.host}]" if ":" in self.host else self.host
        return (
            f"{SCHEME}://{quote(self.user, safe='')}@{host}:{self.port}/"
            f"{quote(self.database, safe='')}?{urlencode(query)}"
        )

    @property
    def label(self) -> str:
        return f"{self.host}/{self.database}" + (f" · {self.table}" if self.table else "")


def is_database_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(f"{SCHEME}://")


def check_source(
    *, host: str, port: int | None, database: str, user: str, table: str = "", sslmode: str
) -> PgSource:
    """Validate connection details without connecting. Raises DatabaseError."""
    host = (host or "").strip().rstrip(".").strip("[]")
    database, user, table = (database or "").strip(), (user or "").strip(), (table or "").strip()
    if not _valid_host(host):
        raise DatabaseError("Enter the database server's host name")
    if port is not None and not 1 <= port <= 65535:
        raise DatabaseError("The port must be between 1 and 65535")
    if not database or len(database) > 63:
        raise DatabaseError("Enter the database name")
    if not user or len(user) > 63:
        raise DatabaseError("Enter the user name")
    if sslmode not in SSL_MODES:
        raise DatabaseError(f"Choose an SSL mode: {', '.join(SSL_MODES)}")
    if table:
        _split_table(table)
    return PgSource(
        host=host,
        database=database,
        user=user,
        port=port or DEFAULT_PORT,
        table=table,
        sslmode=sslmode,
    )


_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def _valid_host(host: str) -> bool:
    if _HOSTNAME.fullmatch(host):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def from_url(url: str) -> PgSource:
    parts = urlsplit(url)
    if parts.scheme != SCHEME or not parts.hostname or not parts.username:
        raise DatabaseError("Not a PostgreSQL source")
    query = parse_qs(parts.query)
    return check_source(
        host=parts.hostname,
        port=parts.port,
        database=unquote(parts.path.lstrip("/")),
        user=unquote(parts.username),
        table=query.get("table", [""])[0],
        sslmode=query.get("sslmode", ["require"])[0],
    )


def _split_table(name: str) -> tuple[str, str]:
    schema, dot, table = name.partition(".")
    if not dot:
        schema, table = "public", name
    if not schema or not table or len(schema) > 63 or len(table) > 63 or "\x00" in name:
        raise DatabaseError("Choose a table from the list")
    return schema, table


# ----------------------------------------------------------------------
# Connecting
# ----------------------------------------------------------------------


def _checked_address(src: PgSource, policy: LinkPolicy, resolver: Resolver) -> str:
    try:
        addresses = resolver(src.host, src.port)
    except ConnectorError as exc:
        raise DatabaseError(f"Could not find the database server {src.host}") from exc
    if not addresses:
        raise DatabaseError(f"Could not find the database server {src.host}")
    for addr in addresses:
        problem = address_problem(addr, allow_private=policy.allow_private)
        if problem:
            hint = ""
            if problem.startswith("a private") and not policy.allow_private:
                hint = " (an administrator can allow private networks)"
            raise DatabaseError(
                f"{src.host} points at {problem}, which Prism may not connect to{hint}"
            )
    return addresses[0]


Connector = Callable[..., Any]


def _connect(
    src: PgSource,
    password: str,
    policy: LinkPolicy,
    resolver: Resolver,
    connect: Connector | None,
) -> Any:
    import psycopg

    address = _checked_address(src, policy, resolver)
    params: dict[str, Any] = {
        "host": src.host,  # used for TLS verification and server name only
        "hostaddr": address,  # where libpq actually connects: the checked address
        "port": src.port,
        "dbname": src.database,
        "user": src.user,
        "password": password,
        "sslmode": src.sslmode,
        "connect_timeout": max(2, min(int(policy.connect_timeout_s), 30)),
        "application_name": "Prism",
        # Never use a password file from the Prism server's own disk.
        "passfile": "/nonexistent",
    }
    if src.sslmode == "verify-full":
        params["sslrootcert"] = "system"
    try:
        conn = (connect or psycopg.connect)(**params, autocommit=False)
    except psycopg.OperationalError as exc:
        raise DatabaseError(_friendly(exc, src)) from exc
    try:
        # Settings sent with SET rather than as startup options, which connection poolers
        # often refuse. The transaction is read-only before anything is read.
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true),"
            " set_config('lock_timeout', '5s', true)",
            (f"{int(policy.timeout_s * 1000)}ms",),
        )
    except psycopg.Error as exc:
        conn.close()
        raise DatabaseError(f"Could not prepare a read-only session: {_first_line(exc)}") from exc
    return conn


def _friendly(exc: Exception, src: PgSource) -> str:
    text = str(exc).lower()
    if "password authentication failed" in text or "authentication failed" in text:
        return f"The database refused the user name or password for {src.user}"
    if "does not exist" in text and "database" in text:
        return f"There is no database called {src.database} on {src.host}"
    if "timeout" in text or "timed out" in text:
        return f"{src.host} did not answer in time"
    if "ssl" in text or "certificate" in text:
        return (
            f"The secure connection to {src.host} failed. Check the SSL mode: 'verify-full' "
            "needs a certificate from a public authority"
        )
    if "no pg_hba.conf entry" in text:
        return f"{src.host} does not accept connections from this Prism server"
    return f"Could not connect to {src.host}:{src.port}"


# ----------------------------------------------------------------------
# Listing and reading
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TableInfo:
    name: str  # schema.table
    kind: str  # table | view
    rows: int | None  # the planner's estimate, when known


_LIST_TABLES = """
SELECT n.nspname, c.relname, c.relkind, NULLIF(c.reltuples, -1)::bigint
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\\_%'
  AND has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname = 'public' DESC, n.nspname, c.relname
LIMIT 1000
"""


def list_tables(
    src: PgSource,
    password: str,
    policy: LinkPolicy,
    *,
    resolver: Resolver = system_resolver,
    connect: Connector | None = None,
) -> list[TableInfo]:
    """Tables and views this account may read (up to 1000)."""
    import psycopg

    with _connect(src, password, policy, resolver, connect) as conn:
        try:
            rows = conn.execute(_LIST_TABLES).fetchall()
        except psycopg.Error as exc:
            raise DatabaseError(f"Could not list the tables: {_first_line(exc)}") from exc
    out = []
    for schema, name, kind, estimate in rows:
        full = name if schema == "public" else f"{schema}.{name}"
        out.append(TableInfo(full, "view" if kind in ("v", "m") else "table", estimate))
    return out


def read_table(
    src: PgSource,
    password: str,
    policy: LinkPolicy,
    *,
    max_rows: int,
    known: str | None = None,
    resolver: Resolver = system_resolver,
    connect: Connector | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Fetched:
    """Read the source's table into a Parquet file, or report it unchanged."""
    import psycopg
    from psycopg import sql

    if not src.table:
        raise DatabaseError("Choose a table to import")
    schema, table = _split_table(src.table)
    deadline = clock() + policy.timeout_s
    query = sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    with _connect(src, password, policy, resolver, connect) as conn:
        try:
            with conn.cursor(name="prism_read") as cur:
                cur.itersize = BATCH
                cur.execute(query)
                names: list[str] | None = None
                rows: list[tuple[Any, ...]] = []
                while True:
                    batch = cur.fetchmany(BATCH)
                    if names is None:
                        names = [d.name for d in cur.description or []]
                    if not batch:
                        break
                    rows.extend(batch)
                    if len(rows) > max_rows:
                        raise DatabaseError(
                            f"{src.table} has more than {max_rows:,} rows, the import limit"
                        )
                    if clock() > deadline:
                        raise DatabaseError(f"Reading {src.table} took too long")
        except psycopg.errors.UndefinedTable as exc:
            raise DatabaseError(
                f"There is no table {src.table} (or this user cannot see it)"
            ) from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            raise DatabaseError(f"The user {src.user} may not read {src.table}") from exc
        except psycopg.errors.QueryCanceled as exc:
            raise DatabaseError(f"Reading {src.table} took too long") from exc
        except psycopg.Error as exc:
            raise DatabaseError(f"Could not read {src.table}: {_first_line(exc)}") from exc
    names = names or []
    if not names:
        raise DatabaseError(f"{src.table} has no columns")
    if len(set(names)) != len(names):
        raise DatabaseError(f"{src.table} has duplicate column names")

    cleaned = [[_plain(v) for v in row] for row in rows]
    fingerprint = "rows:" + rows_fingerprint(names, cleaned)
    if known and known == fingerprint:
        return Fetched(url=src.to_url(), not_modified=True, etag=fingerprint)
    data = _parquet(names, cleaned)
    if len(data) > policy.max_bytes:
        mb = policy.max_bytes // (1024 * 1024)
        raise DatabaseError(f"{src.table} is larger than the {mb} MB import limit")
    filename = f"{table}.parquet"
    return Fetched(url=src.to_url(), data=data, kind="parquet", filename=filename, etag=fingerprint)


def _first_line(exc: Exception) -> str:
    return (str(exc).strip().splitlines() or ["error"])[0][:300]


def _plain(v: Any) -> Any:
    """A value pyarrow can store: keep dates, numbers, text and nested JSON; stringify the rest."""
    if v is None or isinstance(v, (bool, int, float, str, dt.date, dt.datetime, decimal.Decimal)):
        if isinstance(v, decimal.Decimal) and not v.is_finite():
            return str(v)
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None  # binary columns are not imported, as for other sources
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str, ensure_ascii=False)
    if isinstance(v, (uuid.UUID, dt.time, dt.timedelta)):
        return str(v)
    return str(v)


def rows_fingerprint(names: list[str], rows: Iterable[list[Any]]) -> str:
    """Order-independent fingerprint: a sum of per-row hashes, plus the column names."""
    total = 0
    count = 0
    for row in rows:
        digest = hashlib.sha256(json.dumps(row, default=str, separators=(",", ":")).encode())
        total = (total + int.from_bytes(digest.digest(), "big")) & _MASK
        count += 1
    head = hashlib.sha256(json.dumps(names).encode()).hexdigest()[:16]
    return f"{head}-{count}-{total:064x}"


def _parquet(names: list[str], rows: list[list[Any]]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns: dict[str, list[Any]] = {n: [] for n in names}
    for row in rows:
        for n, v in zip(names, row, strict=True):
            columns[n].append(v)
    arrays = {}
    for n, values in columns.items():
        try:
            arrays[n] = pa.array(values)
        except (pa.ArrowException, TypeError, ValueError, OverflowError):
            # Mixed or unusual values in one column: keep them as text.
            arrays[n] = pa.array([None if v is None else str(v) for v in values], type=pa.string())
    buf = io.BytesIO()
    pq.write_table(pa.table(arrays), buf)
    return buf.getvalue()
