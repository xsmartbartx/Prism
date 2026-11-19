"""PostgreSQL sources: validation, addresses, fingerprints, values, credentials.

The integration test at the end reads from a real PostgreSQL when
PRISM_TEST_DATABASE_URL is set (CI provides one).
"""

from __future__ import annotations

import datetime as dt
import decimal
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from data.connectors import postgres as pg
from data.connectors.link import LinkPolicy
from data.connectors.parquet import read_parquet
from server.services.secrets import SecretUnavailable, seal, unseal

POLICY = LinkPolicy(max_bytes=10_000_000, timeout_s=20)


def src(**kw: Any) -> pg.PgSource:
    base = {"host": "db.example.com", "port": 5432, "database": "shop", "user": "reader",
            "table": "", "sslmode": "require"}
    return pg.check_source(**{**base, **kw})


class TestDetails:
    def test_round_trip_through_the_stored_address(self) -> None:
        s = src(user="ana@corp", database="sales db", table="reporting.orders")
        url = s.to_url()
        assert "password" not in url and url.startswith("postgresql://ana%40corp@db.example.com")
        assert pg.from_url(url) == s
        v6 = src(host="2001:db8::5", table="orders")
        assert "[2001:db8::5]" in v6.to_url() and pg.from_url(v6.to_url()) == v6
        assert pg.is_database_url(url) and not pg.is_database_url("https://x.test/a.csv")

    @pytest.mark.parametrize(
        ("kw", "message"),
        [
            ({"host": ""}, "host name"),
            ({"host": "db.example.com/evil"}, "host name"),
            ({"host": "user@db"}, "host name"),
            ({"host": "-db"}, "host name"),
            ({"port": 0}, "port"),
            ({"port": 70000}, "port"),
            ({"database": ""}, "database name"),
            ({"user": ""}, "user name"),
            ({"sslmode": "allow"}, "SSL mode"),
            ({"table": "a.b.c" + "x" * 70}, "Choose a table"),
            ({"table": "."}, "Choose a table"),
        ],
    )
    def test_rejects(self, kw: dict[str, Any], message: str) -> None:
        with pytest.raises(pg.DatabaseError, match=message):
            src(**kw)

    def test_from_url_rejects_other_addresses(self) -> None:
        with pytest.raises(pg.DatabaseError):
            pg.from_url("https://db.example.com/shop")


class TestConnecting:
    def _never(self, **kw: Any) -> Any:
        raise AssertionError("must not connect")

    @pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "::1"])
    def test_refuses_internal_addresses_before_connecting(self, address: str) -> None:
        with pytest.raises(pg.DatabaseError, match="may not connect"):
            pg.list_tables(src(), "pw", POLICY, resolver=lambda h, p: [address], connect=self._never)

    def test_private_networks_only_when_allowed(self) -> None:
        seen: dict[str, Any] = {}

        class Conn:
            def execute(self, *a: Any) -> Any:
                return self

            def fetchall(self) -> list[Any]:
                return [("public", "orders", "r", 3), ("sales", "big", "v", None)]

            def close(self) -> None: ...

            def __enter__(self) -> Conn:
                return self

            def __exit__(self, *a: Any) -> None: ...

        def connect(**kw: Any) -> Conn:
            seen.update(kw)
            return Conn()

        allowed = LinkPolicy(max_bytes=1, allow_private=True)
        tables = pg.list_tables(src(), "pw", allowed, resolver=lambda h, p: ["10.0.0.5"],
                                connect=connect)
        assert [(t.name, t.kind, t.rows) for t in tables] == [
            ("orders", "table", 3), ("sales.big", "view", None),
        ]
        # libpq connects to the checked address; the name is only used for TLS.
        assert seen["hostaddr"] == "10.0.0.5" and seen["host"] == "db.example.com"
        assert seen["passfile"] == "/nonexistent" and "sslrootcert" not in seen
        pg.list_tables(src(sslmode="verify-full"), "pw", allowed,
                       resolver=lambda h, p: ["10.0.0.5"], connect=connect)
        assert seen["sslrootcert"] == "system"
        with pytest.raises(pg.DatabaseError, match="private networks"):
            pg.list_tables(src(), "pw", POLICY, resolver=lambda h, p: ["10.0.0.5"],
                           connect=self._never)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('FATAL: password authentication failed for user "reader"', "user name or password"),
            ('FATAL: database "shop" does not exist', "no database called shop"),
            ("timeout expired", "did not answer in time"),
            ("SSL error: certificate verify failed", "secure connection"),
            ('no pg_hba.conf entry for host "1.2.3.4"', "does not accept connections"),
            ("something else", "Could not connect"),
        ],
    )
    def test_friendly_errors(self, text: str, expected: str) -> None:
        assert expected in pg._friendly(Exception(text), src())


def test_fingerprint_ignores_row_order_but_not_content() -> None:
    names = ["id", "v"]
    a = pg.rows_fingerprint(names, [[1, "x"], [2, "y"]])
    assert a == pg.rows_fingerprint(names, [[2, "y"], [1, "x"]])
    assert a != pg.rows_fingerprint(names, [[1, "x"], [2, "z"]])
    assert a != pg.rows_fingerprint(names, [[1, "x"], [2, "y"], [2, "y"]])
    assert a != pg.rows_fingerprint(["id", "w"], [[1, "x"], [2, "y"]])


def test_values_become_parquet() -> None:
    row = [
        1, "EU", dt.date(2026, 1, 5), decimal.Decimal("120.50"), True,
        {"a": 1}, uuid.UUID(int=1), dt.datetime(2026, 1, 5, 10, tzinfo=dt.UTC),
        b"\x00\x01", dt.time(8, 30), decimal.Decimal("NaN"),
    ]
    cleaned = [pg._plain(v) for v in row]
    assert cleaned[5] == '{"a": 1}' and cleaned[8] is None and cleaned[9] == "08:30:00"
    names = [f"c{i}" for i in range(len(row))]
    table = read_parquet(pg._parquet(names, [cleaned, [None] * len(row)]))
    assert table.rows[1][:4] == ["1", "EU", "2026-01-05", "120.50"]
    mixed = read_parquet(pg._parquet(["m"], [[1], ["two"]]))  # mixed types fall back to text
    assert [r[0] for r in mixed.rows[1:]] == ["1", "two"]


def test_credentials_are_sealed() -> None:
    token = seal("s3cret", "k" * 32)
    assert "s3cret" not in token and unseal(token, "k" * 32) == "s3cret"
    with pytest.raises(SecretUnavailable, match="secret key changed"):
        unseal(token, "other" * 8)
    with pytest.raises(SecretUnavailable, match="enter it again"):
        unseal(None, "k" * 32)


# ----------------------------------------------------------------------
# A real PostgreSQL (CI and local runs with PRISM_TEST_DATABASE_URL)
# ----------------------------------------------------------------------

URL = os.environ.get("PRISM_TEST_DATABASE_URL")


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[pg.PgSource, str]]:
    if not URL:
        pytest.skip("PRISM_TEST_DATABASE_URL not set")
    import psycopg
    from sqlalchemy.engine import make_url

    u = make_url(URL)
    admin = psycopg.connect(host=u.host, port=u.port or 5432, dbname=u.database, user=u.username,
                            password=u.password or "", autocommit=True)
    admin.execute("DROP SCHEMA IF EXISTS prism_src_test CASCADE")
    admin.execute("CREATE SCHEMA prism_src_test")
    admin.execute(
        "CREATE TABLE prism_src_test.orders (id int PRIMARY KEY, region text, placed date,"
        " total numeric(10,2), meta jsonb, at timestamptz)"
    )
    admin.execute(
        "INSERT INTO prism_src_test.orders VALUES"
        " (1,'EU','2026-01-05',120.50,'{\"a\":1}','2026-01-05 10:00+01'),"
        " (2,'US','2026-01-12',80.00,NULL,NULL), (3,'APAC','2026-02-02',300.25,'[1]',NULL)"
    )
    admin.execute("CREATE VIEW prism_src_test.big AS SELECT * FROM prism_src_test.orders"
                  " WHERE total > 100")
    # The test database is reached on localhost; production refuses loopback.
    monkeypatch.setattr(pg, "address_problem", lambda a, allow_private: None)
    s = pg.check_source(host=u.host or "localhost", port=u.port or 5432, database=u.database or "",
                        user=u.username or "", table="prism_src_test.orders", sslmode="disable")
    try:
        yield s, u.password or ""
    finally:
        admin.execute("DROP SCHEMA prism_src_test CASCADE")
        admin.close()


def test_live_read(live: tuple[pg.PgSource, str]) -> None:
    s, password = live
    names = [t.name for t in pg.list_tables(s, password, POLICY)]
    assert "prism_src_test.orders" in names and "prism_src_test.big" in names

    got = pg.read_table(s, password, POLICY, max_rows=100)
    assert got.kind == "parquet" and got.filename == "orders.parquet" and got.etag
    rows = read_parquet(got.data).rows
    assert rows[0] == ["id", "region", "placed", "total", "meta", "at"]
    assert ["1", "EU", "2026-01-05", "120.50", '{"a": 1}', "2026-01-05 09:00:00"] in rows
    assert pg.read_table(s, password, POLICY, max_rows=100, known=got.etag).not_modified
    with pytest.raises(pg.DatabaseError, match="more than 2 rows"):
        pg.read_table(s, password, POLICY, max_rows=2)
    view = pg.check_source(host=s.host, port=s.port, database=s.database, user=s.user,
                           table="prism_src_test.big", sslmode="disable")
    assert len(read_parquet(pg.read_table(view, password, POLICY, max_rows=10).data).rows) == 3
    missing = pg.check_source(host=s.host, port=s.port, database=s.database, user=s.user,
                              table="prism_src_test.nope", sslmode="disable")
    with pytest.raises(pg.DatabaseError, match="no table"):
        pg.read_table(missing, password, POLICY, max_rows=10)


def test_live_session_is_read_only(live: tuple[pg.PgSource, str]) -> None:
    import psycopg

    s, password = live
    conn = pg._connect(s, password, POLICY, pg.system_resolver, None)
    try:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM prism_src_test.orders")
    finally:
        conn.close()
